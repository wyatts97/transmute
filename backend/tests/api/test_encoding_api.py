"""HTTP-level tests for advanced options, presets, capabilities, probe and cancel.

The app here is the real API router over temporary SQLite databases, with
authentication replaced by a fixed user. Encoder availability is pinned to
an AMD Cezanne-like host (VAAPI H.264/HEVC) so results don't depend on the
machine running the tests.
"""
from __future__ import annotations

import hashlib
import threading
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import api
from api import deps
from background.encode_tracking import running_job_cancels
from compressors.ffmpeg_compress import FFmpegCompressor
from compressors.pillow_compress import PillowCompressor
from converters.converter_interface import ConverterInterface
from converters.ffmpeg_convert import FFmpegConverter
from converters.pillow_convert import PillowConverter
from db import (
    CompressionDB,
    CompressionJobDB,
    CompressionRelationsDB,
    ConversionDB,
    ConversionJobDB,
    ConversionRelationsDB,
    FileDB,
    PresetDB,
)
from encoding.capabilities import Capabilities
from registry import compressor_registry, registry


USER = {"uuid": "user-a", "username": "alice", "role": "member", "disabled": False}
OTHER_USER_ID = "user-b"

CEZANNE = Capabilities(
    ffmpeg_version="7.1.1",
    compiled_encoders=frozenset({
        "libx264", "libx265", "libsvtav1", "libvpx-vp9", "h264_vaapi", "hevc_vaapi",
        "aac", "libopus", "libmp3lame", "ac3", "libvorbis", "flac", "pcm_s16le",
    }),
    vaapi_device="/dev/dri/renderD128",
    usable_hw_encoders=frozenset({"h264_vaapi", "hevc_vaapi"}),
    usable_hw_10bit_encoders=frozenset({"hevc_vaapi"}),
    vaapi_driver="Mesa Gallium driver 25.0.7 for AMD Radeon Graphics (radeonsi, renoir)",
)

VIDEO = {"mp4", "mkv", "webm", "mov", "wmv"}
IMAGE = {"png", "jpeg", "webp", "avif", "bmp"}


class DocConverter(ConverterInterface):
    """Stand-in for a converter that doesn't take advanced options."""


@pytest.fixture
def env(tmp_path, safe_path_test_settings, monkeypatch):
    db_path = str(tmp_path / "transmute.db")
    for cls in (FileDB, ConversionDB, CompressionDB, ConversionJobDB, CompressionJobDB,
                ConversionRelationsDB, CompressionRelationsDB, PresetDB):
        monkeypatch.setattr(cls, "DB_PATH", db_path)
    for target in ("converters.ffmpeg_convert", "compressors.ffmpeg_compress", "api.routes.capabilities"):
        monkeypatch.setattr(f"{target}.get_capabilities", lambda: CEZANNE)
    for target in ("services.compression_service", "compressors.pillow_compress"):
        monkeypatch.setattr(f"{target}.get_settings", lambda: safe_path_test_settings)

    def find_converter(input_format, output_format):
        if input_format in VIDEO and output_format in VIDEO:
            return FFmpegConverter
        if input_format in IMAGE and output_format in IMAGE:
            return PillowConverter
        if output_format == "pdf":
            return DocConverter
        return None

    def find_compressor(media_format):
        return FFmpegCompressor if media_format in VIDEO else (PillowCompressor if media_format in IMAGE else None)

    monkeypatch.setattr(registry, "get_converter_for_conversion", find_converter)
    monkeypatch.setattr(compressor_registry, "get_compressor_for_format", find_compressor)

    dbs = {
        "file": FileDB(), "conversion": ConversionDB(), "compression": CompressionDB(),
        "conversion_jobs": ConversionJobDB(), "compression_jobs": CompressionJobDB(),
        "conversion_relations": ConversionRelationsDB(), "compression_relations": CompressionRelationsDB(),
        "presets": PresetDB(),
    }
    settings_db = MagicMock()
    settings_db.get_settings.return_value = {"keep_originals": True}
    levels_db = MagicMock()
    levels_db.get.return_value = None

    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    app.dependency_overrides.update({
        deps.get_current_active_user: lambda: USER,
        deps.get_file_db: lambda: dbs["file"],
        deps.get_conversion_db: lambda: dbs["conversion"],
        deps.get_compression_db: lambda: dbs["compression"],
        deps.get_conversion_job_db: lambda: dbs["conversion_jobs"],
        deps.get_compression_job_db: lambda: dbs["compression_jobs"],
        deps.get_conversion_relations_db: lambda: dbs["conversion_relations"],
        deps.get_compression_relations_db: lambda: dbs["compression_relations"],
        deps.get_preset_db: lambda: dbs["presets"],
        deps.get_settings_db: lambda: settings_db,
        deps.get_default_compression_levels_db: lambda: levels_db,
    })

    class Env:
        client = TestClient(app)
        settings = safe_path_test_settings

        @staticmethod
        def db(name):
            return dbs[name]

        @staticmethod
        def add_file(ext: str, data: bytes | None = None, user_id: str = USER["uuid"], image: Image.Image | None = None) -> str:
            file_id = str(uuid.uuid4())
            path = safe_path_test_settings.upload_dir / f"{uuid.uuid4().hex}.{ext}"
            if image is not None:
                image.save(path)
            else:
                path.write_bytes(data or b"\x00" * 1024)
            dbs["file"].insert_file_metadata({
                "id": file_id, "storage_path": str(path), "original_filename": f"source.{ext}",
                "media_type": ext, "extension": f".{ext}", "size_bytes": path.stat().st_size,
                "sha256_checksum": hashlib.sha256(path.read_bytes()).hexdigest(), "user_id": user_id,
            })
            return file_id

    yield Env
    for db in dbs.values():
        db.close()


def _detail(response) -> str:
    detail = response.json()["detail"]
    return detail[0]["msg"] if isinstance(detail, list) else detail


# ── backwards compatibility ─────────────────────────────────────────

def test_legacy_job_request_is_unchanged(env):
    file_id = env.add_file("mp4")
    response = env.client.post("/api/jobs", json={"id": file_id, "output_format": "mkv", "quality": "high"})
    assert response.status_code == 201
    job = response.json()
    assert (job["quality"], job["status"], job["options"], job["preset"]) == ("high", "queued", None, None)
    assert env.db("conversion_jobs").get_job(job["id"])["options_json"] is None


def test_empty_options_object_keeps_legacy_path(env):
    file_id = env.add_file("mp4")
    job = env.client.post("/api/compression-jobs", json={"id": file_id, "compression_level": "max", "options": {}}).json()
    assert job["options"] is None
    assert env.db("compression_jobs").get_job(job["id"])["options_json"] is None


# ── options and presets on jobs ─────────────────────────────────────

def test_conversion_job_stores_resolved_options(env):
    file_id = env.add_file("mp4")
    response = env.client.post("/api/jobs", json={
        "id": file_id, "output_format": "mkv",
        "options": {"video": {"codec": "hevc", "qp": 24, "bit_depth": 10}, "audio": {"codec": "opus", "bitrate_kbps": 128}},
    })
    assert response.status_code == 201, response.text
    options = response.json()["options"]
    assert options["video"] == {"codec": "hevc", "qp": 24, "bit_depth": 10}
    assert options["audio"] == {"codec": "opus", "bitrate_kbps": 128}

    fetched = env.client.get(f"/api/jobs/{response.json()['id']}").json()
    assert fetched["options"] == options


def test_preset_with_overrides(env):
    file_id = env.add_file("mp4")
    job = env.client.post("/api/jobs", json={
        "id": file_id, "output_format": "mp4", "preset": "web-1080p-h264", "options": {"video": {"crf": 20}},
    }).json()
    assert job["preset"] == "web-1080p-h264"
    assert job["options"]["video"]["crf"] == 20
    assert job["options"]["video"]["max_height"] == 1080
    assert job["options"]["video"]["encoder"] == "libx264"


@pytest.mark.parametrize(
    ("payload", "field", "message"),
    [
        ({"output_format": "webm", "options": {"video": {"codec": "h264"}}}, "options", "webm can't hold h264 video"),
        ({"output_format": "mkv", "options": {"video": {"encoder": "h264_vaapi", "bit_depth": 10}}}, "options", "can't encode 10-bit"),
        ({"output_format": "wmv", "options": {"video": {"codec": "h264"}}}, "options", "aren't supported for wmv"),
        ({"output_format": "mkv", "preset": "nope"}, "preset", "Unknown preset 'nope'"),
    ],
)
def test_invalid_options_are_rejected_at_submit(env, payload, field, message):
    file_id = env.add_file("mp4")
    response = env.client.post("/api/jobs", json={"id": file_id, **payload})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", field]
    assert message in detail[0]["msg"]
    assert env.db("conversion_jobs").list_jobs(user_id=USER["uuid"]) == []


def test_unknown_option_fields_use_standard_validation_errors(env):
    file_id = env.add_file("mp4")
    response = env.client.post("/api/jobs", json={"id": file_id, "output_format": "mkv", "options": {"video": {"crff": 20}}})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "crff"


def test_options_rejected_for_converters_without_support(env):
    file_id = env.add_file("png", image=Image.new("RGB", (4, 4)))
    response = env.client.post("/api/jobs", json={"id": file_id, "output_format": "pdf", "options": {"strip_metadata": True}})
    assert response.status_code == 422
    assert "aren't supported for png to pdf" in _detail(response)


def test_image_compression_job_options(env):
    file_id = env.add_file("png", image=Image.new("RGBA", (8, 8)))
    ok = env.client.post("/api/compression-jobs", json={"id": file_id, "options": {"image": {"palette_colors": 64}}})
    assert ok.status_code == 201
    assert ok.json()["options"]["image"] == {"palette_colors": 64}
    bad = env.client.post("/api/compression-jobs", json={"id": file_id, "options": {"image": {"quality": 60}}})
    assert bad.status_code == 422
    assert "PNG is lossless" in _detail(bad)


def test_sync_compression_records_options_in_history(env):
    image = Image.new("RGB", (64, 48), (200, 30, 30))
    file_id = env.add_file("jpeg", image=image)
    response = env.client.post("/api/compressions", json={
        "id": file_id, "preset": "web-image-webp", "options": {"image": {"quality": 40}, "keep_if_larger": True},
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["preset"] == "web-image-webp"
    assert result["options"]["image"]["quality"] == 40
    assert result["encoder_used"] == "pillow"

    history = env.client.get("/api/compressions/complete").json()["compressions"]
    assert len(history) == 1
    assert history[0]["options"]["image"]["quality"] == 40
    assert history[0]["preset"] == "web-image-webp"
    assert history[0]["encoder_used"] == "pillow"


# ── presets CRUD ────────────────────────────────────────────────────

def test_preset_crud_and_use(env):
    listed = env.client.get("/api/presets").json()["presets"]
    builtin_ids = {p["id"] for p in listed if p["builtin"]}
    assert {"amd-fast-hevc", "discord-10mb", "web-image-webp"} <= builtin_ids

    created = env.client.post("/api/presets", json={
        "name": "Plex 1080p", "kind": "video",
        "options": {"video": {"codec": "hevc", "crf": 22, "max_height": 1080}, "audio": {"codec": "aac", "bitrate_kbps": 192}},
    })
    assert created.status_code == 201, created.text
    preset = created.json()
    assert preset["builtin"] is False

    file_id = env.add_file("mkv")
    job = env.client.post("/api/jobs", json={"id": file_id, "output_format": "mkv", "preset": preset["id"]}).json()
    assert job["preset"] == preset["id"]
    assert job["options"]["video"]["max_height"] == 1080

    patched = env.client.patch(f"/api/presets/{preset['id']}", json={"name": "Plex 720p", "options": {"video": {"codec": "hevc", "max_height": 720}}})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Plex 720p"
    assert patched.json()["options"]["video"] == {"codec": "hevc", "max_height": 720}

    assert env.client.delete(f"/api/presets/{preset['id']}").status_code == 204
    assert env.client.get(f"/api/presets/{preset['id']}").status_code == 404


def test_presets_are_private_and_builtins_read_only(env):
    other = env.db("presets").insert_preset(user_id=OTHER_USER_ID, name="Theirs", kind="video", options_json="{}")
    assert env.client.get(f"/api/presets/{other['id']}").status_code == 404
    file_id = env.add_file("mp4")
    response = env.client.post("/api/jobs", json={"id": file_id, "output_format": "mkv", "preset": other["id"]})
    assert response.status_code == 422

    assert env.client.get("/api/presets/discord-10mb").json()["options"]["video"]["target_size_mb"] == 9.5
    assert env.client.patch("/api/presets/discord-10mb", json={"name": "x"}).status_code == 403
    assert env.client.delete("/api/presets/discord-10mb").status_code == 403


def test_preset_kind_must_match_options(env):
    response = env.client.post("/api/presets", json={"name": "Bad", "kind": "image", "options": {"video": {"codec": "h264"}}})
    assert response.status_code == 422
    assert "Image presets can't contain options.video" in _detail(response)


# ── capabilities and probe ──────────────────────────────────────────

def test_capabilities(env):
    caps = env.client.get("/api/capabilities").json()
    assert caps["hardware"] == {
        "vaapi_device": "/dev/dri/renderD128",
        "driver": "Mesa Gallium driver 25.0.7 for AMD Radeon Graphics (radeonsi, renoir)",
        "encoders": ["h264_vaapi", "hevc_vaapi"],
        "ten_bit_encoders": ["hevc_vaapi"],
    }
    encoders = {e["name"]: e for e in caps["video_encoders"]}
    assert "av1_vaapi" not in encoders
    assert encoders["hevc_vaapi"]["quality_param"] == "qp"
    assert encoders["libx265"]["presets"][0] == "ultrafast"
    assert caps["default_video_encoders"]["hevc"] == "hevc_vaapi"
    assert caps["default_video_encoders"]["av1"] == "libsvtav1"
    webm = next(c for c in caps["containers"] if c["format"] == "webm")
    assert webm["video_codecs"] == ["av1", "vp9"]
    png = next(f for f in caps["image_formats"] if f["format"] == "png")
    assert (png["quality"], png["palette_colors"]) == (False, True)
    assert any(p["id"] == "amd-fast-hevc" for p in caps["presets"])


def test_probe_image_and_ownership(env):
    image = Image.new("RGBA", (40, 30))
    file_id = env.add_file("png", image=image)
    probe = env.client.get(f"/api/files/{file_id}/probe").json()
    assert probe["kind"] == "image"
    assert probe["image"]["width"] == 40 and probe["image"]["mode"] == "RGBA"

    theirs = env.add_file("png", image=image, user_id=OTHER_USER_ID)
    assert env.client.get(f"/api/files/{theirs}/probe").status_code == 404
    assert env.client.get(f"/api/files/{uuid.uuid4()}/probe").status_code == 404


# ── cancelling running jobs ─────────────────────────────────────────

def _start_running_job(env, kind="conversion_jobs") -> dict:
    file_id = env.add_file("mp4")
    job_db = env.db(kind)
    payload = {"user_id": USER["uuid"], "source_file_id": file_id}
    if kind == "conversion_jobs":
        payload["output_format"] = "mkv"
    job_db.insert_job(payload)
    return job_db.claim_next_queued_job()


def test_cancel_running_options_job(env):
    job = _start_running_job(env)
    job_db = env.db("conversion_jobs")
    event = running_job_cancels.register(job["id"])

    def worker():
        # Stand-in for the queue worker: stop when signalled.
        event.wait(5)
        job_db.mark_cancelled(job["id"])

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        response = env.client.post(f"/api/jobs/{job['id']}/cancel")
    finally:
        thread.join(5)
        running_job_cancels.unregister(job["id"])
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_running_legacy_job_still_conflicts(env):
    job = _start_running_job(env, "compression_jobs")
    response = env.client.post(f"/api/compression-jobs/{job['id']}/cancel")
    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot cancel job with status 'running'"
