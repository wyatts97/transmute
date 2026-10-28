"""Option validation and FFmpeg command construction for the options path."""
import os

import pytest

from encoding import EncodeOptions, EncodeOptionsError, plan_av_encode
from encoding.capabilities import parse_encoder_list, parse_vainfo_driver
from encoding.ffmpeg_args import build_commands
from encoding.probe import AudioStreamInfo, MediaInfo, VideoStreamInfo, parse_probe
from encoding.resolve import software_fallback_plan


def _opts(**data) -> EncodeOptions:
    return EncodeOptions.model_validate(data)


def _cmd(plan, info=None, passlog_prefix=None):
    commands = build_commands(
        plan, input_file="in.mkv", output_file="out.mkv", info=info,
        passlog_prefix=passlog_prefix, ffmpeg_path="ffmpeg",
    )
    return commands


def _after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


SOURCE = MediaInfo(
    duration_s=100.0,
    bitrate_kbps=12400,
    container="matroska,webm",
    video=VideoStreamInfo("hevc", 3840, 2160, 23.976, "yuv420p10le", 10),
    audio=[AudioStreamInfo("aac", 6, 48000, 640)],
)


def test_hevc_prefers_vaapi_on_cezanne(cezanne_caps, cpu_caps):
    assert plan_av_encode("mkv", _opts(video={"codec": "hevc"}), cezanne_caps).video.encoder == "hevc_vaapi"
    assert plan_av_encode("mkv", _opts(video={"codec": "hevc"}), cpu_caps).video.encoder == "libx265"


def test_av1_uses_svt_because_cezanne_has_no_av1_encoder(cezanne_caps):
    plan = plan_av_encode("mkv", _opts(video={"codec": "av1"}), cezanne_caps)
    assert plan.video.encoder == "libsvtav1"
    assert plan.vaapi_device is None


def test_vaapi_hevc_10bit_command(cezanne_caps):
    plan = plan_av_encode("mkv", _opts(video={"codec": "hevc", "qp": 24, "bit_depth": 10, "max_height": 1080}), cezanne_caps)
    (cmd,) = _cmd(plan)
    assert cmd[:6] == ["ffmpeg", "-hide_banner", "-y", "-vaapi_device", "/dev/dri/renderD128", "-i"]
    assert _after(cmd, "-vf") == (
        "scale=w=iw:h='min(ih,1080)':force_original_aspect_ratio=decrease:force_divisible_by=2,format=p010,hwupload"
    )
    assert _after(cmd, "-c:v") == "hevc_vaapi"
    assert _after(cmd, "-rc_mode") == "CQP"
    assert _after(cmd, "-qp") == "24"
    assert _after(cmd, "-profile:v") == "main10"


def test_10bit_request_skips_gpu_without_main10(gpu_8bit_only_caps):
    plan = plan_av_encode("mkv", _opts(video={"codec": "hevc", "bit_depth": 10}), gpu_8bit_only_caps)
    assert plan.video.encoder == "libx265"
    assert plan.vaapi_device is None
    # 8-bit HEVC still goes to the GPU.
    assert plan_av_encode("mkv", _opts(video={"codec": "hevc"}), gpu_8bit_only_caps).video.encoder == "hevc_vaapi"


def test_explicit_gpu_10bit_without_main10_is_rejected(gpu_8bit_only_caps):
    with pytest.raises(EncodeOptionsError, match="hevc_vaapi can't encode 10-bit video on this GPU. Encoders that can: libx265"):
        plan_av_encode("mkv", _opts(video={"encoder": "hevc_vaapi", "bit_depth": 10}), gpu_8bit_only_caps)


def test_capabilities_describe_hardware(cezanne_caps):
    hardware = cezanne_caps.describe()["hardware"]
    assert hardware["ten_bit_encoders"] == ["hevc_vaapi"]
    assert hardware["driver"].startswith("Mesa Gallium driver")


def test_parse_vainfo_driver():
    output = """Trying display: drm
libva info: VA-API version 1.22.0
libva info: Trying to open /usr/lib/x86_64-linux-gnu/dri/radeonsi_drv_video.so
vainfo: VA-API version: 1.22 (libva 2.22.0)
vainfo: Driver version: Mesa Gallium driver 25.0.7-2+deb13u1 for AMD Radeon Graphics (radeonsi, renoir, LLVM 19.1.7, DRM 3.61, 6.12.48-amd64)
vainfo: Supported profile and entrypoints
      VAProfileHEVCMain               : VAEntrypointEncSlice
"""
    assert parse_vainfo_driver(output) == (
        "Mesa Gallium driver 25.0.7-2+deb13u1 for AMD Radeon Graphics (radeonsi, renoir, LLVM 19.1.7, DRM 3.61, 6.12.48-amd64)"
    )
    assert parse_vainfo_driver("vaInitialize failed with error code -1") is None


def test_crf_on_hardware_encoder_becomes_constant_qp(cezanne_caps):
    plan = plan_av_encode("mp4", _opts(video={"codec": "hevc", "rate_control": "crf", "crf": 22}), cezanne_caps)
    assert (plan.video.rate_control, plan.video.quality) == ("cqp", 22)


def test_h264_vaapi_rejects_10bit(cezanne_caps):
    with pytest.raises(EncodeOptionsError, match="can't encode 10-bit"):
        plan_av_encode("mp4", _opts(video={"encoder": "h264_vaapi", "bit_depth": 10}), cezanne_caps)


def test_container_rejects_incompatible_codec(cpu_caps):
    with pytest.raises(EncodeOptionsError, match="webm can't hold h264 video. Supported codecs for webm: av1, vp9"):
        plan_av_encode("webm", _opts(video={"codec": "h264"}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="webm can't hold aac audio"):
        plan_av_encode("webm", _opts(audio={"codec": "aac"}), cpu_caps)


def test_unknown_and_unavailable_encoders(cezanne_caps):
    with pytest.raises(EncodeOptionsError, match="Unknown video encoder"):
        plan_av_encode("mkv", _opts(video={"encoder": "h264_nvenc"}), cezanne_caps)
    with pytest.raises(EncodeOptionsError, match="isn't available on this server. Available av1 encoders: libaom-av1, libsvtav1"):
        plan_av_encode("mkv", _opts(video={"encoder": "av1_vaapi"}), cezanne_caps)


def test_encoder_codec_mismatch(cpu_caps):
    with pytest.raises(EncodeOptionsError, match="produces hevc, not h264"):
        plan_av_encode("mkv", _opts(video={"codec": "h264", "encoder": "libx265"}), cpu_caps)


def test_preset_tune_and_range_validation(cpu_caps):
    with pytest.raises(EncodeOptionsError, match="encoder_preset 'turbo'"):
        plan_av_encode("mkv", _opts(video={"encoder": "libx264", "encoder_preset": "turbo"}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="integer from 0 to 13"):
        plan_av_encode("mkv", _opts(video={"encoder": "libsvtav1", "encoder_preset": 20}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="crf for libx264 must be from 0 to 51"):
        plan_av_encode("mkv", _opts(video={"encoder": "libx264", "crf": 60}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="tune 'film' isn't valid for libsvtav1"):
        plan_av_encode("mkv", _opts(video={"encoder": "libsvtav1", "tune": "film"}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="needs bitrate_kbps"):
        plan_av_encode("mkv", _opts(video={"encoder": "libx264", "rate_control": "vbr"}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="'cqp' needs a hardware encoder"):
        plan_av_encode("mkv", _opts(video={"encoder": "libx264", "rate_control": "cqp"}), cpu_caps)


def test_software_x265_command(cpu_caps):
    plan = plan_av_encode("mkv", _opts(
        video={"codec": "hevc", "crf": 20, "encoder_preset": "slow", "tune": "grain", "max_width": 1920, "max_height": 1080, "fps": 30, "keyframe_interval_s": 2},
        audio={"codec": "opus", "bitrate_kbps": 128, "channels": 2},
        strip_metadata=True,
    ), cpu_caps)
    (cmd,) = _cmd(plan)
    assert _after(cmd, "-vf") == (
        "fps=30,scale=w='min(iw,1920)':h='min(ih,1080)':force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p"
    )
    assert cmd[cmd.index("-c:v"):cmd.index("-c:v") + 8] == ["-c:v", "libx265", "-preset", "slow", "-tune", "grain", "-crf", "20"]
    assert _after(cmd, "-force_key_frames") == "expr:gte(t,n_forced*2)"
    assert cmd[cmd.index("-c:a"):cmd.index("-c:a") + 6] == ["-c:a", "libopus", "-b:a", "128k", "-ac", "2"]
    assert _after(cmd, "-map_metadata") == "-1"
    assert cmd[-1] == "out.mkv"
    assert "-movflags" not in cmd


def test_unscaled_video_is_padded_to_even_dimensions(cpu_caps):
    (cmd,) = _cmd(plan_av_encode("mp4", _opts(video={"codec": "h264"}), cpu_caps))
    assert _after(cmd, "-vf") == "pad=ceil(iw/2)*2:ceil(ih/2)*2,format=yuv420p"
    assert _after(cmd, "-movflags") == "+faststart"


def test_vp9_constant_quality_uses_zero_bitrate(cpu_caps):
    (cmd,) = _cmd(plan_av_encode("webm", _opts(video={"codec": "vp9", "crf": 33, "encoder_preset": 2}), cpu_caps))
    start = cmd.index("-c:v")
    assert cmd[start:start + 12] == [
        "-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "2", "-row-mt", "1", "-crf", "33", "-b:v", "0",
    ]
    assert _after(cmd, "-c:a") == "libopus"


def test_target_size_two_pass_bitrate(cpu_caps):
    plan = plan_av_encode("mp4", _opts(
        video={"encoder": "libx264", "rate_control": "target_size", "target_size_mb": 10},
        audio={"codec": "aac", "bitrate_kbps": 96},
    ), cpu_caps)
    first, second = _cmd(plan, info=SOURCE, passlog_prefix="/tmp/x/pass")
    # 10 MiB * 8192 * 0.98 / 100 s = 802.8 kb/s total, minus 96 kb/s audio.
    assert _after(first, "-b:v") == "706k"
    assert _after(second, "-b:v") == "706k"
    assert first[-4:] == ["-an", "-f", "null", os.devnull]
    assert _after(first, "-pass") == "1" and _after(second, "-pass") == "2"
    assert _after(second, "-passlogfile") == "/tmp/x/pass"
    assert second[-1] == "out.mkv"


def test_target_size_x265_uses_x265_params(cpu_caps):
    plan = plan_av_encode("mkv", _opts(video={"encoder": "libx265", "rate_control": "target_size", "target_size_mb": 50}), cpu_caps)
    first, second = _cmd(plan, info=SOURCE, passlog_prefix="/tmp/x/pass")
    assert _after(first, "-x265-params") == "pass=1:stats=/tmp/x/pass.log"
    assert _after(second, "-x265-params") == "pass=2:stats=/tmp/x/pass.log"


def test_target_size_too_small_is_rejected(cpu_caps):
    plan = plan_av_encode("mp4", _opts(video={"encoder": "libx264", "rate_control": "target_size", "target_size_mb": 1}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="too small"):
        _cmd(plan, info=SOURCE, passlog_prefix="/tmp/x/pass")


def test_vaapi_target_size_is_single_pass_vbr(cezanne_caps):
    plan = plan_av_encode("mp4", _opts(video={"codec": "hevc", "rate_control": "target_size", "target_size_mb": 100}), cezanne_caps)
    (cmd,) = _cmd(plan, info=SOURCE)
    assert _after(cmd, "-rc_mode") == "VBR"
    assert "-pass" not in cmd


def test_audio_only_output_from_video(cpu_caps):
    (cmd,) = _cmd(plan_av_encode("mp3", _opts(audio={"bitrate_kbps": 192, "sample_rate": 44100}), cpu_caps))
    assert cmd[cmd.index("-map"):cmd.index("-map") + 2] == ["-map", "0:a:0"]
    assert "-vf" not in cmd
    assert cmd[cmd.index("-c:a"):] == ["-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100", "out.mkv"]


def test_audio_container_rejects_video_options(cpu_caps):
    with pytest.raises(EncodeOptionsError, match="mp3 is an audio format"):
        plan_av_encode("mp3", _opts(video={"codec": "h264"}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="audio can't be removed"):
        plan_av_encode("mp3", _opts(audio={"codec": "none"}), cpu_caps)


def test_trim_copy_and_subtitles(cpu_caps):
    plan = plan_av_encode("mkv", _opts(video={"codec": "copy"}, audio={"codec": "copy"}, trim={"start_s": 10, "end_s": 30}, subtitles="copy"), cpu_caps)
    (cmd,) = _cmd(plan)
    assert cmd[:10] == ["ffmpeg", "-hide_banner", "-y", "-ss", "10", "-i", "in.mkv", "-t", "20", "-map"]
    assert ["-map", "0:s?", "-c:s", "copy"] == cmd[cmd.index("0:s?") - 1:cmd.index("0:s?") + 3]
    assert _after(cmd, "-c:v") == "copy"
    assert "-vf" not in cmd


def test_subtitle_copy_needs_mkv(cpu_caps):
    with pytest.raises(EncodeOptionsError, match="Subtitle copy isn't supported for mp4"):
        plan_av_encode("mp4", _opts(subtitles="copy"), cpu_caps)


def test_removing_audio(cpu_caps):
    (cmd,) = _cmd(plan_av_encode("mp4", _opts(audio={"codec": "none"}), cpu_caps))
    assert "-an" in cmd
    assert "0:a?" not in cmd


def test_unsupported_containers_reject_options(cpu_caps):
    with pytest.raises(EncodeOptionsError, match="aren't supported for wmv"):
        plan_av_encode("wmv", _opts(video={"codec": "h264"}), cpu_caps)
    with pytest.raises(EncodeOptionsError, match="options.image applies to image outputs"):
        plan_av_encode("mp4", _opts(image={"quality": 50}), cpu_caps)


def test_software_fallback_plan(cezanne_caps):
    plan = plan_av_encode("mkv", _opts(video={"codec": "hevc", "qp": 26, "bit_depth": 10}), cezanne_caps)
    fallback = software_fallback_plan(plan, cezanne_caps)
    assert fallback.video.encoder == "libx265"
    assert (fallback.video.rate_control, fallback.video.quality, fallback.video.preset) == ("crf", 26, "medium")
    assert fallback.video.bit_depth == 10
    assert fallback.vaapi_device is None

    no_fallback = plan_av_encode("mkv", _opts(video={"codec": "hevc"}, hw_fallback=False), cezanne_caps)
    assert software_fallback_plan(no_fallback, cezanne_caps) is None


def test_parse_encoder_list():
    listing = """Encoders:
 V..... = Video
 A..... = Audio
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D hevc_vaapi           H.265/HEVC (VAAPI) (codec hevc)
 A....D libopus              libopus Opus (codec opus)
"""
    assert parse_encoder_list(listing) == {"libx264", "hevc_vaapi", "libopus"}


def test_parse_probe_skips_cover_art():
    info = parse_probe({
        "format": {"duration": "61.5", "bit_rate": "4000000", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        "streams": [
            {"codec_type": "video", "codec_name": "mjpeg", "width": 600, "height": 600, "disposition": {"attached_pic": 1}},
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "avg_frame_rate": "30000/1001", "pix_fmt": "yuv420p"},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2, "sample_rate": "48000", "bit_rate": "128000"},
            {"codec_type": "subtitle", "codec_name": "mov_text"},
        ],
    })
    assert info.duration_s == 61.5
    assert info.bitrate_kbps == 4000
    assert (info.video.codec, info.video.width, info.video.fps, info.video.bit_depth) == ("h264", 1920, 29.97, 8)
    assert info.audio == [AudioStreamInfo("aac", 2, 48000, 128)]
    assert info.subtitle_count == 1
