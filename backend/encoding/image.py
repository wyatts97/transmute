"""Apply ``ImageOptions`` to a Pillow image and build its save kwargs."""
from __future__ import annotations

from PIL import Image, ImageOps

from .options import EncodeOptions, ImageOptions
from .resolve import EncodeOptionsError


# Formats where quality / effort / lossless controls are wired up. Other
# image outputs accept only max_dimension and strip_metadata.
TUNABLE_IMAGE_FORMATS = frozenset({"jpeg", "png", "webp", "avif", "jxl", "heif", "heic"})
_LOSSLESS_FORMATS = frozenset({"webp", "jxl", "png"})
_EFFORT_FORMATS = frozenset({"jpeg", "png", "webp", "avif", "jxl"})
_CHROMA_FORMATS = frozenset({"jpeg", "avif"})
_JPEG_SUBSAMPLING = {"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}


def validate_image_options(fmt: str, options: EncodeOptions) -> None:
    """Raise ``EncodeOptionsError`` when ``options`` don't fit image output ``fmt``."""
    for name in ("video", "audio", "trim", "subtitles"):
        if getattr(options, name) is not None:
            raise EncodeOptionsError(f"options.{name} applies to audio/video outputs, not {fmt}")
    image = options.image
    if image is None:
        return
    tuned = [
        name for name in ("quality", "lossless", "effort", "chroma_subsampling", "palette_colors")
        if getattr(image, name) is not None
    ]
    if fmt not in TUNABLE_IMAGE_FORMATS and tuned:
        raise EncodeOptionsError(
            f"Only max_dimension and strip_metadata apply to {fmt} output (got {', '.join(tuned)})"
        )
    if image.quality is not None and fmt == "png":
        raise EncodeOptionsError("PNG is lossless; use palette_colors to make it smaller")
    if image.lossless and fmt not in _LOSSLESS_FORMATS:
        raise EncodeOptionsError(f"Lossless isn't supported for {fmt}. Use webp, jxl, or png")
    if image.effort is not None and fmt not in _EFFORT_FORMATS:
        raise EncodeOptionsError(f"effort isn't supported for {fmt}")
    if image.chroma_subsampling is not None and fmt not in _CHROMA_FORMATS:
        raise EncodeOptionsError(f"chroma_subsampling applies to jpeg and avif, not {fmt}")
    if image.palette_colors is not None and fmt != "png":
        raise EncodeOptionsError("palette_colors applies to png output only")


def apply_image_options(img: Image.Image, fmt: str, options: EncodeOptions) -> tuple[Image.Image, dict]:
    """Return the (possibly resized/quantized) image and its ``save`` kwargs.

    ``strip_metadata`` semantics: ``True`` drops EXIF but keeps the ICC color
    profile, ``False`` keeps both, unset keeps Pillow's default behavior.
    EXIF orientation is baked into the pixels whenever EXIF is dropped or the
    image is resized, so photos never come out sideways.
    """
    validate_image_options(fmt, options)
    image = options.image or ImageOptions()
    icc_profile = img.info.get("icc_profile")

    if options.strip_metadata is not None or image.max_dimension:
        img = ImageOps.exif_transpose(img)
    if image.max_dimension and max(img.size) > image.max_dimension:
        img = img.copy()
        img.thumbnail((image.max_dimension, image.max_dimension), Image.LANCZOS)

    effort = image.effort
    kwargs: dict = {}
    if fmt == "jpeg":
        kwargs["quality"] = image.quality if image.quality is not None else 85
        kwargs["optimize"] = True
        kwargs["progressive"] = effort is None or effort >= 3
        if image.chroma_subsampling:
            kwargs["subsampling"] = _JPEG_SUBSAMPLING[image.chroma_subsampling]
    elif fmt == "webp":
        method = round((effort if effort is not None else 7) * 0.6)
        if image.lossless:
            # For lossless WebP, quality sets compression effort, not fidelity.
            kwargs.update(lossless=True, quality=(effort if effort is not None else 8) * 10, method=method)
        else:
            kwargs.update(quality=image.quality if image.quality is not None else 80, method=method)
    elif fmt == "avif":
        kwargs["quality"] = image.quality if image.quality is not None else 60
        kwargs["speed"] = 10 - (effort if effort is not None else 4)
        if image.chroma_subsampling:
            kwargs["subsampling"] = image.chroma_subsampling
    elif fmt == "jxl":
        if image.lossless:
            kwargs["lossless"] = True
        else:
            kwargs["quality"] = image.quality if image.quality is not None else 85
        kwargs["effort"] = 1 + round((effort if effort is not None else 7) * 0.8)
    elif fmt == "png":
        if image.palette_colors:
            method = Image.Quantize.FASTOCTREE if img.mode in ("RGBA", "LA", "PA") else Image.Quantize.MEDIANCUT
            img = img.convert("RGBA" if "A" in img.mode else "RGB").quantize(colors=image.palette_colors, method=method)
        if effort is None or effort >= 8:
            kwargs["optimize"] = True
        else:
            kwargs["compress_level"] = round(effort * 0.9)
    elif fmt in ("heif", "heic"):
        kwargs["quality"] = image.quality if image.quality is not None else 75

    if options.strip_metadata is False:
        exif = img.getexif()
        if exif:
            kwargs["exif"] = exif.tobytes()
        if icc_profile:
            kwargs["icc_profile"] = icc_profile
    elif options.strip_metadata is True and icc_profile:
        kwargs["icc_profile"] = icc_profile
    return img, kwargs
