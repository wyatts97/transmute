"""Built-in, read-only encode presets.

A request can name one with ``"preset": "<key>"``. Its options sit between
the caller's explicit ``options`` (which win) and the legacy
``quality``/``compression_level`` mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .options import AudioOptions, EncodeOptions, ImageOptions, VideoOptions


@dataclass(frozen=True)
class BuiltinPreset:
    key: str
    name: str
    description: str
    kind: Literal["video", "image"]
    options: EncodeOptions

    def describe(self) -> dict:
        """API shape (``PresetResponse``); built-ins use their key as ``id``."""
        return {
            "id": self.key,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "builtin": True,
            "options": self.options.model_dump(mode="json", exclude_none=True, exclude_defaults=True),
        }


BUILTIN_PRESETS: dict[str, BuiltinPreset] = {
    preset.key: preset
    for preset in (
        BuiltinPreset(
            key="amd-fast-hevc",
            name="Fast HEVC (GPU)",
            description="HEVC at QP 24 on the VAAPI GPU encoder when available, x265 CRF 24 otherwise.",
            kind="video",
            options=EncodeOptions(
                video=VideoOptions(codec="hevc", rate_control="crf", crf=24, bit_depth=8),
                audio=AudioOptions(bitrate_kbps=160),
            ),
        ),
        BuiltinPreset(
            key="web-1080p-h264",
            name="Web 1080p H.264",
            description="Broadly compatible H.264 capped at 1080p, CRF 23, AAC 160k.",
            kind="video",
            options=EncodeOptions(
                video=VideoOptions(codec="h264", encoder="libx264", rate_control="crf", crf=23,
                                   encoder_preset="medium", max_height=1080, bit_depth=8),
                audio=AudioOptions(codec="aac", bitrate_kbps=160),
            ),
        ),
        BuiltinPreset(
            key="archive-hevc-10bit",
            name="Archive HEVC 10-bit",
            description="High-quality 10-bit x265 at CRF 20 (slow), audio copied untouched.",
            kind="video",
            options=EncodeOptions(
                video=VideoOptions(codec="hevc", encoder="libx265", rate_control="crf", crf=20,
                                   encoder_preset="slow", bit_depth=10),
                audio=AudioOptions(codec="copy"),
            ),
        ),
        BuiltinPreset(
            key="av1-small",
            name="AV1 small",
            description="10-bit AV1 at CRF 36 capped at 1080p with Opus 96k. Small files, slow encode.",
            kind="video",
            options=EncodeOptions(
                video=VideoOptions(codec="av1", rate_control="crf", crf=36, max_height=1080, bit_depth=10),
                audio=AudioOptions(codec="opus", bitrate_kbps=96),
            ),
        ),
        BuiltinPreset(
            key="discord-10mb",
            name="Discord 10 MB",
            description="Two-pass H.264 sized to fit a 10 MB upload, 720p 30 fps.",
            kind="video",
            options=EncodeOptions(
                video=VideoOptions(codec="h264", encoder="libx264", rate_control="target_size",
                                   target_size_mb=9.5, encoder_preset="medium", max_height=720,
                                   fps=30, bit_depth=8),
                audio=AudioOptions(codec="aac", bitrate_kbps=96),
            ),
        ),
        BuiltinPreset(
            key="web-image-webp",
            name="Web image (WebP)",
            description="WebP quality 80, longest side capped at 2560 px, EXIF stripped.",
            kind="image",
            options=EncodeOptions(image=ImageOptions(quality=80, effort=6, max_dimension=2560), strip_metadata=True),
        ),
        BuiltinPreset(
            key="avif-photo",
            name="AVIF photo",
            description="AVIF quality 60 with 4:2:0 chroma, EXIF stripped, ICC kept.",
            kind="image",
            options=EncodeOptions(image=ImageOptions(quality=60, effort=6, chroma_subsampling="4:2:0"), strip_metadata=True),
        ),
    )
}


def get_builtin_preset(key: str) -> BuiltinPreset | None:
    return BUILTIN_PRESETS.get(key)
