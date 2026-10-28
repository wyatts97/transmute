"""Static knowledge about the encoders the advanced options path can drive.

Each spec lists what an encoder accepts (rate-control modes, quality range,
speed presets, bit depths) so options can be validated before FFmpeg runs and
so ``GET /api/capabilities`` can describe the controls to clients. Whether an
encoder is actually usable on this host is decided by ``capabilities``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


X26X_PRESETS: tuple[str, ...] = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
)


@dataclass(frozen=True)
class VideoEncoderSpec:
    name: str
    codec: str
    hardware: Optional[str]                     # e.g. "vaapi"; None for software encoders
    rate_controls: frozenset[str]
    quality_range: tuple[int, int]              # CRF (software) or QP (hardware)
    default_quality: int
    named_presets: tuple[str, ...] = ()         # x264/x265 style presets
    numeric_presets: Optional[tuple[int, int]] = None  # SVT-AV1 preset / libvpx cpu-used
    default_preset: Optional[Union[int, str]] = None
    tunes: tuple[str, ...] = ()
    bit_depths: frozenset[int] = frozenset({8})
    two_pass: bool = False

    @property
    def quality_param(self) -> str:
        return "qp" if self.hardware else "crf"

    def describe(self) -> dict:
        """JSON-friendly description for the capabilities endpoint."""
        return {
            "name": self.name,
            "codec": self.codec,
            "hardware": self.hardware,
            "rate_controls": sorted(self.rate_controls),
            "quality_param": self.quality_param,
            "quality_range": list(self.quality_range),
            "default_quality": self.default_quality,
            "presets": list(self.named_presets) if self.named_presets else (
                list(range(self.numeric_presets[0], self.numeric_presets[1] + 1)) if self.numeric_presets else []
            ),
            "default_preset": self.default_preset,
            "tunes": list(self.tunes),
            "bit_depths": sorted(self.bit_depths),
            "two_pass": self.two_pass,
        }


_SOFTWARE_RC = frozenset({"crf", "vbr", "cbr", "target_size"})
_VAAPI_RC = frozenset({"cqp", "vbr", "cbr", "target_size"})

VIDEO_ENCODERS: dict[str, VideoEncoderSpec] = {
    spec.name: spec
    for spec in (
        VideoEncoderSpec(
            name="libx264", codec="h264", hardware=None, rate_controls=_SOFTWARE_RC,
            quality_range=(0, 51), default_quality=23,
            named_presets=X26X_PRESETS, default_preset="medium",
            tunes=("film", "animation", "grain", "stillimage", "fastdecode", "zerolatency"),
            bit_depths=frozenset({8, 10}), two_pass=True,
        ),
        VideoEncoderSpec(
            name="libx265", codec="hevc", hardware=None, rate_controls=_SOFTWARE_RC,
            quality_range=(0, 51), default_quality=28,
            named_presets=X26X_PRESETS, default_preset="medium",
            tunes=("grain", "animation", "fastdecode", "zerolatency", "psnr", "ssim"),
            bit_depths=frozenset({8, 10}), two_pass=True,
        ),
        VideoEncoderSpec(
            name="libsvtav1", codec="av1", hardware=None,
            rate_controls=frozenset({"crf", "vbr", "target_size"}),
            quality_range=(1, 63), default_quality=35,
            numeric_presets=(0, 13), default_preset=8,
            bit_depths=frozenset({8, 10}),
        ),
        VideoEncoderSpec(
            name="libaom-av1", codec="av1", hardware=None,
            rate_controls=frozenset({"crf", "vbr", "target_size"}),
            quality_range=(0, 63), default_quality=32,
            numeric_presets=(0, 8), default_preset=4,
            bit_depths=frozenset({8, 10}), two_pass=True,
        ),
        VideoEncoderSpec(
            name="libvpx-vp9", codec="vp9", hardware=None, rate_controls=_SOFTWARE_RC,
            quality_range=(0, 63), default_quality=32,
            numeric_presets=(0, 8), default_preset=4,
            bit_depths=frozenset({8, 10}), two_pass=True,
        ),
        VideoEncoderSpec(
            name="h264_vaapi", codec="h264", hardware="vaapi", rate_controls=_VAAPI_RC,
            quality_range=(0, 51), default_quality=24,
            bit_depths=frozenset({8}),
        ),
        VideoEncoderSpec(
            name="hevc_vaapi", codec="hevc", hardware="vaapi", rate_controls=_VAAPI_RC,
            quality_range=(0, 51), default_quality=25,
            bit_depths=frozenset({8, 10}),
        ),
        VideoEncoderSpec(
            name="av1_vaapi", codec="av1", hardware="vaapi", rate_controls=_VAAPI_RC,
            quality_range=(0, 255), default_quality=120,
            bit_depths=frozenset({8, 10}),
        ),
    )
}

# Preference order when a request names a codec but no encoder: hardware
# first (when usable on this host), then the best software encoder.
ENCODER_PREFERENCE: dict[str, tuple[str, ...]] = {
    "h264": ("h264_vaapi", "libx264"),
    "hevc": ("hevc_vaapi", "libx265"),
    "av1": ("av1_vaapi", "libsvtav1", "libaom-av1"),
    "vp9": ("libvpx-vp9",),
}

# Software encoder to fall back to when a hardware encode fails.
SOFTWARE_FALLBACK: dict[str, str] = {
    "h264_vaapi": "libx264",
    "hevc_vaapi": "libx265",
    "av1_vaapi": "libsvtav1",
}


@dataclass(frozen=True)
class AudioEncoderSpec:
    name: str
    codec: str
    lossless: bool = False
    default_bitrate_kbps: Optional[int] = None
    sample_rates: frozenset[int] = field(default_factory=frozenset)  # empty = any


AUDIO_ENCODERS: dict[str, AudioEncoderSpec] = {
    "aac": AudioEncoderSpec("aac", "aac", default_bitrate_kbps=160),
    "opus": AudioEncoderSpec("libopus", "opus", default_bitrate_kbps=128,
                             sample_rates=frozenset({8000, 16000, 24000, 48000})),
    "mp3": AudioEncoderSpec("libmp3lame", "mp3", default_bitrate_kbps=192,
                            sample_rates=frozenset({8000, 16000, 22050, 24000, 32000, 44100, 48000})),
    "ac3": AudioEncoderSpec("ac3", "ac3", default_bitrate_kbps=384,
                            sample_rates=frozenset({32000, 44100, 48000})),
    "vorbis": AudioEncoderSpec("libvorbis", "vorbis", default_bitrate_kbps=160),
    "flac": AudioEncoderSpec("flac", "flac", lossless=True),
    "pcm": AudioEncoderSpec("pcm_s16le", "pcm", lossless=True),
}
