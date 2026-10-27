"""Golden snapshots of the encoder settings produced by the legacy presets.

Requests that only send ``quality`` / ``compression_level`` (no ``options``)
must keep producing exactly what upstream Transmute produced. These tests pin
the full FFmpeg argv and the Pillow save kwargs for every supported
format x preset combination, including unknown preset strings, against a
snapshot recorded from the unmodified upstream code.

Regenerate only when a behavior change is intentional:

    TRANSMUTE_UPDATE_GOLDEN=1 python -m pytest tests/encoding/test_legacy_golden.py
"""
from __future__ import annotations

import json
import os
import subprocess  # nosec B404
from pathlib import Path

import pytest
from PIL import Image

from compressors.ffmpeg_compress import FFmpegCompressor
from compressors.pillow_compress import PillowCompressor
from converters.ffmpeg_convert import FFmpegConverter
from converters.pillow_convert import PillowConverter


GOLDEN_PATH = Path(__file__).parent.parent / "fixtures" / "golden" / "legacy_encode.json"
UPDATE = os.environ.get("TRANSMUTE_UPDATE_GOLDEN") == "1"

# ``bogus`` pins how each encoder treats a preset string it does not know.
COMPRESSION_LEVELS = [None, "light", "balanced", "max", "bogus"]
QUALITIES = [None, "low", "medium", "high", "bogus"]


def _load_golden() -> dict:
    if not GOLDEN_PATH.exists():
        return {}
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def golden_store():
    """Shared snapshot dict; written back to disk once in update mode."""
    store = {} if UPDATE else _load_golden()
    yield store
    if UPDATE:
        # One entry per line keeps snapshot diffs reviewable.
        lines = [
            f"{json.dumps(key)}: {json.dumps(value, separators=(',', ':'), sort_keys=True)}"
            for key, value in sorted(store.items())
        ]
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def _check(store: dict, key: str, actual) -> None:
    if UPDATE:
        store[key] = actual
        return
    assert key in store, f"No golden snapshot for {key}; regenerate with TRANSMUTE_UPDATE_GOLDEN=1"
    assert actual == store[key], f"Legacy output changed for {key}"


def _fake_subprocess(monkeypatch) -> list[list[str]]:
    """Record every subprocess.run call without running anything.

    The empty stdout makes the ffprobe-based timeout estimate fall back to the
    size heuristic, which only affects the timeout, not the argv.
    """
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append([str(part) for part in cmd])

        class Result:
            stdout = ""
            stderr = ""
            returncode = 0

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _normalize_argv(cmd: list[str], *, input_file: Path, settings) -> list[str]:
    """Replace machine-specific paths so snapshots are portable."""
    tmp_prefix = str(settings.tmp_dir)
    out_prefix = str(settings.output_dir)
    normalized = ["<ffmpeg>"]
    for part in cmd[1:]:
        if part == str(input_file):
            normalized.append("<input>")
        elif part.startswith(tmp_prefix):
            normalized.append("<tmp>" + Path(part).suffix)
        elif part.startswith(out_prefix):
            normalized.append("<output>" + Path(part).suffix)
        else:
            normalized.append(part)
    return normalized


def _last_ffmpeg_call(calls: list[list[str]], ffmpeg_path: str) -> list[str]:
    ffmpeg_calls = [c for c in calls if c[0] == ffmpeg_path]
    assert ffmpeg_calls, "FFmpeg was never invoked"
    return ffmpeg_calls[-1]


@pytest.fixture
def media_settings(safe_path_test_settings, monkeypatch):
    monkeypatch.setattr("compressors.ffmpeg_compress.get_settings", lambda: safe_path_test_settings)
    monkeypatch.setattr("compressors.pillow_compress.get_settings", lambda: safe_path_test_settings)
    return safe_path_test_settings


@pytest.mark.parametrize("media_type", sorted(FFmpegCompressor.supported_formats))
def test_ffmpeg_compressor_argv(media_type, media_settings, monkeypatch, golden_store):
    for level in COMPRESSION_LEVELS:
        calls = _fake_subprocess(monkeypatch)
        input_file = media_settings.upload_dir / f"{'c' * 32}.{media_type}"
        input_file.write_bytes(b"\x00" * 4096)
        compressor = FFmpegCompressor(str(input_file), str(media_settings.output_dir), media_type)
        compressor.compress(compression_level=level)
        argv = _last_ffmpeg_call(calls, FFmpegCompressor.ffmpeg_path)
        _check(
            golden_store,
            f"ffmpeg-compress:{media_type}:{level}",
            _normalize_argv(argv, input_file=input_file, settings=media_settings),
        )


@pytest.mark.parametrize("input_type", sorted(FFmpegConverter.supported_input_formats))
def test_ffmpeg_converter_argv(input_type, media_settings, monkeypatch, golden_store):
    for output_type in sorted(FFmpegConverter.get_formats_compatible_with(input_type)):
        for quality in QUALITIES:
            calls = _fake_subprocess(monkeypatch)
            input_file = media_settings.upload_dir / f"{'d' * 32}.{input_type}"
            input_file.write_bytes(b"\x00" * 4096)
            converter = FFmpegConverter(
                str(input_file), str(media_settings.output_dir), input_type, output_type
            )
            if not converter.can_convert():
                continue
            converter.convert(quality=quality)
            argv = _last_ffmpeg_call(calls, FFmpegConverter.ffmpeg_path)
            _check(
                golden_store,
                f"ffmpeg-convert:{input_type}>{output_type}:{quality}",
                _normalize_argv(argv, input_file=input_file, settings=media_settings),
            )


def _json_safe(value):
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@pytest.mark.parametrize("media_type", sorted(PillowCompressor.supported_formats))
def test_pillow_compressor_save_kwargs(media_type, golden_store):
    for level in COMPRESSION_LEVELS:
        kwargs = PillowCompressor._build_save_kwargs(media_type, level)
        _check(
            golden_store,
            f"pillow-compress:{media_type}:{level}",
            {k: _json_safe(v) for k, v in sorted(kwargs.items())},
        )


@pytest.mark.parametrize("output_type", sorted(PillowConverter.get_formats_compatible_with("png")))
def test_pillow_converter_save_kwargs(output_type, safe_path_test_settings, monkeypatch, golden_store):
    """Capture what PillowConverter passes to ``Image.save`` for a PNG source."""
    input_file = safe_path_test_settings.upload_dir / f"{'e' * 32}.png"
    Image.new("RGBA", (8, 6), (10, 20, 30, 128)).save(input_file)

    for quality in QUALITIES:
        saved: list[dict] = []

        def fake_save(self, fp, format=None, **params):
            saved.append({"mode": self.mode, **{k: _json_safe(v) for k, v in sorted(params.items())}})

        converter = PillowConverter(
            str(input_file), str(safe_path_test_settings.output_dir), "png", output_type
        )
        if not converter.can_convert():
            continue
        with monkeypatch.context() as m:
            m.setattr(Image.Image, "save", fake_save)
            converter.convert(quality=quality)
        assert saved, f"Image.save was not called for png>{output_type}"
        _check(golden_store, f"pillow-convert:png>{output_type}:{quality}", saved[-1])
