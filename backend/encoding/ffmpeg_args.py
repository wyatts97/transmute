"""Build FFmpeg command lines from a validated ``EncodePlan``.

Only the advanced options path uses this module; legacy presets keep their
original command construction in the compressor/converter classes.
"""
from __future__ import annotations

import os

from . import capabilities
from .encoders import AUDIO_ENCODERS
from .probe import MediaInfo
from .resolve import EncodeOptionsError, EncodePlan, VideoPlan

# Muxing overhead reserved when sizing a target-size encode.
_CONTAINER_OVERHEAD = 0.98
# Bitrate assumed for a copied audio track whose bitrate ffprobe can't report.
_ASSUMED_COPY_AUDIO_KBPS = 192
# Lowest video bitrate a target-size encode is allowed to request.
MIN_TARGET_VIDEO_KBPS = 50


def _num(value: float) -> str:
    """Format a number without a trailing ``.0`` (``2.0`` → ``2``)."""
    return f"{value:g}"


def output_duration_s(plan: EncodePlan, info: MediaInfo | None) -> float | None:
    source = info.duration_s if info else None
    end = plan.trim_end_s
    if source is not None and end is not None:
        end = min(end, source)
    if end is None:
        end = source
    if end is None:
        return None
    return max(0.0, end - plan.trim_start_s)


def _audio_kbps_estimate(plan: EncodePlan, info: MediaInfo | None) -> int:
    audio = plan.audio
    if audio.mode == "none":
        return 0
    if audio.mode == "copy":
        tracks = info.audio if info else []
        if not tracks:
            return _ASSUMED_COPY_AUDIO_KBPS
        return sum(t.bitrate_kbps or _ASSUMED_COPY_AUDIO_KBPS for t in tracks)
    if audio.bitrate_kbps:
        return audio.bitrate_kbps
    return AUDIO_ENCODERS[audio.codec].default_bitrate_kbps or 0


def target_video_kbps(plan: EncodePlan, info: MediaInfo | None) -> int:
    """Video bitrate that lands a ``target_size`` encode at the requested size."""
    video = plan.video
    duration = output_duration_s(plan, info)
    if not duration:
        raise EncodeOptionsError("target_size needs a source with a known duration")
    total_kbps = video.target_size_mb * 8192 * _CONTAINER_OVERHEAD / duration
    video_kbps = int(total_kbps - _audio_kbps_estimate(plan, info))
    if video_kbps < MIN_TARGET_VIDEO_KBPS:
        raise EncodeOptionsError(
            f"target_size_mb {video.target_size_mb:g} is too small for {duration:.0f}s of media: "
            f"the video would get {max(video_kbps, 0)} kb/s. Raise the target, trim the clip, or lower the audio bitrate"
        )
    return video_kbps


def _scale_filter(video: VideoPlan) -> str:
    width = f"'min(iw,{video.max_width})'" if video.max_width else "iw"
    height = f"'min(ih,{video.max_height})'" if video.max_height else "ih"
    return f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease:force_divisible_by=2"


def _video_filters(video: VideoPlan) -> list[str]:
    filters: list[str] = []
    if video.fps:
        filters.append(f"fps={_num(video.fps)}")
    if video.max_width or video.max_height:
        filters.append(_scale_filter(video))
    else:
        # 4:2:0 chroma needs even dimensions; pad odd sources by at most 1px.
        filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
    if video.hardware == "vaapi":
        filters.append("format=p010" if video.bit_depth == 10 else "format=nv12")
        filters.append("hwupload")
    else:
        filters.append("format=yuv420p10le" if video.bit_depth == 10 else "format=yuv420p")
    return filters


def _rate_args(video: VideoPlan, bitrate_kbps: int | None) -> list[str]:
    name = video.encoder
    rc = video.rate_control
    if video.hardware == "vaapi":
        if rc == "cqp":
            return ["-rc_mode", "CQP", "-qp", str(video.quality)]
        if rc == "cbr":
            return ["-rc_mode", "CBR", "-b:v", f"{bitrate_kbps}k", "-maxrate", f"{bitrate_kbps}k"]
        maxrate = video.maxrate_kbps or int(bitrate_kbps * 1.5)
        return ["-rc_mode", "VBR", "-b:v", f"{bitrate_kbps}k", "-maxrate", f"{maxrate}k"]

    if rc == "crf":
        args = ["-crf", str(video.quality)]
        if name in ("libvpx-vp9", "libaom-av1"):
            # ``-b:v 0`` selects pure constant-quality mode for libvpx/libaom.
            args += ["-b:v", "0"]
        return args
    if rc == "cbr":
        rate = f"{bitrate_kbps}k"
        return ["-b:v", rate, "-minrate", rate, "-maxrate", rate, "-bufsize", f"{bitrate_kbps * 2}k"]
    args = ["-b:v", f"{bitrate_kbps}k"]
    if video.maxrate_kbps:
        args += ["-maxrate", f"{video.maxrate_kbps}k", "-bufsize", f"{video.maxrate_kbps * 2}k"]
    return args


def _video_codec_args(video: VideoPlan, bitrate_kbps: int | None) -> list[str]:
    args = ["-c:v", video.encoder]
    name = video.encoder
    if name in ("libx264", "libx265"):
        if video.preset is not None:
            args += ["-preset", str(video.preset)]
        if video.tune:
            args += ["-tune", video.tune]
    elif name == "libsvtav1":
        args += ["-preset", str(video.preset)]
    elif name == "libaom-av1":
        args += ["-cpu-used", str(video.preset), "-row-mt", "1"]
    elif name == "libvpx-vp9":
        args += ["-deadline", "good", "-cpu-used", str(video.preset), "-row-mt", "1"]
    args += _rate_args(video, bitrate_kbps)
    if name == "hevc_vaapi" and video.bit_depth == 10:
        args += ["-profile:v", "main10"]
    if video.keyframe_interval_s:
        args += ["-force_key_frames", f"expr:gte(t,n_forced*{_num(video.keyframe_interval_s)})"]
    return args


def _audio_args(plan: EncodePlan) -> list[str]:
    audio = plan.audio
    if audio.mode == "none":
        return ["-an"]
    if audio.mode == "copy":
        return ["-c:a", "copy"]
    args = ["-c:a", audio.encoder]
    if audio.bitrate_kbps:
        args += ["-b:a", f"{audio.bitrate_kbps}k"]
    if audio.codec == "flac":
        args += ["-compression_level", "8"]
    if audio.channels:
        args += ["-ac", str(audio.channels)]
    if audio.sample_rate:
        args += ["-ar", str(audio.sample_rate)]
    return args


def _input_args(plan: EncodePlan, input_file: str, ffmpeg_path: str) -> list[str]:
    args = [ffmpeg_path, "-hide_banner", "-y"]
    if plan.vaapi_device:
        args += ["-vaapi_device", plan.vaapi_device]
    if plan.trim_start_s:
        args += ["-ss", _num(plan.trim_start_s)]
    args += ["-i", input_file]
    if plan.trim_end_s is not None:
        args += ["-t", _num(plan.trim_end_s - plan.trim_start_s)]
    return args


def _map_args(plan: EncodePlan) -> list[str]:
    if plan.video is None:
        # Audio-only output: keep the first audio track.
        return ["-map", "0:a:0"]
    # ``V`` skips attached pictures (cover art) so the real video is chosen.
    args = ["-map", "0:V:0"]
    if plan.audio.mode != "none":
        args += ["-map", "0:a?"]
    if plan.copy_subtitles:
        args += ["-map", "0:s?", "-c:s", "copy"]
    return args


def _two_pass_args(video: VideoPlan, pass_number: int, passlog_prefix: str) -> list[str]:
    if video.encoder == "libx265":
        return ["-x265-params", f"pass={pass_number}:stats={passlog_prefix}.log"]
    return ["-pass", str(pass_number), "-passlogfile", passlog_prefix]


def build_commands(
    plan: EncodePlan,
    *,
    input_file: str,
    output_file: str,
    info: MediaInfo | None = None,
    passlog_prefix: str | None = None,
    ffmpeg_path: str | None = None,
) -> list[list[str]]:
    """Return the FFmpeg command(s) for ``plan``: one, or two for 2-pass."""
    ffmpeg_path = ffmpeg_path or capabilities.FFMPEG_PATH
    video = plan.video
    video_args: list[str] = []
    if video is not None:
        if video.copy:
            video_args = ["-c:v", "copy"]
        else:
            bitrate = video.bitrate_kbps
            if video.rate_control == "target_size":
                bitrate = target_video_kbps(plan, info)
            video_args = ["-vf", ",".join(_video_filters(video))] + _video_codec_args(video, bitrate)

    tail: list[str] = []
    if plan.strip_metadata:
        tail += ["-map_metadata", "-1"]
    if plan.faststart:
        tail += ["-movflags", "+faststart"]

    final = (
        _input_args(plan, input_file, ffmpeg_path)
        + _map_args(plan)
        + video_args
        + _audio_args(plan)
    )

    if video is not None and video.two_pass:
        if not passlog_prefix:
            raise ValueError("Two-pass encodes need a passlog_prefix")
        first = (
            _input_args(plan, input_file, ffmpeg_path)
            + ["-map", "0:V:0"]
            + video_args
            + _two_pass_args(video, 1, passlog_prefix)
            + ["-an", "-f", "null", os.devnull]
        )
        second = final + _two_pass_args(video, 2, passlog_prefix) + tail + [output_file]
        return [first, second]

    return [final + tail + [output_file]]
