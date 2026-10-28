"""End-to-end encodes through real FFmpeg on the advanced options path.

Skipped when no FFmpeg binary is available. The clips are tiny synthetic
test patterns so the whole module runs in a few seconds.
"""
from __future__ import annotations

import shutil
import subprocess  # nosec B404
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from compressors.ffmpeg_compress import FFmpegCompressor
from converters.ffmpeg_convert import FFmpegConverter
from encoding import EncodeOptions, capabilities
from encoding.capabilities import detect_capabilities
from encoding.ffmpeg_runner import (
    FFmpegCancelled,
    parse_progress_block,
    progress_from_block,
    run_ffmpeg,
)
from encoding.probe import probe_media


HAVE_FFMPEG = bool(shutil.which(capabilities.FFMPEG_PATH)) and bool(shutil.which(capabilities.FFPROBE_PATH))
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="FFmpeg/ffprobe not installed")


def test_progress_block_parsing():
    block = parse_progress_block(["frame=10\n", "out_time_us=50000000\n", "speed=2.0x\n", "progress=continue\n"])
    progress = progress_from_block(block, duration_s=100)
    assert (progress.percent, progress.speed, progress.eta_seconds) == (50, 2.0, 25)
    assert progress_from_block({"progress": "end", "speed": "N/A"}, 100).percent == 100
    assert progress_from_block({"out_time_us": "N/A", "progress": "continue"}, 100) is None
    assert progress_from_block({"out_time_us": "1000000"}, None) is None


@pytest.fixture
def media_env(safe_path_test_settings, monkeypatch):
    for target in ("compressors.ffmpeg_compress.get_settings", "converters.ffmpeg_convert.get_settings"):
        monkeypatch.setattr(target, lambda: safe_path_test_settings)
    return safe_path_test_settings


@pytest.fixture(scope="module")
def caps():
    return detect_capabilities()


@pytest.fixture
def clip(media_env) -> Path:
    """A 3 s 320x240 H.264 + AAC test clip in the upload dir."""
    path = media_env.upload_dir / f"{'a1' * 16}.mp4"
    subprocess.run(  # nosec B603
        [
            capabilities.FFMPEG_PATH, "-hide_banner", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True, capture_output=True, timeout=60,
    )
    return path


def _use_caps(monkeypatch, module: str, caps_value):
    monkeypatch.setattr(f"{module}.get_capabilities", lambda: caps_value)


@needs_ffmpeg
def test_detects_real_encoders(caps):
    assert "libx264" in caps.compiled_encoders
    assert caps.ffmpeg_version
    assert caps.default_encoder_for("h264") in ("libx264", "h264_vaapi")


@needs_ffmpeg
def test_compressor_reencodes_to_hevc_with_progress(clip, media_env, monkeypatch, caps):
    _use_caps(monkeypatch, "compressors.ffmpeg_compress", caps)
    progress = []
    compressor = FFmpegCompressor(str(clip), str(media_env.tmp_dir), "mp4")
    options = EncodeOptions.model_validate({
        "video": {"encoder": "libx265", "crf": 30, "encoder_preset": "ultrafast", "max_height": 120},
        "audio": {"codec": "aac", "bitrate_kbps": 64},
        "keep_if_larger": True,
    })
    (output,) = compressor.compress(options=options, progress_cb=progress.append)

    info = probe_media(output)
    assert info.video.codec == "hevc"
    assert (info.video.width, info.video.height) == (160, 120)
    assert info.audio[0].codec == "aac"
    assert compressor.encoder_used == "libx265"
    assert progress and progress[-1].percent == 100
    assert [p.percent for p in progress] == sorted(p.percent for p in progress)


@needs_ffmpeg
def test_converter_mp4_to_webm_vp9(clip, media_env, monkeypatch, caps):
    _use_caps(monkeypatch, "converters.ffmpeg_convert", caps)
    converter = FFmpegConverter(str(clip), str(media_env.tmp_dir), "mp4", "webm")
    options = EncodeOptions.model_validate({
        "video": {"codec": "vp9", "crf": 40, "encoder_preset": 8},
        "audio": {"bitrate_kbps": 48},
    })
    (output,) = converter.convert(options=options)
    info = probe_media(output)
    assert info.video.codec == "vp9"
    assert info.audio[0].codec == "opus"


@needs_ffmpeg
def test_two_pass_target_size_lands_near_target(clip, media_env, monkeypatch, caps):
    _use_caps(monkeypatch, "converters.ffmpeg_convert", caps)
    converter = FFmpegConverter(str(clip), str(media_env.tmp_dir), "mp4", "mkv")
    target_mb = 0.2
    options = EncodeOptions.model_validate({
        "video": {"encoder": "libx264", "rate_control": "target_size", "target_size_mb": target_mb, "encoder_preset": "veryfast"},
        "audio": {"codec": "aac", "bitrate_kbps": 64},
    })
    (output,) = converter.convert(options=options)
    size_mb = Path(output).stat().st_size / (1024 * 1024)
    assert 0.5 * target_mb < size_mb < 1.3 * target_mb
    # Pass logs live in a private temp dir that is cleaned up.
    assert not list(media_env.tmp_dir.glob("encode-*"))


@needs_ffmpeg
def test_failed_hardware_encode_falls_back_to_software(clip, media_env, monkeypatch, caps):
    if "hevc_vaapi" not in caps.compiled_encoders or "libx265" not in caps.compiled_encoders:
        pytest.skip("FFmpeg build lacks hevc_vaapi or libx265")
    # Pretend VAAPI is usable on a device that does not exist, so FFmpeg fails.
    fake_gpu = replace(caps, vaapi_device="/nonexistent/renderD128", usable_hw_encoders=frozenset({"hevc_vaapi"}))
    _use_caps(monkeypatch, "converters.ffmpeg_convert", fake_gpu)
    converter = FFmpegConverter(str(clip), str(media_env.tmp_dir), "mp4", "mkv")
    (output,) = converter.convert(options=EncodeOptions.model_validate({"video": {"codec": "hevc", "qp": 30}}))
    assert converter.encoder_used == "libx265"
    assert probe_media(output).video.codec == "hevc"


@needs_ffmpeg
def test_hardware_failure_without_fallback_raises(clip, media_env, monkeypatch, caps):
    if "hevc_vaapi" not in caps.compiled_encoders:
        pytest.skip("FFmpeg build lacks hevc_vaapi")
    fake_gpu = replace(caps, vaapi_device="/nonexistent/renderD128", usable_hw_encoders=frozenset({"hevc_vaapi"}))
    _use_caps(monkeypatch, "converters.ffmpeg_convert", fake_gpu)
    converter = FFmpegConverter(str(clip), str(media_env.tmp_dir), "mp4", "mkv")
    with pytest.raises(RuntimeError, match="FFmpeg failed"):
        converter.convert(options=EncodeOptions.model_validate({"video": {"codec": "hevc"}, "hw_fallback": False}))


def _endless_encode_cmd() -> list[str]:
    return [
        capabilities.FFMPEG_PATH, "-hide_banner", "-y", "-re",
        "-f", "lavfi", "-i", "testsrc=size=64x64:rate=25:duration=600",
        "-f", "null", "-",
    ]


@needs_ffmpeg
def test_cancel_event_stops_running_encode():
    cancel = threading.Event()
    seen = []

    def on_progress(progress):
        seen.append(progress)
        cancel.set()

    with pytest.raises(FFmpegCancelled):
        run_ffmpeg(_endless_encode_cmd(), timeout_s=60, duration_s=600, progress_cb=on_progress, cancel_event=cancel)
    assert seen


@needs_ffmpeg
def test_watchdog_enforces_timeout():
    with pytest.raises(RuntimeError, match="timed out after 1 seconds"):
        run_ffmpeg(_endless_encode_cmd(), timeout_s=1, duration_s=600)


@needs_ffmpeg
def test_ffmpeg_errors_include_stderr(media_env):
    missing = media_env.upload_dir / "missing.mp4"
    with pytest.raises(RuntimeError, match=r"(?s)FFmpeg failed: .*missing\.mp4"):
        run_ffmpeg([capabilities.FFMPEG_PATH, "-hide_banner", "-i", str(missing), "-f", "null", "-"], timeout_s=30)
