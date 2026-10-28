"""Typed, whitelisted encoder options accepted by the API.

These models are the only way callers can influence encoder settings. They
never carry raw FFmpeg arguments: every field is range-checked here and then
checked again against the selected encoder and output container in
``encoding.resolve`` before any command is built.

Unknown fields are rejected (``extra="forbid"``) so typos surface as a 422
instead of being silently ignored.
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


VideoCodec = Literal["h264", "hevc", "av1", "vp9", "copy"]
RateControl = Literal["crf", "cqp", "vbr", "cbr", "target_size"]
AudioCodec = Literal["aac", "opus", "mp3", "flac", "ac3", "vorbis", "pcm", "copy", "none"]
ChromaSubsampling = Literal["4:2:0", "4:2:2", "4:4:4"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VideoOptions(_StrictModel):
    codec: Optional[VideoCodec] = Field(None, description="Target video codec, or `copy` to pass the stream through", json_schema_extra={"example": "hevc"})
    encoder: Optional[str] = Field(None, pattern=r"^[a-z0-9_-]{2,32}$", description="Specific FFmpeg encoder (e.g. `libx265`, `hevc_vaapi`). Must appear in `GET /api/capabilities`. Defaults to the best available encoder for the codec", json_schema_extra={"example": "hevc_vaapi"})
    rate_control: Optional[RateControl] = Field(None, description="`crf` (software constant quality), `cqp` (hardware constant QP), `vbr`, `cbr`, or `target_size`", json_schema_extra={"example": "crf"})
    crf: Optional[int] = Field(None, ge=0, le=63, description="Constant rate factor; valid range depends on the encoder (x264/x265 0-51, SVT-AV1/libvpx 0-63)", json_schema_extra={"example": 24})
    qp: Optional[int] = Field(None, ge=0, le=255, description="Constant QP for hardware encoders (`rate_control=cqp`)", json_schema_extra={"example": 24})
    bitrate_kbps: Optional[int] = Field(None, ge=16, le=500_000, description="Target video bitrate for `vbr`/`cbr`", json_schema_extra={"example": 4000})
    maxrate_kbps: Optional[int] = Field(None, ge=16, le=500_000, description="Peak bitrate cap for `vbr`", json_schema_extra={"example": 6000})
    target_size_mb: Optional[float] = Field(None, gt=0, le=1_000_000, description="Desired output size in MiB for `target_size` (audio included)", json_schema_extra={"example": 700})
    encoder_preset: Optional[Union[int, str]] = Field(None, description="Encoder-native speed preset: x264/x265 names (`ultrafast`..`veryslow`), SVT-AV1 0-13, libvpx/libaom cpu-used 0-8", json_schema_extra={"example": "slow"})
    tune: Optional[str] = Field(None, pattern=r"^[a-z]{2,16}$", description="Encoder tune (x264/x265 only), e.g. `film`, `animation`, `grain`", json_schema_extra={"example": "film"})
    bit_depth: Optional[Literal[8, 10]] = Field(None, description="Output bit depth", json_schema_extra={"example": 10})
    max_width: Optional[int] = Field(None, ge=16, le=16384, description="Downscale to fit this width (never upscales, keeps aspect ratio)", json_schema_extra={"example": 1920})
    max_height: Optional[int] = Field(None, ge=16, le=16384, description="Downscale to fit this height (never upscales, keeps aspect ratio)", json_schema_extra={"example": 1080})
    fps: Optional[float] = Field(None, gt=0, le=240, description="Output frame rate", json_schema_extra={"example": 30})
    keyframe_interval_s: Optional[float] = Field(None, gt=0, le=60, description="Force a keyframe every N seconds", json_schema_extra={"example": 2})


class AudioOptions(_StrictModel):
    codec: Optional[AudioCodec] = Field(None, description="Target audio codec, `copy` to pass through, or `none` to remove audio", json_schema_extra={"example": "opus"})
    bitrate_kbps: Optional[int] = Field(None, ge=8, le=1536, description="Audio bitrate for lossy codecs", json_schema_extra={"example": 128})
    channels: Optional[int] = Field(None, ge=1, le=8, description="Output channel count (e.g. 2 to downmix 5.1)", json_schema_extra={"example": 2})
    sample_rate: Optional[Literal[8000, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000]] = Field(None, description="Output sample rate in Hz", json_schema_extra={"example": 48000})


class ImageOptions(_StrictModel):
    quality: Optional[int] = Field(None, ge=1, le=100, description="Lossy quality (higher = better / larger)", json_schema_extra={"example": 80})
    lossless: Optional[bool] = Field(None, description="Lossless encoding (WebP, JPEG XL)", json_schema_extra={"example": False})
    effort: Optional[int] = Field(None, ge=0, le=10, description="Normalized encoder effort, 0 = fastest, 10 = smallest output. Mapped to WebP method, AVIF speed, JPEG XL effort, PNG zlib level", json_schema_extra={"example": 6})
    chroma_subsampling: Optional[ChromaSubsampling] = Field(None, description="Chroma subsampling for JPEG and AVIF", json_schema_extra={"example": "4:2:0"})
    max_dimension: Optional[int] = Field(None, ge=16, le=65535, description="Downscale so the longest side fits (never upscales)", json_schema_extra={"example": 1920})
    palette_colors: Optional[int] = Field(None, ge=2, le=256, description="Quantize PNG output to a palette of N colors", json_schema_extra={"example": 128})


class TrimOptions(_StrictModel):
    start_s: float = Field(0, ge=0, description="Start offset in seconds", json_schema_extra={"example": 12.5})
    end_s: Optional[float] = Field(None, gt=0, description="End offset in seconds (exclusive)", json_schema_extra={"example": 42})

    @model_validator(mode="after")
    def _end_after_start(self) -> "TrimOptions":
        if self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError("trim.end_s must be greater than trim.start_s")
        return self


class EncodeOptions(_StrictModel):
    """Advanced encoding options shared by conversions and compressions.

    Every field is optional. Anything left unset falls back to the request's
    named ``preset``, then to the legacy ``quality``/``compression_level``
    mapping, then to the encoder's defaults.
    """

    video: Optional[VideoOptions] = None
    audio: Optional[AudioOptions] = None
    image: Optional[ImageOptions] = None
    trim: Optional[TrimOptions] = None
    subtitles: Optional[Literal["copy", "drop"]] = Field(None, description="Copy subtitle streams (mkv output only) or drop them")
    strip_metadata: Optional[bool] = Field(None, description="Remove container/EXIF metadata. The ICC color profile is kept for images")
    keep_if_larger: bool = Field(False, description="Compression only: keep the re-encoded file even if it is larger than the source")
    hw_fallback: bool = Field(True, description="Retry on the matching software encoder if a hardware encode fails")


def merge_options(base: EncodeOptions | None, override: EncodeOptions | None) -> EncodeOptions:
    """Overlay ``override`` onto ``base`` field by field.

    Only fields the caller explicitly set on ``override`` win. When the
    override switches to a different video codec or encoder, the base's
    codec-specific video settings (CRF, preset, tune, bitrate) are dropped so
    an x264 CRF never leaks into, say, an SVT-AV1 encode. Geometry settings
    (size, fps, bit depth, keyframes) carry over.
    """
    if base is None:
        return override.model_copy(deep=True) if override is not None else EncodeOptions()
    if override is None:
        return base.model_copy(deep=True)

    merged = base.model_dump(exclude_none=True)
    patch = override.model_dump(exclude_unset=True)

    base_video = merged.get("video") or {}
    patch_video = patch.get("video") or {}
    switches_codec = (
        ("codec" in patch_video and patch_video["codec"] != base_video.get("codec"))
        or ("encoder" in patch_video and patch_video["encoder"] != base_video.get("encoder"))
    )
    if switches_codec:
        for key in ("encoder", "rate_control", "crf", "qp", "bitrate_kbps", "maxrate_kbps", "encoder_preset", "tune"):
            base_video.pop(key, None)
        # An explicit encoder implies its codec; don't keep the base's.
        if "encoder" in patch_video and "codec" not in patch_video:
            base_video.pop("codec", None)

    base_audio = merged.get("audio") or {}
    patch_audio = patch.get("audio") or {}
    if patch_audio.get("codec") in ("flac", "pcm", "copy", "none"):
        base_audio.pop("bitrate_kbps", None)

    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return EncodeOptions.model_validate(merged)
