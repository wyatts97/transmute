"""Runtime detection of the encoders this host can actually use.

``ffmpeg -encoders`` tells us what the FFmpeg build was compiled with; for
hardware encoders that is not enough (the GPU, driver, or device node may be
missing), so each hardware encoder is also verified with a one-frame test
encode. Results are cached for the life of the process.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess  # nosec B404
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core import get_settings

from .encoders import AUDIO_ENCODERS, ENCODER_PREFERENCE, VIDEO_ENCODERS


logger = logging.getLogger(__name__)

_FFMPEG_PATHS = {
    "darwin": "/opt/homebrew/bin/ffmpeg",
    "linux": "/usr/bin/ffmpeg",
    "win32": "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
}
_FFPROBE_PATHS = {
    "darwin": "/opt/homebrew/bin/ffprobe",
    "linux": "/usr/bin/ffprobe",
    "win32": "C:\\Program Files\\ffmpeg\\bin\\ffprobe.exe",
}


def _resolve_binary(platform_paths: dict[str, str], name: str) -> str:
    """Prefer the platform's standard install path, else whatever is on PATH."""
    preferred = platform_paths.get(sys.platform)
    if preferred and Path(preferred).exists():
        return preferred
    return shutil.which(name) or preferred or name


FFMPEG_PATH = _resolve_binary(_FFMPEG_PATHS, "ffmpeg")
FFPROBE_PATH = _resolve_binary(_FFPROBE_PATHS, "ffprobe")

_ENCODER_LINE = re.compile(r"^\s*([VAS])[A-Z.]{5}\s+(\S+)")


@dataclass(frozen=True)
class Capabilities:
    ffmpeg_version: str | None
    compiled_encoders: frozenset[str]
    vaapi_device: str | None
    usable_hw_encoders: frozenset[str]
    # Hardware encoders that also passed a 10-bit (P010) test encode. GPUs
    # often encode 8-bit HEVC but not Main10, so this is checked separately.
    usable_hw_10bit_encoders: frozenset[str] = frozenset()
    vaapi_driver: str | None = None

    def is_usable(self, encoder: str, bit_depth: int = 8) -> bool:
        spec = VIDEO_ENCODERS.get(encoder)
        if spec is not None and spec.hardware:
            if bit_depth == 10:
                return encoder in self.usable_hw_10bit_encoders
            return encoder in self.usable_hw_encoders
        return encoder in self.compiled_encoders

    def default_encoder_for(self, codec: str, bit_depth: int = 8) -> str | None:
        """Best usable encoder for ``codec``; hardware first when it can do ``bit_depth``."""
        for name in ENCODER_PREFERENCE.get(codec, ()):
            spec = VIDEO_ENCODERS[name]
            if bit_depth in spec.bit_depths and self.is_usable(name, bit_depth):
                return name
        return None

    def describe(self) -> dict:
        video = [spec.describe() for name, spec in VIDEO_ENCODERS.items() if self.is_usable(name)]
        audio = sorted(codec for codec, spec in AUDIO_ENCODERS.items() if spec.name in self.compiled_encoders)
        return {
            "ffmpeg_version": self.ffmpeg_version,
            "hardware": {
                "vaapi_device": self.vaapi_device,
                "driver": self.vaapi_driver,
                "encoders": sorted(self.usable_hw_encoders),
                "ten_bit_encoders": sorted(self.usable_hw_10bit_encoders),
            },
            "video_encoders": video,
            "default_video_encoders": {
                codec: self.default_encoder_for(codec) for codec in ENCODER_PREFERENCE
            },
            "audio_codecs": audio,
        }


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess | None:
    try:
        # Subprocess is safe here: the command is built from constants and
        # the configured device path, never from request data.
        return subprocess.run(  # nosec B603
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def parse_encoder_list(output: str) -> frozenset[str]:
    """Parse ``ffmpeg -encoders`` output into a set of encoder names."""
    names = set()
    for line in output.splitlines():
        match = _ENCODER_LINE.match(line)
        if match and match.group(2) != "=":
            names.add(match.group(2))
    return frozenset(names)


def _ffmpeg_version() -> str | None:
    result = _run([FFMPEG_PATH, "-hide_banner", "-version"], timeout=10)
    if result is None or result.returncode != 0:
        return None
    first_line = (result.stdout.splitlines() or [""])[0]
    match = re.search(r"ffmpeg version (\S+)", first_line)
    return match.group(1) if match else None


def _vaapi_test_encode(device: str, encoder: str, bit_depth: int = 8) -> bool:
    upload = "format=p010,hwupload" if bit_depth == 10 else "format=nv12,hwupload"
    profile = ["-profile:v", "main10"] if bit_depth == 10 and encoder == "hevc_vaapi" else []
    result = _run(
        [
            FFMPEG_PATH, "-hide_banner", "-v", "error",
            "-vaapi_device", device,
            "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
            "-vf", upload, "-frames:v", "1", "-c:v", encoder, *profile,
            "-f", "null", "-",
        ],
        timeout=20,
    )
    ok = result is not None and result.returncode == 0
    if not ok and result is not None:
        logger.info(
            "VAAPI encoder %s (%d-bit) unusable on %s: %s",
            encoder, bit_depth, device, result.stderr.strip()[:300],
        )
    return ok


def parse_vainfo_driver(output: str) -> str | None:
    """Pull the driver description out of ``vainfo`` output."""
    for line in output.splitlines():
        if "Driver version:" in line:
            return line.split("Driver version:", 1)[1].strip() or None
    return None


def _vaapi_driver(device: str) -> str | None:
    result = _run(["vainfo", "--display", "drm", "--device", device], timeout=10)
    if result is None:
        return None
    return parse_vainfo_driver(result.stdout + result.stderr)


def detect_capabilities() -> Capabilities:
    settings = get_settings()
    listing = _run([FFMPEG_PATH, "-hide_banner", "-encoders"], timeout=15)
    compiled = parse_encoder_list(listing.stdout) if listing is not None and listing.returncode == 0 else frozenset()

    vaapi_device = None
    vaapi_driver = None
    usable_hw: set[str] = set()
    usable_hw_10bit: set[str] = set()
    hw_mode = (settings.hw_accel or "auto").lower()
    device = settings.vaapi_device
    if hw_mode in ("auto", "vaapi") and Path(device).exists():
        candidates = [
            name for name, spec in VIDEO_ENCODERS.items()
            if spec.hardware == "vaapi" and name in compiled
        ]
        for encoder in candidates:
            if not _vaapi_test_encode(device, encoder):
                continue
            usable_hw.add(encoder)
            if 10 in VIDEO_ENCODERS[encoder].bit_depths and _vaapi_test_encode(device, encoder, bit_depth=10):
                usable_hw_10bit.add(encoder)
        if usable_hw:
            vaapi_device = device
            vaapi_driver = _vaapi_driver(device)
    if hw_mode == "vaapi" and not usable_hw:
        logger.warning(
            "HW_ACCEL=vaapi but no VAAPI encoder works on %s. Is /dev/dri passed into "
            "the container and is a VA driver (e.g. mesa-va-drivers) installed?",
            device,
        )

    caps = Capabilities(
        ffmpeg_version=_ffmpeg_version(),
        compiled_encoders=compiled,
        vaapi_device=vaapi_device,
        usable_hw_encoders=frozenset(usable_hw),
        usable_hw_10bit_encoders=frozenset(usable_hw_10bit),
        vaapi_driver=vaapi_driver,
    )
    logger.info(
        "Encoder capabilities: ffmpeg=%s, hw=%s (10-bit: %s, driver: %s), software=%s",
        caps.ffmpeg_version,
        sorted(caps.usable_hw_encoders) or "none",
        sorted(caps.usable_hw_10bit_encoders) or "none",
        caps.vaapi_driver or "n/a",
        sorted(n for n, s in VIDEO_ENCODERS.items() if not s.hardware and n in compiled),
    )
    return caps


@lru_cache
def get_capabilities() -> Capabilities:
    return detect_capabilities()
