#!/bin/sh
# Diagnose VAAPI hardware encoding inside the Transmute container.
#
#   docker compose exec transmute vaapi-check
#
# Checks the render node, prints what the VA driver advertises, and runs a
# short test encode with every VAAPI encoder FFmpeg was built with.

DEVICE="${VAAPI_DEVICE:-/dev/dri/renderD128}"
SAMPLE="testsrc2=size=1280x720:rate=30:duration=2"
status=0

echo "== Render node: $DEVICE"
if [ ! -e "$DEVICE" ]; then
    echo "Not found. Pass the GPU into the container (devices: /dev/dri:/dev/dri)."
    echo "On the host, check: ls -l /dev/dri"
    exit 1
fi
ls -l "$DEVICE"

echo
echo "== VA driver (vainfo)"
if command -v vainfo >/dev/null 2>&1; then
    vainfo --display drm --device "$DEVICE" 2>&1 | grep -E "Driver version|VAProfile(H264|HEVC|AV1|VP9)" || {
        echo "vainfo failed. Is a VA driver installed (mesa-va-drivers for AMD, intel-media-va-driver for Intel)?"
        status=1
    }
else
    echo "vainfo is not installed in this image."
fi

echo
echo "== Test encodes"
try_encode() {
    label="$1"; shift
    if out=$(ffmpeg -hide_banner -v error -vaapi_device "$DEVICE" -f lavfi -i "$SAMPLE" "$@" -f null - 2>&1); then
        echo "ok      $label"
    else
        echo "FAILED  $label: $(echo "$out" | tail -n 1)"
    fi
}

for encoder in h264_vaapi hevc_vaapi av1_vaapi; do
    if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q " $encoder "; then
        try_encode "$encoder 8-bit" -vf format=nv12,hwupload -c:v "$encoder"
    fi
done
try_encode "hevc_vaapi 10-bit (Main10)" -vf format=p010,hwupload -c:v hevc_vaapi -profile:v main10
if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q " av1_vaapi "; then
    try_encode "av1_vaapi 10-bit" -vf format=p010,hwupload -c:v av1_vaapi
fi

echo
echo "Encoders that fail here are hidden from GET /api/capabilities and"
echo "requests fall back to the CPU encoder (libx264 / libx265 / libsvtav1)."
exit $status
