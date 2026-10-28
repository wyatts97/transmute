# GPU encoding with VAAPI (AMD and Intel)

Transmute encodes H.264, HEVC and (on newer GPUs) AV1 on the GPU through VAAPI. It only uses a GPU encoder after a real test encode succeeds at startup. Anything the GPU can't do, or any GPU encode that fails mid-job, falls back to the CPU encoder (`libx264`, `libx265`, `libsvtav1`) automatically.

What to expect on common hardware:

| GPU | Hardware encoders | 10-bit HEVC |
|---|---|---|
| AMD Ryzen 4000/5000 APUs (Renoir/Cezanne, VCN 2.x) | H.264, HEVC | Usually; confirmed by the startup test |
| AMD RDNA2 (RX 6000) | H.264, HEVC | Yes |
| AMD RDNA3+ (RX 7000, Ryzen 7040+) | H.264, HEVC, AV1 | Yes |
| Intel 7th gen+ / Arc | H.264, HEVC (Arc: AV1) | Gen-dependent |

VP9 always encodes on the CPU (libvpx).

## 1. Host checks (Debian)

```bash
ls -l /dev/dri
```

You should see `renderD128` (and `card0` or `card1`). If `/dev/dri` is missing, the GPU driver isn't loaded. On AMD, make sure the `amdgpu` module is loaded and the firmware package is installed.

```bash
lsmod | grep amdgpu
```

```bash
sudo apt install firmware-amd-graphics
```

That firmware package comes from the `non-free-firmware` component. Reboot after installing it.

Optional: see what the GPU advertises from the host itself:

```bash
sudo apt install vainfo mesa-va-drivers
```

```bash
vainfo --display drm --device /dev/dri/renderD128
```

Look for `VAEntrypointEncSlice` lines: `VAProfileH264High`, `VAProfileHEVCMain`, `VAProfileHEVCMain10`.

## 2. Build and start with the GPU

```bash
git clone https://github.com/wyatts97/transmute.git
```

```bash
cd transmute && git checkout feat/encoding-core
```

```bash
docker compose -f docker-compose.yml -f docker-compose.vaapi.yml up -d --build
```

`docker-compose.vaapi.yml` passes `/dev/dri` into the container and sets `HW_ACCEL=vaapi`. The image ships `mesa-va-drivers` (AMD). For Intel, build with the Intel media driver instead:

```bash
docker compose -f docker-compose.yml -f docker-compose.vaapi.yml build --build-arg VAAPI_DRIVERS="intel-media-va-driver"
```

## 3. Check it inside the container

```bash
docker compose exec transmute vaapi-check
```

This prints the VA driver, the profiles it supports, and a pass/fail test encode for every VAAPI encoder, including 10-bit HEVC. The app runs the same tests at startup and logs a summary:

```bash
docker compose logs transmute | grep "Encoder capabilities"
```

On a Cezanne APU, expect a line like this:

```
Encoder capabilities: ffmpeg=7.1.5-0+deb13u1, hw=['h264_vaapi', 'hevc_vaapi'] (10-bit: ['hevc_vaapi'], driver: Mesa Gallium driver 25.0.7 ... (radeonsi, renoir ...)), software=['libaom-av1', 'libsvtav1', 'libvpx-vp9', 'libx264', 'libx265']
```

The same information is available from the API (create a key under My Account → API Keys):

```bash
curl -s -H "Authorization: Bearer $KEY" http://localhost:3313/api/capabilities | jq .hardware
```

## 4. Run a real GPU encode

```bash
FILE_ID=$(curl -s -H "Authorization: Bearer $KEY" -F file=@/path/to/video.mkv \
  http://localhost:3313/api/files | jq -r .metadata.id)
```

```bash
JOB_ID=$(curl -s -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d "{\"id\": \"$FILE_ID\", \"preset\": \"amd-fast-hevc\"}" \
  http://localhost:3313/api/compression-jobs | jq -r .id)
```

```bash
watch -n1 "curl -s -H 'Authorization: Bearer $KEY' http://localhost:3313/api/compression-jobs/$JOB_ID | jq '{status, progress, speed, eta_seconds, encoder_used}'"
```

When the job completes, `encoder_used` should read `hevc_vaapi`. If it says `libx265`, the GPU encode failed and the job fell back to the CPU; the container logs say why:

```bash
docker compose logs transmute | grep -i "hardware encode"
```

To see the GPU's video engine working on AMD, run `amdgpu_top` on the host during the encode. Its VCN/media row should go busy.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `vaapi-check`: render node not found | Start with `-f docker-compose.vaapi.yml`; check `ls -l /dev/dri` on the host |
| `vainfo` fails / `vaInitialize failed` | Driver missing or wrong. AMD needs `mesa-va-drivers` (default). Intel needs `--build-arg VAAPI_DRIVERS="intel-media-va-driver"`. You can force one with `LIBVA_DRIVER_NAME=radeonsi` or `iHD` |
| `Permission denied` on `/dev/dri/renderD128` | Only when running as non-root or under rootless Docker: add the host render group with `group_add` (see `docker-compose.vaapi.yml`) |
| 10-bit HEVC goes to the CPU | The GPU failed the Main10 test encode; check `vaapi-check`. 8-bit HEVC still uses the GPU |
| Multiple GPUs | Set `VAAPI_DEVICE=/dev/dri/renderD129` (see `ls /dev/dri/by-path`) |
| You never want the GPU | Set `HW_ACCEL=off` |
