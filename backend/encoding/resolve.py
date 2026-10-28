"""Validate merged ``EncodeOptions`` and turn them into a concrete plan.

``plan_av_encode`` is pure: it needs no source file, so routes can call it at
submit time to reject bad options with a 422 before a job is queued, and the
worker calls it again right before encoding.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Optional, Union

from .capabilities import Capabilities
from .codec_matrix import AUDIO_CONTAINERS, VIDEO_CONTAINERS, container_spec
from .encoders import AUDIO_ENCODERS, SOFTWARE_FALLBACK, VIDEO_ENCODERS, VideoEncoderSpec
from .options import EncodeOptions


class EncodeOptionsError(ValueError):
    """Raised when options are invalid for the requested output."""


@dataclass(frozen=True)
class VideoPlan:
    copy: bool
    encoder: Optional[str] = None
    spec: Optional[VideoEncoderSpec] = None
    rate_control: Optional[str] = None
    quality: Optional[int] = None
    bitrate_kbps: Optional[int] = None
    maxrate_kbps: Optional[int] = None
    target_size_mb: Optional[float] = None
    preset: Optional[Union[int, str]] = None
    tune: Optional[str] = None
    bit_depth: int = 8
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    fps: Optional[float] = None
    keyframe_interval_s: Optional[float] = None

    @property
    def hardware(self) -> Optional[str]:
        return self.spec.hardware if self.spec else None

    @property
    def two_pass(self) -> bool:
        return bool(self.spec and self.spec.two_pass and self.rate_control == "target_size")


@dataclass(frozen=True)
class AudioPlan:
    mode: Literal["encode", "copy", "none"]
    codec: Optional[str] = None
    encoder: Optional[str] = None
    bitrate_kbps: Optional[int] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None


@dataclass(frozen=True)
class EncodePlan:
    container: str
    video: Optional[VideoPlan]
    audio: AudioPlan
    trim_start_s: float = 0.0
    trim_end_s: Optional[float] = None
    copy_subtitles: bool = False
    strip_metadata: bool = False
    faststart: bool = False
    hw_fallback: bool = True
    vaapi_device: Optional[str] = None

    @property
    def encoder_used(self) -> Optional[str]:
        if self.video is None:
            return self.audio.encoder
        return "copy" if self.video.copy else self.video.encoder


def _coerce_preset(spec: VideoEncoderSpec, preset: Union[int, str, None]) -> Union[int, str, None]:
    if preset is None:
        return spec.default_preset
    if spec.named_presets:
        if str(preset) not in spec.named_presets:
            raise EncodeOptionsError(
                f"encoder_preset '{preset}' isn't valid for {spec.name}. Use one of: {', '.join(spec.named_presets)}"
            )
        return str(preset)
    if spec.numeric_presets:
        try:
            value = int(preset)
        except (TypeError, ValueError):
            value = None
        low, high = spec.numeric_presets
        if value is None or not low <= value <= high:
            raise EncodeOptionsError(f"encoder_preset for {spec.name} must be an integer from {low} to {high}")
        return value
    raise EncodeOptionsError(f"{spec.name} has no speed presets; remove encoder_preset")


def _plan_video(fmt: str, options: EncodeOptions, caps: Capabilities) -> VideoPlan:
    container = VIDEO_CONTAINERS[fmt]
    video = options.video
    codec = video.codec if video and video.codec else None
    encoder = video.encoder if video and video.encoder else None

    if encoder is not None:
        spec = VIDEO_ENCODERS.get(encoder)
        if spec is None:
            raise EncodeOptionsError(f"Unknown video encoder '{encoder}'. Check GET /api/capabilities for available encoders")
        if codec not in (None, spec.codec):
            raise EncodeOptionsError(f"Encoder {encoder} produces {spec.codec}, not {codec}")
        codec = spec.codec
    codec = codec or container.default_video

    if codec == "copy":
        # Stream copy ignores every other video setting.
        return VideoPlan(copy=True)

    if codec not in container.video_codecs:
        raise EncodeOptionsError(
            f"{fmt} can't hold {codec} video. Supported codecs for {fmt}: {', '.join(sorted(container.video_codecs))}"
        )

    encoder = encoder or caps.default_encoder_for(codec)
    if encoder is None:
        raise EncodeOptionsError(f"No {codec} encoder is available on this server")
    if not caps.is_usable(encoder):
        available = sorted(n for n, s in VIDEO_ENCODERS.items() if s.codec == codec and caps.is_usable(n))
        hint = f" Available {codec} encoders: {', '.join(available)}" if available else ""
        raise EncodeOptionsError(f"Encoder {encoder} isn't available on this server.{hint}")
    spec = VIDEO_ENCODERS[encoder]

    rate_control = (video.rate_control if video else None) or ("cqp" if spec.hardware else "crf")
    # A CRF on a hardware encoder is treated as its constant QP so presets
    # written for software encoders still work on the GPU.
    if rate_control == "crf" and spec.hardware:
        rate_control = "cqp"
    if rate_control == "cqp" and not spec.hardware:
        raise EncodeOptionsError(f"rate_control 'cqp' needs a hardware encoder; use 'crf' with {encoder}")
    if rate_control not in spec.rate_controls:
        raise EncodeOptionsError(
            f"{encoder} doesn't support rate_control '{rate_control}'. Use one of: {', '.join(sorted(spec.rate_controls))}"
        )

    quality = None
    if rate_control in ("crf", "cqp"):
        if spec.hardware:
            quality = video.qp if video and video.qp is not None else (video.crf if video and video.crf is not None else spec.default_quality)
        else:
            if video and video.qp is not None:
                raise EncodeOptionsError(f"qp applies to hardware encoders; use crf with {encoder}")
            quality = video.crf if video and video.crf is not None else spec.default_quality
        low, high = spec.quality_range
        if not low <= quality <= high:
            raise EncodeOptionsError(f"{spec.quality_param} for {encoder} must be from {low} to {high}")

    bitrate = video.bitrate_kbps if video else None
    maxrate = video.maxrate_kbps if video else None
    target_size = video.target_size_mb if video else None
    if rate_control in ("vbr", "cbr") and bitrate is None:
        raise EncodeOptionsError(f"rate_control '{rate_control}' needs bitrate_kbps")
    if rate_control == "target_size" and target_size is None:
        raise EncodeOptionsError("rate_control 'target_size' needs target_size_mb")
    if maxrate is not None and bitrate is not None and maxrate < bitrate:
        raise EncodeOptionsError("maxrate_kbps must be at least bitrate_kbps")

    tune = video.tune if video else None
    if tune is not None and tune not in spec.tunes:
        supported = ", ".join(spec.tunes) if spec.tunes else "none"
        raise EncodeOptionsError(f"tune '{tune}' isn't valid for {encoder}. Supported: {supported}")

    bit_depth = (video.bit_depth if video and video.bit_depth else None) or 8
    if bit_depth not in spec.bit_depths:
        alternatives = sorted(n for n, s in VIDEO_ENCODERS.items() if bit_depth in s.bit_depths and caps.is_usable(n))
        raise EncodeOptionsError(
            f"{encoder} can't encode {bit_depth}-bit video."
            + (f" Encoders that can: {', '.join(alternatives)}" if alternatives else "")
        )

    return VideoPlan(
        copy=False,
        encoder=encoder,
        spec=spec,
        rate_control=rate_control,
        quality=quality,
        bitrate_kbps=bitrate,
        maxrate_kbps=maxrate,
        target_size_mb=target_size,
        preset=_coerce_preset(spec, video.encoder_preset if video else None),
        tune=tune,
        bit_depth=bit_depth,
        max_width=video.max_width if video else None,
        max_height=video.max_height if video else None,
        fps=video.fps if video else None,
        keyframe_interval_s=video.keyframe_interval_s if video else None,
    )


def _plan_audio(fmt: str, options: EncodeOptions, caps: Capabilities) -> AudioPlan:
    container = container_spec(fmt)
    audio = options.audio
    codec = (audio.codec if audio and audio.codec else None) or container.default_audio
    if codec == "none":
        if fmt in AUDIO_CONTAINERS:
            raise EncodeOptionsError(f"{fmt} is an audio format; audio can't be removed")
        return AudioPlan(mode="none")
    if codec == "copy":
        return AudioPlan(mode="copy")
    if codec not in container.audio_codecs:
        raise EncodeOptionsError(
            f"{fmt} can't hold {codec} audio. Supported codecs for {fmt}: {', '.join(sorted(container.audio_codecs))}"
        )

    spec = AUDIO_ENCODERS[codec]
    if caps.compiled_encoders and spec.name not in caps.compiled_encoders:
        raise EncodeOptionsError(f"The {codec} audio encoder ({spec.name}) isn't available on this server")

    bitrate = audio.bitrate_kbps if audio else None
    if spec.lossless and bitrate is not None:
        raise EncodeOptionsError(f"{codec} is lossless; remove audio.bitrate_kbps")
    sample_rate = audio.sample_rate if audio else None
    if sample_rate is not None and spec.sample_rates and sample_rate not in spec.sample_rates:
        raise EncodeOptionsError(
            f"{codec} doesn't support {sample_rate} Hz. Use one of: {', '.join(str(r) for r in sorted(spec.sample_rates))}"
        )
    return AudioPlan(
        mode="encode",
        codec=codec,
        encoder=spec.name,
        bitrate_kbps=bitrate,
        channels=audio.channels if audio else None,
        sample_rate=sample_rate,
    )


def plan_av_encode(output_format: str, options: EncodeOptions, caps: Capabilities) -> EncodePlan:
    """Validate ``options`` for an FFmpeg output and build the encode plan."""
    container = container_spec(output_format)
    if container is None:
        raise EncodeOptionsError(f"Advanced audio/video options aren't supported for {output_format} output yet")
    if options.image is not None:
        raise EncodeOptionsError("options.image applies to image outputs only")

    is_audio = output_format in AUDIO_CONTAINERS
    if is_audio and options.video is not None:
        raise EncodeOptionsError(f"{output_format} is an audio format; remove options.video")
    if options.subtitles == "copy" and not container.subtitle_copy:
        raise EncodeOptionsError(f"Subtitle copy isn't supported for {output_format}; use mkv or set subtitles to 'drop'")

    video = None if is_audio else _plan_video(output_format, options, caps)
    audio = _plan_audio(output_format, options, caps)
    trim = options.trim
    return EncodePlan(
        container=output_format,
        video=video,
        audio=audio,
        trim_start_s=trim.start_s if trim else 0.0,
        trim_end_s=trim.end_s if trim else None,
        copy_subtitles=options.subtitles == "copy",
        strip_metadata=bool(options.strip_metadata),
        faststart=container.faststart,
        hw_fallback=options.hw_fallback,
        vaapi_device=caps.vaapi_device if video is not None and video.hardware == "vaapi" else None,
    )


def software_fallback_plan(plan: EncodePlan, caps: Capabilities) -> EncodePlan | None:
    """Return the plan re-targeted at the software twin of its hardware encoder."""
    video = plan.video
    if video is None or video.copy or not video.hardware or not plan.hw_fallback:
        return None
    software = SOFTWARE_FALLBACK.get(video.encoder)
    if software is None or not caps.is_usable(software):
        return None
    spec = VIDEO_ENCODERS[software]
    rate_control = "crf" if video.rate_control == "cqp" else video.rate_control
    quality = None
    if rate_control == "crf":
        low, high = spec.quality_range
        quality = min(high, max(low, video.quality if video.quality is not None else spec.default_quality))
    bit_depth = video.bit_depth if video.bit_depth in spec.bit_depths else 8
    new_video = replace(
        video, encoder=software, spec=spec, rate_control=rate_control, quality=quality,
        preset=spec.default_preset, tune=None, bit_depth=bit_depth,
    )
    return replace(plan, video=new_video, vaapi_device=None)
