"""Queue workers on the advanced options path: progress, encoder, cancel."""
from __future__ import annotations

import hashlib
import shutil
import subprocess  # nosec B404
import uuid
from unittest.mock import MagicMock, patch

import pytest

from background.compression_queue import _process_compression_job
from background.conversion_queue import _process_job
from background.encode_tracking import ProgressReporter, running_job_cancels
from compressors.ffmpeg_compress import FFmpegCompressor
from db import CompressionDB, CompressionJobDB, CompressionRelationsDB, ConversionJobDB, FileDB
from encoding import EncodeOptions, capabilities
from encoding.capabilities import detect_capabilities
from encoding.ffmpeg_runner import Progress
from services import ConversionFailedError, options_to_json


class _OptionAwareConverter:
    __name__ = "OptionAwareConverter"
    supports_options = True


@pytest.fixture
def conversion_job_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ConversionJobDB, "DB_PATH", str(tmp_path / "jobs.db"))
    db = ConversionJobDB()
    yield db
    db.close()


def _running_job(job_db: ConversionJobDB, options: dict | None) -> dict:
    job_db.insert_job({
        "user_id": "user-a",
        "source_file_id": "file-1",
        "output_format": "mkv",
        "options_json": options_to_json(EncodeOptions.model_validate(options)) if options else None,
        "preset": "amd-fast-hevc" if options else None,
    })
    return job_db.claim_next_queued_job()


def _file_db():
    file_db = MagicMock()
    file_db.get_file_metadata.return_value = {
        "id": "file-1", "user_id": "user-a", "media_type": "mp4", "storage_path": "data/uploads/x.mp4",
    }
    return file_db


def _process(job, job_db):
    _process_job(
        job,
        file_db=_file_db(),
        conversion_db=MagicMock(),
        conversion_relations_db=MagicMock(),
        settings_db=MagicMock(),
        default_qualities_db=MagicMock(),
        job_db=job_db,
    )


def test_progress_reporter_throttles_writes():
    job_db = MagicMock()
    reporter = ProgressReporter(job_db, "job-1", min_interval_s=60)
    for percent in (1, 2, 3, 6, 7, 100):
        reporter(Progress(percent, 1.5, 10))
    written = [call.args[1] for call in job_db.update_progress.call_args_list]
    # First write, then only 5-point jumps and the final 100%.
    assert written == [1, 6, 100]
    assert job_db.update_progress.call_args.kwargs == {"eta_seconds": 10, "speed": 1.5}


def test_progress_reporter_never_raises():
    job_db = MagicMock()
    job_db.update_progress.side_effect = RuntimeError("db locked")
    ProgressReporter(job_db, "job-1")(Progress(50, None, None))


@patch("background.conversion_queue.registry")
@patch("background.conversion_queue.run_conversion_job")
def test_options_job_reports_progress_and_encoder(mock_run, mock_registry, conversion_job_db):
    mock_registry.get_converter_for_conversion.return_value = _OptionAwareConverter
    job = _running_job(conversion_job_db, {"video": {"codec": "hevc"}})

    def fake_run(**kwargs):
        assert kwargs["options"].video.codec == "hevc"
        assert kwargs["preset"] == "amd-fast-hevc"
        kwargs["progress_cb"](Progress(42, 3.2, 72))
        return {"id": "out-1", "encoder_used": "hevc_vaapi"}

    mock_run.side_effect = fake_run
    _process(job, conversion_job_db)

    row = conversion_job_db.get_job(job["id"])
    assert row["status"] == "completed"
    assert (row["progress"], row["eta_seconds"], row["speed"]) == (42, 72, 3.2)
    assert row["encoder_used"] == "hevc_vaapi"
    assert running_job_cancels.request_cancel(job["id"]) is False


@patch("background.conversion_queue.registry")
@patch("background.conversion_queue.run_conversion_job")
def test_cancelled_encode_ends_cancelled_not_failed(mock_run, mock_registry, conversion_job_db):
    mock_registry.get_converter_for_conversion.return_value = _OptionAwareConverter
    job = _running_job(conversion_job_db, {"video": {"codec": "hevc"}})

    def fake_run(**kwargs):
        assert running_job_cancels.request_cancel(job["id"]) is True
        assert kwargs["cancel_event"].is_set()
        raise ConversionFailedError("Encode cancelled")

    mock_run.side_effect = fake_run
    _process(job, conversion_job_db)

    row = conversion_job_db.get_job(job["id"])
    assert row["status"] == "cancelled"
    assert row["error_message"] is None


@patch("background.conversion_queue.registry")
@patch("background.conversion_queue.run_conversion_job")
def test_legacy_job_gets_no_progress_or_cancel(mock_run, mock_registry, conversion_job_db):
    mock_registry.get_converter_for_conversion.return_value = _OptionAwareConverter
    job = _running_job(conversion_job_db, None)
    mock_run.return_value = {"id": "out-1"}
    _process(job, conversion_job_db)

    kwargs = mock_run.call_args.kwargs
    assert kwargs["options"] is None
    assert kwargs["progress_cb"] is None and kwargs["cancel_event"] is None
    assert conversion_job_db.get_job(job["id"])["status"] == "completed"


@patch("background.conversion_queue.registry")
def test_corrupt_stored_options_fail_the_job(mock_registry, conversion_job_db):
    mock_registry.get_converter_for_conversion.return_value = _OptionAwareConverter
    job = _running_job(conversion_job_db, None)
    job["options_json"] = '{"video": {"codec": "mpeg1"}}'
    _process(job, conversion_job_db)
    row = conversion_job_db.get_job(job["id"])
    assert row["status"] == "failed"
    assert "Stored options are invalid" in row["error_message"]


HAVE_FFMPEG = bool(shutil.which(capabilities.FFMPEG_PATH))


@pytest.mark.skipif(not HAVE_FFMPEG, reason="FFmpeg not installed")
def test_compression_job_end_to_end(tmp_path, safe_path_test_settings, monkeypatch):
    """Queue → service → FFmpegCompressor → real FFmpeg → DB rows."""
    db_path = str(tmp_path / "e2e.db")
    for cls in (FileDB, CompressionDB, CompressionJobDB, CompressionRelationsDB):
        monkeypatch.setattr(cls, "DB_PATH", db_path)
    for target in ("services.compression_service.get_settings", "compressors.ffmpeg_compress.get_settings"):
        monkeypatch.setattr(target, lambda: safe_path_test_settings)
    caps = detect_capabilities()
    monkeypatch.setattr("compressors.ffmpeg_compress.get_capabilities", lambda: caps)
    monkeypatch.setattr(
        "background.compression_queue.compressor_registry.get_compressor_for_format",
        lambda fmt: FFmpegCompressor,
    )

    clip = safe_path_test_settings.upload_dir / f"{uuid.uuid4().hex}.mp4"
    subprocess.run(  # nosec B603
        [capabilities.FFMPEG_PATH, "-hide_banner", "-v", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=2",
         "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx264", "-preset", "ultrafast",
         "-crf", "10", "-c:a", "aac", "-shortest", str(clip)],
        check=True, capture_output=True, timeout=60,
    )
    file_db, compression_db, relations_db, job_db = FileDB(), CompressionDB(), CompressionRelationsDB(), CompressionJobDB()
    file_db.insert_file_metadata({
        "id": "src-1", "storage_path": str(clip), "original_filename": "clip.mp4", "media_type": "mp4",
        "extension": ".mp4", "size_bytes": clip.stat().st_size,
        "sha256_checksum": hashlib.sha256(clip.read_bytes()).hexdigest(), "user_id": "user-a",
    })
    options = EncodeOptions.model_validate({
        "video": {"encoder": "libx264", "crf": 35, "encoder_preset": "veryfast", "max_height": 120},
        "audio": {"bitrate_kbps": 48},
    })
    job_db.insert_job({"user_id": "user-a", "source_file_id": "src-1", "options_json": options_to_json(options)})
    job = job_db.claim_next_queued_job()
    settings_db = MagicMock()
    settings_db.get_settings.return_value = {"keep_originals": True}

    _process_compression_job(
        job, file_db=file_db, compression_db=compression_db, compression_relations_db=relations_db,
        settings_db=settings_db, default_compression_levels_db=None, job_db=job_db,
    )

    row = job_db.get_job(job["id"])
    assert row["status"] == "completed", row["error_message"]
    assert row["progress"] == 100
    assert row["encoder_used"] == "libx264"
    output = compression_db.get_file_metadata(row["output_file_id"])
    assert output["options"]["video"]["max_height"] == 120
    assert output["encoder_used"] == "libx264"
    assert output["size_bytes"] < clip.stat().st_size
    for db in (file_db, compression_db, relations_db, job_db):
        db.close()
