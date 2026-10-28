"""Legacy preset tables and their translation into ``EncodeOptions``.

The tables below are the exact values upstream Transmute uses for the
``compression_level`` (light / balanced / max) and ``quality``
(low / medium / high) presets. The legacy code paths in the compressors and
converters read them from here, so requests without ``options`` keep
producing byte-identical commands (pinned by ``tests/encoding``).

When a request does send ``options``, ``legacy_*_base`` turns the preset into
a starting ``EncodeOptions`` that the caller's options are merged onto, so
``{"compression_level": "max", "options": {"video": {"max_height": 720}}}``
means "max compression, and also downscale".
"""
from __future__ import annotations

from typing import Optional

from .codec_matrix import AUDIO_CONTAINERS, VIDEO_CONTAINERS
from .encoders import VIDEO_ENCODERS
from .options import AudioOptions, EncodeOptions, ImageOptions, VideoOptions


# --- Compression-level → encoder setting maps (FFmpegCompressor) -----------
#
# Compression keeps the source format but re-encodes the media at lower
# quality so the output is smaller. ``light`` favors fidelity over size
# reduction, ``max`` favors maximum size reduction, ``balanced`` sits between.

# H.264 CRF (Constant Rate Factor, 0-51, higher = smaller / lower quality).
H264_CRF_BY_LEVEL: dict[str, int] = {
    'light': 26,
    'balanced': 30,
    'max': 33,
}
DEFAULT_H264_CRF = H264_CRF_BY_LEVEL['balanced']

# libx264 encoding preset. Slower presets compress better at the cost of time.
H264_PRESET_BY_LEVEL: dict[str, str] = {
    'light': 'fast',
    'balanced': 'medium',
    'max': 'slow',
}
DEFAULT_H264_PRESET = H264_PRESET_BY_LEVEL['balanced']

# VP9 CRF (0-63, higher = smaller / lower quality). Paired with ``-b:v 0`` for
# constant-quality mode.
VP9_CRF_BY_LEVEL: dict[str, int] = {
    'light': 31,
    'balanced': 36,
    'max': 41,
}
DEFAULT_VP9_CRF = VP9_CRF_BY_LEVEL['balanced']

# MPEG-family qscale (``-q:v``, ~1-31, higher = smaller / lower quality). Used
# by the default codecs of flv/mpeg/wmv/asf containers.
QSCALE_BY_LEVEL: dict[str, int] = {
    'light': 5,
    'balanced': 9,
    'max': 15,
}
DEFAULT_QSCALE = QSCALE_BY_LEVEL['balanced']

# Audio bitrate per level for lossy audio codecs (and the audio track of
# re-encoded video). Lower bitrate = smaller / lower quality.
AUDIO_BITRATE_BY_LEVEL: dict[str, str] = {
    'light': '160k',
    'balanced': '112k',
    'max': '80k',
}
DEFAULT_AUDIO_BITRATE = AUDIO_BITRATE_BY_LEVEL['balanced']

# AC-3 has a higher practical minimum bitrate than other codecs.
AC3_BITRATE_BY_LEVEL: dict[str, str] = {
    'light': '256k',
    'balanced': '192k',
    'max': '128k',
}
DEFAULT_AC3_BITRATE = AC3_BITRATE_BY_LEVEL['balanced']

# FLAC is lossless: a higher compression level (0-12) produces a smaller file
# with no quality loss, at the cost of more encoding time.
FLAC_COMPRESSION_BY_LEVEL: dict[str, int] = {
    'light': 8,
    'balanced': 10,
    'max': 12,
}
DEFAULT_FLAC_COMPRESSION = FLAC_COMPRESSION_BY_LEVEL['balanced']

# Animated GIF is re-encoded with a freshly generated palette so the animation
# (all frames + timing) is preserved. Size is controlled by the palette color
# count and the dithering method. Fewer colors and ordered (Bayer) dithering
# yield smaller files; error-diffusion (sierra2_4a) preserves the most detail.
GIF_MAX_COLORS_BY_LEVEL: dict[str, int] = {
    'light': 256,
    'balanced': 128,
    'max': 64,
}
DEFAULT_GIF_MAX_COLORS = GIF_MAX_COLORS_BY_LEVEL['balanced']

# Bayer dither scale (1-5, higher = smaller / more banding). ``None`` selects
# error-diffusion (sierra2_4a) for the best quality at the ``light`` preset.
GIF_BAYER_SCALE_BY_LEVEL: dict[str, Optional[int]] = {
    'light': None,
    'balanced': 3,
    'max': 5,
}
DEFAULT_GIF_BAYER_SCALE = GIF_BAYER_SCALE_BY_LEVEL['balanced']


# --- Quality → encoder setting maps (FFmpegConverter) ----------------------

# CRF and libx264-style preset for formats converted with CRF.
CONVERT_CRF_PRESET_BY_QUALITY: dict[str, tuple[str, str]] = {
    'high': ('18', 'slow'),
    'medium': ('23', 'medium'),
    'low': ('28', 'fast'),
}

# qscale for MPEG-family outputs whose default codecs use ``-q:v``.
CONVERT_QSCALE_BY_QUALITY: dict[str, str] = {
    'high': '2',
    'medium': '5',
    'low': '9',
}

CONVERT_AUDIO_BITRATE_BY_QUALITY: dict[str, str] = {'high': '320k', 'medium': '192k', 'low': '96k'}
CONVERT_AC3_BITRATE_BY_QUALITY: dict[str, str] = {'high': '448k', 'medium': '256k', 'low': '128k'}


# --- Image quality maps ----------------------------------------------------

# PillowCompressor encoder quality (0-100, higher = better quality / larger).
IMAGE_QUALITY_BY_LEVEL: dict[str, int] = {
    'light': 90,
    'balanced': 75,
    'max': 50,
}
DEFAULT_IMAGE_QUALITY = IMAGE_QUALITY_BY_LEVEL['balanced']

# PillowConverter quality for lossy outputs; ``medium`` and unset map to 85.
CONVERT_IMAGE_QUALITY_BY_QUALITY: dict[str, int] = {'high': 95, 'low': 60}
DEFAULT_CONVERT_IMAGE_QUALITY = 85

LOSSY_IMAGE_FORMATS = frozenset({'jpeg', 'webp', 'avif', 'jxl', 'heif', 'heic'})


def _kbps(bitrate: str) -> int:
    return int(bitrate.rstrip('k'))


# Encoder quality offset applied for ``quality`` on codecs other than H.264,
# relative to the encoder's default CRF.
_QUALITY_OFFSET = {'high': -5, 'medium': 0, 'low': 5}


def legacy_compression_base(media_type: str, compression_level: str | None) -> EncodeOptions | None:
    """Translate an FFmpegCompressor ``compression_level`` into options.

    Returns ``None`` for formats the advanced options path does not handle
    (e.g. qscale containers, GIF); callers reject ``options`` for those.
    """
    level = compression_level
    if media_type in VIDEO_CONTAINERS and media_type != 'webm':
        return EncodeOptions(
            video=VideoOptions(
                codec='h264', encoder='libx264', rate_control='crf',
                crf=H264_CRF_BY_LEVEL.get(level, DEFAULT_H264_CRF),
                encoder_preset=H264_PRESET_BY_LEVEL.get(level, DEFAULT_H264_PRESET),
                bit_depth=8,
            ),
            audio=AudioOptions(codec='aac', bitrate_kbps=_kbps(AUDIO_BITRATE_BY_LEVEL.get(level, DEFAULT_AUDIO_BITRATE))),
        )
    if media_type == 'webm':
        return EncodeOptions(
            video=VideoOptions(
                codec='vp9', encoder='libvpx-vp9', rate_control='crf',
                crf=VP9_CRF_BY_LEVEL.get(level, DEFAULT_VP9_CRF),
            ),
            audio=AudioOptions(codec='opus', bitrate_kbps=_kbps(AUDIO_BITRATE_BY_LEVEL.get(level, DEFAULT_AUDIO_BITRATE))),
        )
    container = AUDIO_CONTAINERS.get(media_type)
    if container is not None:
        codec = container.default_audio
        if codec in ('flac', 'pcm'):
            return EncodeOptions(audio=AudioOptions(codec=codec))
        table, default = (
            (AC3_BITRATE_BY_LEVEL, DEFAULT_AC3_BITRATE) if codec == 'ac3'
            else (AUDIO_BITRATE_BY_LEVEL, DEFAULT_AUDIO_BITRATE)
        )
        return EncodeOptions(audio=AudioOptions(codec=codec, bitrate_kbps=_kbps(table.get(level, default))))
    return None


def legacy_conversion_base(output_type: str, quality: str | None) -> EncodeOptions | None:
    """Translate an FFmpegConverter ``quality`` into options for ``output_type``."""
    video_container = VIDEO_CONTAINERS.get(output_type)
    audio_container = AUDIO_CONTAINERS.get(output_type)
    container = video_container or audio_container
    if container is None:
        return None

    video = None
    if video_container is not None:
        codec = video_container.default_video
        video = VideoOptions(codec=codec)
        if quality in CONVERT_CRF_PRESET_BY_QUALITY:
            if codec == 'h264':
                crf, preset = CONVERT_CRF_PRESET_BY_QUALITY[quality]
                video = VideoOptions(codec=codec, rate_control='crf', crf=int(crf), encoder_preset=preset)
            else:
                default_encoder = {'vp9': 'libvpx-vp9', 'hevc': 'libx265', 'av1': 'libsvtav1'}.get(codec)
                spec = VIDEO_ENCODERS.get(default_encoder) if default_encoder else None
                if spec is not None:
                    low, high = spec.quality_range
                    crf = min(high, max(low, spec.default_quality + _QUALITY_OFFSET[quality]))
                    video = VideoOptions(codec=codec, encoder=spec.name, rate_control='crf', crf=crf)

    audio_codec = container.default_audio
    audio = AudioOptions(codec=audio_codec)
    if quality in CONVERT_AUDIO_BITRATE_BY_QUALITY and audio_codec not in ('flac', 'pcm'):
        table = CONVERT_AC3_BITRATE_BY_QUALITY if audio_codec == 'ac3' else CONVERT_AUDIO_BITRATE_BY_QUALITY
        audio = AudioOptions(codec=audio_codec, bitrate_kbps=_kbps(table[quality]))
    return EncodeOptions(video=video, audio=audio)


def legacy_image_compression_base(media_type: str, compression_level: str | None) -> EncodeOptions:
    if media_type in LOSSY_IMAGE_FORMATS:
        return EncodeOptions(image=ImageOptions(quality=IMAGE_QUALITY_BY_LEVEL.get(compression_level, DEFAULT_IMAGE_QUALITY)))
    return EncodeOptions()


def legacy_image_conversion_base(output_type: str, quality: str | None) -> EncodeOptions:
    if output_type in LOSSY_IMAGE_FORMATS:
        return EncodeOptions(image=ImageOptions(
            quality=CONVERT_IMAGE_QUALITY_BY_QUALITY.get(quality, DEFAULT_CONVERT_IMAGE_QUALITY)
        ))
    return EncodeOptions()
