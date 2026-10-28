# Advanced encoding API

The four create endpoints accept two optional fields on top of their usual body:

| Endpoint | Existing fields | New optional fields |
|---|---|---|
| `POST /api/jobs` (async conversion) | `id`, `output_format`, `quality` | `options`, `preset` |
| `POST /api/conversions` (sync conversion) | `id`, `output_format`, `quality` | `options`, `preset` |
| `POST /api/compression-jobs` (async compression) | `id`, `compression_level` | `options`, `preset` |
| `POST /api/compressions` (sync compression) | `id`, `compression_level` | `options`, `preset` |

Leave both out, or send `"options": {}`, and the request behaves exactly as before. That is enforced by golden tests that pin every legacy FFmpeg command line.

When they're present, settings are resolved in this order (first wins):

1. Fields you set in `options`.
2. The named `preset` (built-in key or the `id` of a saved preset).
3. The legacy `quality` / `compression_level` mapping.
4. Encoder defaults.

So `{"compression_level": "max", "options": {"video": {"max_height": 720}}}` means "max compression, and downscale to 720p".

Every example below needs `Authorization: Bearer <api-key>`.

GPU encoding setup (VAAPI on AMD and Intel) is covered in [vaapi.md](vaapi.md).

## Discover what this server can do

```bash
curl -s -H "Authorization: Bearer $KEY" http://localhost:3313/api/capabilities
```

This returns:

- **Usable video encoders**, each with its ranges, presets, tunes and bit depths. Hardware encoders appear only after a one-frame test encode succeeded on the GPU.
- **The encoder chosen per codec** when you don't name one.
- **Which codecs each output container accepts.**
- **Which image options each image format accepts.**
- **The built-in presets.**

On an AMD Cezanne APU, `hardware.encoders` is `["h264_vaapi", "hevc_vaapi"]`, and AV1 maps to `libsvtav1`.

```bash
curl -s -H "Authorization: Bearer $KEY" http://localhost:3313/api/files/$FILE_ID/probe
```

Probe returns:

- **Audio and video files:** duration, overall bitrate, container, the video stream (codec, size, fps, pixel format, bit depth), audio tracks and subtitle count.
- **Images:** dimensions, mode, frame count, and whether EXIF or an ICC profile is present.

## Examples

HEVC on the GPU (falls back to x265 if the GPU encode fails):

```bash
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  http://localhost:3313/api/compression-jobs \
  -d '{"id": "'$FILE_ID'", "preset": "amd-fast-hevc"}'
```

Full control, MKV to MP4:

```bash
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  http://localhost:3313/api/jobs -d '{
    "id": "'$FILE_ID'",
    "output_format": "mp4",
    "options": {
      "video": {"codec": "hevc", "encoder": "libx265", "crf": 22, "encoder_preset": "slow", "bit_depth": 10, "max_height": 1080},
      "audio": {"codec": "aac", "bitrate_kbps": 160, "channels": 2},
      "trim": {"start_s": 30, "end_s": 90},
      "strip_metadata": true
    }
  }'
```

Fit a size limit (two-pass on CPU encoders):

```bash
-d '{"id": "'$FILE_ID'", "output_format": "mp4", "preset": "discord-10mb"}'
```

Images:

```bash
# PNG → WebP, capped at 2560 px, EXIF stripped (ICC kept)
-d '{"id": "'$FILE_ID'", "output_format": "webp", "options": {"image": {"quality": 80, "effort": 6, "max_dimension": 2560}, "strip_metadata": true}}'

# Shrink a PNG in place by quantizing to 64 colors
# (POST /api/compression-jobs)
-d '{"id": "'$FILE_ID'", "options": {"image": {"palette_colors": 64}}}'
```

## Saved presets

```bash
# Save
curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  http://localhost:3313/api/presets -d '{
    "name": "Plex 1080p", "kind": "video",
    "options": {"video": {"codec": "hevc", "crf": 22, "max_height": 1080}, "audio": {"codec": "aac", "bitrate_kbps": 192}}
  }'
# → {"id": "6f1c…", ...}

# Use
-d '{"id": "'$FILE_ID'", "output_format": "mkv", "preset": "6f1c…"}'
```

`GET /api/presets` lists the built-ins followed by your saved presets. `GET`, `PATCH` and `DELETE /api/presets/{id}` manage one preset. Built-ins are read-only (403).

## Progress and cancellation

Jobs submitted with `options` or `preset` report live progress:

```bash
curl -s -H "Authorization: Bearer $KEY" http://localhost:3313/api/jobs/$JOB_ID
# {"status": "running", "progress": 42, "eta_seconds": 71, "speed": 3.2, "encoder_used": null, "options": {...}, ...}
```

`encoder_used` is filled in once the job completes. It shows `libx265` if a `hevc_vaapi` encode had to fall back to the CPU.

`POST /api/jobs/{id}/cancel` (or `/api/compression-jobs/{id}/cancel`) still cancels queued jobs. It now also stops running jobs that were submitted with `options` or `preset`; they end in `cancelled`. Running legacy jobs still return 409, as before.

## Options reference

| Field | Values |
|---|---|
| `video.codec` | `h264`, `hevc`, `av1`, `vp9`, `copy` |
| `video.encoder` | Any name listed by `/api/capabilities`, e.g. `libx264`, `libx265`, `libsvtav1`, `libaom-av1`, `libvpx-vp9`, `h264_vaapi`, `hevc_vaapi` |
| `video.rate_control` | `crf` (software), `cqp` (hardware), `vbr`, `cbr`, `target_size`. A `crf` on a hardware encoder is used as its QP |
| `video.crf` / `video.qp` | Encoder-specific range, see capabilities |
| `video.bitrate_kbps`, `video.maxrate_kbps` | For `vbr` / `cbr` |
| `video.target_size_mb` | For `target_size`; audio is included in the budget |
| `video.encoder_preset` | x264/x265 `ultrafast`…`veryslow`; SVT-AV1 `0`–`13`; libvpx/libaom cpu-used `0`–`8` |
| `video.tune` | x264/x265 tunes such as `film`, `animation`, `grain` |
| `video.bit_depth` | `8` or `10` |
| `video.max_width`, `video.max_height` | Downscale to fit; never upscales; keeps aspect ratio |
| `video.fps`, `video.keyframe_interval_s` | Frame rate; force a keyframe every N seconds |
| `audio.codec` | `aac`, `opus`, `mp3`, `flac`, `ac3`, `vorbis`, `pcm`, `copy`, `none` |
| `audio.bitrate_kbps`, `audio.channels`, `audio.sample_rate` | Lossy bitrate; downmix; resample |
| `image.quality` | 1–100 (lossy formats) |
| `image.lossless` | WebP, JPEG XL, PNG |
| `image.effort` | 0–10 (0 = fastest, 10 = smallest). Mapped to WebP method, AVIF speed, JPEG XL effort, PNG zlib level |
| `image.chroma_subsampling` | `4:2:0`, `4:2:2`, `4:4:4` (JPEG, AVIF) |
| `image.max_dimension` | Longest side, never upscales |
| `image.palette_colors` | 2–256, PNG only |
| `trim.start_s`, `trim.end_s` | Seconds |
| `subtitles` | `copy` (MKV only) or `drop` (default) |
| `strip_metadata` | `true` drops container/EXIF metadata and keeps the ICC profile; `false` keeps everything |
| `keep_if_larger` | Compression only: keep the re-encode even if it's bigger than the source |
| `hw_fallback` | Default `true`: retry on the CPU if a GPU encode fails |

Unknown fields are rejected. Raw FFmpeg arguments are never accepted.

## Errors

Invalid options fail at submit time with the same 422 shape FastAPI uses for any validation error:

```json
{"detail": [{"loc": ["body", "options"], "msg": "webm can't hold h264 video. Supported codecs for webm: av1, vp9", "type": "value_error"}]}
```

An unknown preset reports `"loc": ["body", "preset"]`.
