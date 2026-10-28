# Encoding

This package powers the advanced `options` path for conversions and compressions: codec, CRF/QP/bitrate/target-size rate control, encoder presets, resizing, 10-bit, VAAPI hardware encoding, and image quality controls.

## Purpose

- Define the typed, whitelisted `EncodeOptions` models the API accepts.
- Validate options against the output container and the encoders this host can actually run.
- Build FFmpeg commands from a validated plan and run them with live progress, timeouts, cancellation, and hardware-to-software fallback.
- Apply image options (quality, lossless, effort, chroma, resize, metadata) to Pillow encodes.
- Hold the legacy `quality` / `compression_level` preset tables, so requests without `options` keep producing upstream's exact commands.

## Contents

- `options.py`: `EncodeOptions` and its sub-models, plus `merge_options()` (explicit options over a preset or legacy base).
- `legacy.py`: the legacy preset tables and their translation into a base `EncodeOptions`.
- `encoders.py`: static specs for each supported video and audio encoder (ranges, presets, tunes, bit depths).
- `codec_matrix.py`: which codecs each output container accepts on the options path.
- `capabilities.py`: runtime detection (`ffmpeg -encoders`, plus a one-frame VAAPI test encode), cached per process.
- `resolve.py`: `plan_av_encode()` validates merged options into an `EncodePlan`; raises `EncodeOptionsError` with a user-facing message.
- `ffmpeg_args.py`: turns an `EncodePlan` into one FFmpeg command, or two for two-pass.
- `ffmpeg_runner.py`: runs commands with `-progress`, a watchdog timeout, cancel events, and HW fallback.
- `probe.py`: ffprobe wrapper returning `MediaInfo`.
- `image.py`: Pillow option validation and save-kwarg construction.
- `presets.py`: built-in named presets (`amd-fast-hevc`, `discord-10mb`, ...).

## API Surface

- `options` and `preset` fields on `POST /api/jobs`, `/api/conversions`, `/api/compression-jobs` and `/api/compressions`. They are resolved by `services/encode_options.py` and stored on the job as `options_json`.
- `GET /api/capabilities`, `GET|POST|PATCH|DELETE /api/presets`, and `GET /api/files/{id}/probe`.
- Running option jobs report `progress`, `eta_seconds` and `speed`, record `encoder_used`, and can be cancelled (`background/encode_tracking.py`).
- User-facing reference with examples: `docs/advanced-encoding.md`.
- `tests/api/test_openapi_compat.py` fails on any breaking change against `tests/fixtures/openapi_upstream.json`.

## How To Work In This Folder

- Never accept raw FFmpeg arguments. New knobs are new typed fields, range-checked in `options.py` and validated per encoder in `resolve.py`.
- Keep `plan_av_encode()` pure (no file access) so routes can call it at submit time and return a 422 before a job is queued.
- When adding an encoder, add its spec to `encoders.py`, its preference order to `ENCODER_PREFERENCE`, and its argument mapping to `ffmpeg_args.py`.
- Hardware encoders must be verified by `capabilities.py` before they are offered; `ffmpeg -encoders` alone only proves they were compiled in.

## Practical Guidelines

- The legacy path is frozen: `tests/encoding/test_legacy_golden.py` pins every legacy argv and Pillow kwarg set. If a change makes it fail, the change is wrong unless it is intentional and the snapshot is regenerated on purpose.
- Prefer clear `EncodeOptionsError` messages that say what to do instead ("Use one of: ...").
- `tests/encoding/test_ffmpeg_e2e.py` runs real encodes when FFmpeg is installed; keep its clips tiny.

## Typical Workflow

1. Add or extend a field in `options.py`.
2. Validate it in `resolve.py` (or `image.py` for images).
3. Map it to arguments in `ffmpeg_args.py` (or save kwargs in `image.py`).
4. Add planning tests in `tests/encoding/test_planning.py` and, when it changes real output, an end-to-end test.
