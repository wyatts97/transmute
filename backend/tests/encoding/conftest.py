import pytest

from encoding.capabilities import Capabilities


_SOFTWARE = {
    "libx264", "libx265", "libsvtav1", "libaom-av1", "libvpx-vp9",
    "aac", "libopus", "libmp3lame", "ac3", "libvorbis", "flac", "pcm_s16le",
}


@pytest.fixture
def cezanne_caps() -> Capabilities:
    """AMD Cezanne APU: VAAPI encodes H.264 and HEVC only."""
    return Capabilities(
        ffmpeg_version="7.1.1",
        compiled_encoders=frozenset(_SOFTWARE | {"h264_vaapi", "hevc_vaapi", "av1_vaapi"}),
        vaapi_device="/dev/dri/renderD128",
        usable_hw_encoders=frozenset({"h264_vaapi", "hevc_vaapi"}),
        usable_hw_10bit_encoders=frozenset({"hevc_vaapi"}),
        vaapi_driver="Mesa Gallium driver 25.0.7 for AMD Radeon Graphics (radeonsi, renoir)",
    )


@pytest.fixture
def gpu_8bit_only_caps() -> Capabilities:
    """A VAAPI GPU that encodes 8-bit HEVC but fails the Main10 test encode."""
    return Capabilities(
        ffmpeg_version="7.1.1",
        compiled_encoders=frozenset(_SOFTWARE | {"h264_vaapi", "hevc_vaapi"}),
        vaapi_device="/dev/dri/renderD128",
        usable_hw_encoders=frozenset({"h264_vaapi", "hevc_vaapi"}),
    )


@pytest.fixture
def cpu_caps() -> Capabilities:
    return Capabilities(
        ffmpeg_version="7.1.1",
        compiled_encoders=frozenset(_SOFTWARE),
        vaapi_device=None,
        usable_hw_encoders=frozenset(),
    )
