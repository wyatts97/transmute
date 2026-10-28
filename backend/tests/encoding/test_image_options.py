"""Advanced image options through PillowCompressor and PillowConverter."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageCms, JpegImagePlugin

from compressors.pillow_compress import PillowCompressor
from converters.pillow_convert import PillowConverter
from encoding import EncodeOptions, EncodeOptionsError
from encoding.image import validate_image_options


@pytest.fixture
def image_env(safe_path_test_settings, monkeypatch):
    monkeypatch.setattr("compressors.pillow_compress.get_settings", lambda: safe_path_test_settings)
    return safe_path_test_settings


def _gradient(size=(400, 300), mode="RGBA") -> Image.Image:
    img = Image.new(mode, size)
    width, height = size
    img.putdata([
        ((x * 255) // width, (y * 255) // height, ((x + y) * 127) // (width + height), 200)[: len(mode)]
        for y in range(height) for x in range(width)
    ])
    return img


def _srgb_icc() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@pytest.fixture
def png_source(image_env) -> Path:
    path = image_env.upload_dir / f"{'b2' * 16}.png"
    _gradient().save(path)
    return path


@pytest.fixture
def jpeg_with_metadata(image_env) -> Path:
    """40x20 JPEG tagged orientation=6 (display rotated 90°), with EXIF + ICC."""
    path = image_env.upload_dir / f"{'c3' * 16}.jpeg"
    exif = Image.Exif()
    exif[0x0112] = 6        # Orientation
    exif[0x010F] = "TestCam"  # Make
    _gradient((40, 20), "RGB").save(path, exif=exif.tobytes(), icc_profile=_srgb_icc(), quality=95)
    return path


def _convert(png_source, image_env, output_type, options) -> Image.Image:
    converter = PillowConverter(str(png_source), str(image_env.output_dir), "png", output_type)
    (output,) = converter.convert(options=EncodeOptions.model_validate(options))
    assert converter.encoder_used == "pillow"
    return Image.open(output)


def test_webp_quality_controls_size(png_source, image_env):
    # Both encodes write the same output path, so measure each right away.
    low_size = Path(_convert(png_source, image_env, "webp", {"image": {"quality": 20}}).filename).stat().st_size
    high_size = Path(_convert(png_source, image_env, "webp", {"image": {"quality": 95}}).filename).stat().st_size
    assert low_size < high_size


def test_webp_lossless(png_source, image_env):
    img = _convert(png_source, image_env, "webp", {"image": {"lossless": True, "effort": 2}})
    assert img.size == (400, 300)


def test_max_dimension_keeps_aspect_and_never_upscales(png_source, image_env):
    assert _convert(png_source, image_env, "avif", {"image": {"max_dimension": 100}}).size == (100, 75)
    assert _convert(png_source, image_env, "jpeg", {"image": {"max_dimension": 4000}}).size == (400, 300)


def test_jpeg_chroma_subsampling(png_source, image_env):
    full = _convert(png_source, image_env, "jpeg", {"image": {"quality": 90, "chroma_subsampling": "4:4:4"}})
    assert JpegImagePlugin.get_sampling(full) == 0
    sub = _convert(png_source, image_env, "jpeg", {"image": {"quality": 90, "chroma_subsampling": "4:2:0"}})
    assert JpegImagePlugin.get_sampling(sub) == 2


def test_png_palette_quantize_via_compressor(png_source, image_env):
    compressor = PillowCompressor(str(png_source), str(image_env.output_dir), "png")
    (output,) = compressor.compress(options=EncodeOptions.model_validate({"image": {"palette_colors": 32}}))
    result = Image.open(output)
    assert result.mode == "P"
    assert len(result.getcolors()) <= 32
    assert Path(output).stat().st_size < png_source.stat().st_size


def test_strip_metadata_drops_exif_keeps_icc_and_bakes_orientation(jpeg_with_metadata, image_env):
    compressor = PillowCompressor(str(jpeg_with_metadata), str(image_env.output_dir), "jpeg")
    (output,) = compressor.compress(options=EncodeOptions.model_validate({"strip_metadata": True, "keep_if_larger": True}))
    result = Image.open(output)
    assert result.size == (20, 40)
    assert not result.getexif()
    assert result.info.get("icc_profile")


def test_keep_metadata_preserves_exif(jpeg_with_metadata, image_env):
    compressor = PillowCompressor(str(jpeg_with_metadata), str(image_env.output_dir), "jpeg")
    (output,) = compressor.compress(options=EncodeOptions.model_validate({"strip_metadata": False, "keep_if_larger": True}))
    result = Image.open(output)
    assert result.getexif().get(0x010F) == "TestCam"
    # Orientation is applied to the pixels, so the tag is removed.
    assert result.getexif().get(0x0112) is None
    assert result.size == (20, 40)


def test_compression_level_still_applies_under_options(png_source, image_env):
    jpeg = image_env.upload_dir / f"{'d4' * 16}.jpeg"
    _gradient((400, 300), "RGB").save(jpeg, quality=98)
    compressor = PillowCompressor(str(jpeg), str(image_env.output_dir), "jpeg")
    (light,) = compressor.compress(compression_level="light", options=EncodeOptions.model_validate({"strip_metadata": True}))
    light_size = Path(light).stat().st_size
    (heavy,) = compressor.compress(compression_level="max", options=EncodeOptions.model_validate({"strip_metadata": True}))
    assert Path(heavy).stat().st_size < light_size


@pytest.mark.parametrize(
    ("fmt", "options", "message"),
    [
        ("png", {"image": {"quality": 50}}, "PNG is lossless"),
        ("avif", {"image": {"lossless": True}}, "Lossless isn't supported for avif"),
        ("bmp", {"image": {"quality": 50}}, "Only max_dimension and strip_metadata apply to bmp"),
        ("webp", {"image": {"chroma_subsampling": "4:4:4"}}, "chroma_subsampling applies to jpeg and avif"),
        ("jpeg", {"image": {"palette_colors": 16}}, "palette_colors applies to png"),
        ("heif", {"image": {"effort": 5}}, "effort isn't supported for heif"),
        ("webp", {"video": {"codec": "h264"}}, "options.video applies to audio/video outputs"),
    ],
)
def test_invalid_image_options(fmt, options, message):
    with pytest.raises(EncodeOptionsError, match=message):
        validate_image_options(fmt, EncodeOptions.model_validate(options))


def test_converter_rejects_invalid_options_before_encoding(png_source, image_env):
    converter = PillowConverter(str(png_source), str(image_env.output_dir), "png", "bmp")
    with pytest.raises(EncodeOptionsError):
        converter.convert(options=EncodeOptions.model_validate({"image": {"quality": 40}}))
