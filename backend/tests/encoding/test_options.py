import pytest
from pydantic import ValidationError

from encoding import EncodeOptions, merge_options
from encoding.legacy import (
    legacy_compression_base,
    legacy_conversion_base,
    legacy_image_compression_base,
    legacy_image_conversion_base,
)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        EncodeOptions.model_validate({"video": {"codec": "hevc", "crff": 20}})


def test_raw_ffmpeg_args_are_not_accepted():
    with pytest.raises(ValidationError):
        EncodeOptions.model_validate({"extra_args": ["-i", "/etc/passwd"]})


def test_encoder_name_is_pattern_checked():
    with pytest.raises(ValidationError):
        EncodeOptions.model_validate({"video": {"encoder": "libx264 -f"}})


def test_trim_end_must_follow_start():
    with pytest.raises(ValidationError):
        EncodeOptions.model_validate({"trim": {"start_s": 10, "end_s": 5}})


def test_override_wins_field_by_field():
    base = EncodeOptions.model_validate({"video": {"codec": "h264", "crf": 30, "max_height": 1080}, "audio": {"codec": "aac", "bitrate_kbps": 112}})
    merged = merge_options(base, EncodeOptions.model_validate({"video": {"crf": 22}}))
    assert merged.video.codec == "h264"
    assert merged.video.crf == 22
    assert merged.video.max_height == 1080
    assert merged.audio.bitrate_kbps == 112


def test_switching_codec_drops_codec_specific_settings():
    base = legacy_compression_base("mp4", "max")
    merged = merge_options(base, EncodeOptions.model_validate({"video": {"codec": "av1"}}))
    assert merged.video.codec == "av1"
    assert merged.video.encoder is None
    assert merged.video.crf is None
    assert merged.video.encoder_preset is None
    # Geometry and bit depth carry over.
    assert merged.video.bit_depth == 8


def test_explicit_encoder_replaces_base_codec():
    base = legacy_compression_base("mp4", "balanced")
    merged = merge_options(base, EncodeOptions.model_validate({"video": {"encoder": "libx265"}}))
    assert merged.video.codec is None
    assert merged.video.encoder == "libx265"
    assert merged.video.crf is None


def test_switching_audio_to_lossless_drops_bitrate():
    base = legacy_compression_base("mkv", "balanced")
    merged = merge_options(base, EncodeOptions.model_validate({"audio": {"codec": "flac"}}))
    assert merged.audio.codec == "flac"
    assert merged.audio.bitrate_kbps is None


def test_merge_with_no_override_copies_base():
    base = legacy_compression_base("mp4", "light")
    merged = merge_options(base, None)
    assert merged == base
    assert merged is not base


def test_legacy_compression_base_matches_preset_tables():
    base = legacy_compression_base("mp4", "balanced")
    assert base.video.encoder == "libx264"
    assert base.video.crf == 30
    assert base.video.encoder_preset == "medium"
    assert base.audio.bitrate_kbps == 112

    webm = legacy_compression_base("webm", "max")
    assert (webm.video.encoder, webm.video.crf, webm.audio.codec) == ("libvpx-vp9", 41, "opus")

    assert legacy_compression_base("ac3", "light").audio.bitrate_kbps == 256
    assert legacy_compression_base("flac", "max").audio.codec == "flac"
    # Unknown levels fall back to balanced, like the legacy encoder does.
    assert legacy_compression_base("mp4", "bogus").video.crf == 30


def test_legacy_compression_base_is_none_for_unsupported_formats():
    for fmt in ("wmv", "flv", "gif", "wma"):
        assert legacy_compression_base(fmt, "balanced") is None


def test_legacy_conversion_base():
    high = legacy_conversion_base("mp4", "high")
    assert (high.video.codec, high.video.crf, high.video.encoder_preset) == ("h264", 18, "slow")
    assert high.audio.bitrate_kbps == 320

    webm = legacy_conversion_base("webm", "high")
    assert webm.video.encoder == "libvpx-vp9"
    assert webm.video.crf == 27

    no_quality = legacy_conversion_base("mkv", None)
    assert no_quality.video.codec == "h264"
    assert no_quality.video.crf is None

    assert legacy_conversion_base("mp3", "low").audio.bitrate_kbps == 96
    assert legacy_conversion_base("gif", "high") is None


def test_legacy_image_bases():
    assert legacy_image_compression_base("jpeg", "max").image.quality == 50
    assert legacy_image_compression_base("png", "max").image is None
    assert legacy_image_conversion_base("webp", "high").image.quality == 95
    assert legacy_image_conversion_base("avif", None).image.quality == 85
