"""ffprobe wrapper returning the source facts the encode planner needs."""
from __future__ import annotations

import json
import subprocess  # nosec B404
from dataclasses import dataclass, field

from core import validate_safe_path

from . import capabilities


@dataclass(frozen=True)
class VideoStreamInfo:
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    pix_fmt: str | None
    bit_depth: int | None


@dataclass(frozen=True)
class AudioStreamInfo:
    codec: str | None
    channels: int | None
    sample_rate: int | None
    bitrate_kbps: int | None = None


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float | None
    bitrate_kbps: int | None
    container: str | None
    video: VideoStreamInfo | None
    audio: list[AudioStreamInfo] = field(default_factory=list)
    subtitle_count: int = 0

    def to_dict(self) -> dict:
        return {
            "duration_s": self.duration_s,
            "bitrate_kbps": self.bitrate_kbps,
            "container": self.container,
            "video": None if self.video is None else self.video.__dict__,
            "audio": [a.__dict__ for a in self.audio],
            "subtitle_count": self.subtitle_count,
        }


def _parse_rate(value: str | None) -> float | None:
    if not value or value in ("0/0", "0"):
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            return round(float(num) / float(den), 3) if float(den) else None
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _bit_depth(stream: dict) -> int | None:
    raw = stream.get("bits_per_raw_sample")
    if raw and str(raw).isdigit():
        return int(raw)
    pix_fmt = stream.get("pix_fmt") or ""
    for depth in (16, 12, 10):
        if f"p{depth}" in pix_fmt:
            return depth
    return 8 if pix_fmt else None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_probe(data: dict) -> MediaInfo:
    """Build ``MediaInfo`` from ``ffprobe -print_format json`` output."""
    fmt = data.get("format", {}) or {}
    video = None
    audio: list[AudioStreamInfo] = []
    subtitles = 0
    durations = []
    for stream in data.get("streams", []) or []:
        kind = stream.get("codec_type")
        stream_duration = _to_float(stream.get("duration"))
        if stream_duration:
            durations.append(stream_duration)
        if kind == "video" and video is None and not (stream.get("disposition") or {}).get("attached_pic"):
            video = VideoStreamInfo(
                codec=stream.get("codec_name"),
                width=stream.get("width"),
                height=stream.get("height"),
                fps=_parse_rate(stream.get("avg_frame_rate")) or _parse_rate(stream.get("r_frame_rate")),
                pix_fmt=stream.get("pix_fmt"),
                bit_depth=_bit_depth(stream),
            )
        elif kind == "audio":
            audio.append(AudioStreamInfo(
                codec=stream.get("codec_name"),
                channels=stream.get("channels"),
                sample_rate=int(stream["sample_rate"]) if str(stream.get("sample_rate", "")).isdigit() else None,
                bitrate_kbps=round(_to_float(stream.get("bit_rate")) / 1000) if _to_float(stream.get("bit_rate")) else None,
            ))
        elif kind == "subtitle":
            subtitles += 1

    duration = _to_float(fmt.get("duration")) or (max(durations) if durations else None)
    bitrate = _to_float(fmt.get("bit_rate"))
    return MediaInfo(
        duration_s=round(duration, 3) if duration else None,
        bitrate_kbps=round(bitrate / 1000) if bitrate else None,
        container=fmt.get("format_name"),
        video=video,
        audio=audio,
        subtitle_count=subtitles,
    )


def probe_media(path: str, timeout: int = 15) -> MediaInfo | None:
    """Probe ``path`` with ffprobe. Returns ``None`` when probing fails."""
    validate_safe_path(path)
    try:
        # Subprocess is safe here because the path is validated and the
        # command is constructed without request data.
        result = subprocess.run(  # nosec B603
            [capabilities.FFPROBE_PATH, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, timeout=timeout,
        )
        return parse_probe(json.loads(result.stdout))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return None
