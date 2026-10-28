"""Run FFmpeg with live progress, timeouts, cancellation and HW fallback."""
from __future__ import annotations

import logging
import math
import os
import subprocess  # nosec B404
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .capabilities import Capabilities
from .encoders import X26X_PRESETS
from .ffmpeg_args import build_commands, output_duration_s
from .probe import MediaInfo
from .resolve import EncodePlan, software_fallback_plan


logger = logging.getLogger(__name__)

# Seconds of stderr kept for error messages.
_STDERR_TAIL_CHARS = 4000


@dataclass(frozen=True)
class Progress:
    percent: int
    speed: Optional[float]      # encode speed as a multiple of real time
    eta_seconds: Optional[int]


ProgressCallback = Callable[[Progress], None]


class FFmpegCancelled(RuntimeError):
    """Raised when an encode is stopped through its cancel event."""


def parse_progress_block(lines: list[str]) -> dict[str, str]:
    """Parse one ``-progress`` block (``key=value`` lines) into a dict."""
    values: dict[str, str] = {}
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep:
            values[key] = value
    return values


def progress_from_block(values: dict[str, str], duration_s: float | None) -> Progress | None:
    """Turn a parsed progress block into a ``Progress`` (``None`` if unknown)."""
    raw_time = values.get("out_time_us") or values.get("out_time_ms")
    try:
        out_time_s = int(raw_time) / 1_000_000 if raw_time not in (None, "N/A") else None
    except ValueError:
        out_time_s = None
    speed = None
    raw_speed = values.get("speed", "").rstrip("x").strip()
    try:
        speed = float(raw_speed) if raw_speed and raw_speed != "N/A" else None
    except ValueError:
        speed = None
    if values.get("progress") == "end":
        return Progress(percent=100, speed=speed, eta_seconds=0)
    if out_time_s is None or not duration_s:
        return None
    percent = max(0, min(99, int(out_time_s / duration_s * 100)))
    eta = None
    if speed and speed > 0:
        eta = max(0, math.ceil((duration_s - out_time_s) / speed))
    return Progress(percent=percent, speed=speed, eta_seconds=eta)


def run_ffmpeg(
    cmd: list[str],
    *,
    timeout_s: int,
    duration_s: float | None = None,
    progress_cb: ProgressCallback | None = None,
    progress_span: tuple[int, int] = (0, 100),
    cancel_event: threading.Event | None = None,
) -> None:
    """Run one FFmpeg command, reporting progress scaled into ``progress_span``."""
    # ``-progress`` must precede the output; inserting right after the binary
    # makes it a global option.
    full_cmd = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    # Subprocess is safe here: every argument comes from a validated plan.
    process = subprocess.Popen(  # nosec B603
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        for line in process.stderr:
            stderr_chunks.append(line)
            if sum(len(c) for c in stderr_chunks) > _STDERR_TAIL_CHARS * 2:
                del stderr_chunks[: len(stderr_chunks) // 2]

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    # The watchdog enforces the timeout and cancellation even when FFmpeg
    # stops writing progress lines (a hung encode never unblocks readline).
    killed: dict[str, str] = {}
    finished = threading.Event()

    def _watchdog() -> None:
        started = time.monotonic()
        while not finished.wait(0.5):
            if cancel_event is not None and cancel_event.is_set():
                killed["reason"] = "cancelled"
            elif time.monotonic() - started > timeout_s:
                killed["reason"] = "timeout"
            if killed:
                process.kill()
                return

    watchdog = threading.Thread(target=_watchdog, daemon=True)
    watchdog.start()

    low, high = progress_span
    block: list[str] = []
    try:
        for line in process.stdout:
            block.append(line)
            if line.startswith("progress="):
                progress = progress_from_block(parse_progress_block(block), duration_s)
                block = []
                if progress is not None and progress_cb is not None and not killed:
                    scaled = low + (high - low) * progress.percent // 100
                    progress_cb(Progress(scaled, progress.speed, progress.eta_seconds))
        process.wait()
    finally:
        finished.set()
        if process.poll() is None:
            process.kill()
            process.wait()
        watchdog.join(timeout=5)
        stderr_thread.join(timeout=5)

    killed_reason = killed.get("reason")
    if killed_reason == "cancelled":
        raise FFmpegCancelled("Encode cancelled")
    if killed_reason == "timeout":
        raise RuntimeError(f"FFmpeg timed out after {timeout_s} seconds")
    if process.returncode != 0:
        stderr = "".join(stderr_chunks)[-_STDERR_TAIL_CHARS:]
        raise RuntimeError(f"FFmpeg failed: {stderr.strip()}")


def estimate_timeout_s(plan: EncodePlan, info: MediaInfo | None, input_size_bytes: int) -> int:
    """Generous wall-clock limit; slow presets and 2-pass encodes get more time.

    Progress is reported continuously, so a long limit only matters for jobs
    that hang.
    """
    size_mb = max(1, math.ceil(input_size_bytes / (1024 * 1024)))
    duration = output_duration_s(plan, info) or 0
    per_second = 2.0
    video = plan.video
    if video is not None and not video.copy:
        pixels = (info.video.width or 0) * (info.video.height or 0) if info and info.video else 0
        # Unknown resolution: assume roughly 1080p.
        resolution_factor = min(max(1.0, (pixels / (1280 * 720)) ** 0.85), 12.0) if pixels else 2.0
        per_second *= resolution_factor
        preset = video.preset
        if isinstance(preset, str) and preset in X26X_PRESETS:
            per_second *= {"slow": 2, "slower": 4, "veryslow": 8}.get(preset, 1)
        elif video.encoder == "libsvtav1" and isinstance(preset, int):
            per_second *= 1 if preset >= 8 else (3 if preset >= 5 else 8)
        elif video.encoder in ("libaom-av1", "libvpx-vp9") and isinstance(preset, int):
            per_second *= 1 if preset >= 4 else 4
        if video.two_pass:
            per_second *= 2
    timeout = 120 + math.ceil(max(duration * per_second, size_mb * 20))
    return min(timeout, 86400 * 2)


def run_encode_plan(
    plan: EncodePlan,
    *,
    input_file: str,
    output_file: str,
    info: MediaInfo | None,
    caps: Capabilities,
    tmp_dir: str,
    progress_cb: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    """Execute ``plan`` and return the encoder that produced the output.

    Two-pass encodes write their pass logs into a private temp dir that is
    always removed. A failed hardware encode is retried once on the software
    twin when ``plan.hw_fallback`` is set.
    """
    attempts = [plan]
    fallback = software_fallback_plan(plan, caps)
    if fallback is not None:
        attempts.append(fallback)

    last_error: Exception | None = None
    for attempt in attempts:
        try:
            _run_single_plan(
                attempt, input_file=input_file, output_file=output_file, info=info,
                tmp_dir=tmp_dir, progress_cb=progress_cb, cancel_event=cancel_event,
            )
            return attempt.encoder_used or "unknown"
        except FFmpegCancelled:
            raise
        except RuntimeError as exc:
            last_error = exc
            if attempt is not attempts[-1]:
                logger.warning(
                    "Hardware encode with %s failed, retrying with %s: %s",
                    attempt.encoder_used, attempts[-1].encoder_used, str(exc)[:300],
                )
                if os.path.exists(output_file):
                    os.remove(output_file)
    raise last_error  # type: ignore[misc]


def _run_single_plan(
    plan: EncodePlan,
    *,
    input_file: str,
    output_file: str,
    info: MediaInfo | None,
    tmp_dir: str,
    progress_cb: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> None:
    duration = output_duration_s(plan, info)
    timeout_s = estimate_timeout_s(plan, info, os.path.getsize(input_file))
    with tempfile.TemporaryDirectory(prefix="encode-", dir=tmp_dir) as passlog_dir:
        commands = build_commands(
            plan,
            input_file=input_file,
            output_file=output_file,
            info=info,
            passlog_prefix=os.path.join(passlog_dir, "pass"),
        )
        spans = [(0, 100)] if len(commands) == 1 else [(0, 50), (50, 100)]
        for cmd, span in zip(commands, spans):
            run_ffmpeg(
                cmd,
                timeout_s=timeout_s,
                duration_s=duration,
                progress_cb=progress_cb,
                progress_span=span,
                cancel_event=cancel_event,
            )
