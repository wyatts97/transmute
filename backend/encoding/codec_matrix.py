"""Which codecs each output container accepts on the advanced options path.

Containers missing from these tables (flv, wmv, asf, mpeg, ogv, gif, apng,
animated webp, ...) keep working through the legacy ``quality`` /
``compression_level`` presets but reject ``options.video`` / ``options.audio``
with a clear error instead of producing a broken file.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerSpec:
    video_codecs: frozenset[str]
    audio_codecs: frozenset[str]
    default_video: str | None
    default_audio: str | None
    subtitle_copy: bool = False
    faststart: bool = False


VIDEO_CONTAINERS: dict[str, ContainerSpec] = {
    "mp4": ContainerSpec(frozenset({"h264", "hevc", "av1"}), frozenset({"aac", "opus", "mp3", "ac3", "flac"}), "h264", "aac", faststart=True),
    "m4v": ContainerSpec(frozenset({"h264", "hevc"}), frozenset({"aac", "ac3"}), "h264", "aac", faststart=True),
    "mov": ContainerSpec(frozenset({"h264", "hevc"}), frozenset({"aac", "ac3", "pcm"}), "h264", "aac", faststart=True),
    "mkv": ContainerSpec(frozenset({"h264", "hevc", "av1", "vp9"}), frozenset({"aac", "opus", "mp3", "ac3", "flac", "vorbis"}), "h264", "aac", subtitle_copy=True),
    "webm": ContainerSpec(frozenset({"vp9", "av1"}), frozenset({"opus", "vorbis"}), "vp9", "opus"),
    "ts": ContainerSpec(frozenset({"h264", "hevc"}), frozenset({"aac", "ac3", "mp3"}), "h264", "aac"),
    "3gp": ContainerSpec(frozenset({"h264"}), frozenset({"aac"}), "h264", "aac"),
    "f4v": ContainerSpec(frozenset({"h264"}), frozenset({"aac", "mp3"}), "h264", "aac"),
    "avi": ContainerSpec(frozenset({"h264"}), frozenset({"mp3", "ac3", "aac"}), "h264", "mp3"),
}

AUDIO_CONTAINERS: dict[str, ContainerSpec] = {
    "mp3": ContainerSpec(frozenset(), frozenset({"mp3"}), None, "mp3"),
    "aac": ContainerSpec(frozenset(), frozenset({"aac"}), None, "aac"),
    "m4a": ContainerSpec(frozenset(), frozenset({"aac"}), None, "aac", faststart=True),
    "m4b": ContainerSpec(frozenset(), frozenset({"aac"}), None, "aac", faststart=True),
    "opus": ContainerSpec(frozenset(), frozenset({"opus"}), None, "opus"),
    "oga": ContainerSpec(frozenset(), frozenset({"vorbis", "opus", "flac"}), None, "vorbis"),
    "flac": ContainerSpec(frozenset(), frozenset({"flac"}), None, "flac"),
    "ac3": ContainerSpec(frozenset(), frozenset({"ac3"}), None, "ac3"),
    "wav": ContainerSpec(frozenset(), frozenset({"pcm"}), None, "pcm"),
    "mka": ContainerSpec(frozenset(), frozenset({"aac", "opus", "mp3", "flac", "ac3", "vorbis"}), None, "opus"),
}


def container_spec(fmt: str) -> ContainerSpec | None:
    return VIDEO_CONTAINERS.get(fmt) or AUDIO_CONTAINERS.get(fmt)


def is_audio_container(fmt: str) -> bool:
    return fmt in AUDIO_CONTAINERS


def describe_containers() -> list[dict]:
    """JSON-friendly container table for the capabilities endpoint."""
    rows = []
    for kind, table in (("video", VIDEO_CONTAINERS), ("audio", AUDIO_CONTAINERS)):
        for fmt, spec in table.items():
            rows.append({
                "format": fmt,
                "kind": kind,
                "video_codecs": sorted(spec.video_codecs),
                "audio_codecs": sorted(spec.audio_codecs),
                "default_video": spec.default_video,
                "default_audio": spec.default_audio,
                "subtitle_copy": spec.subtitle_copy,
            })
    return rows
