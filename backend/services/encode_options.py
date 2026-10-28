"""Resolve a request's ``preset`` + ``options`` and validate them for a job.

Routes call these at submit time so bad options fail fast with a 422; the
resolved options are stored on the job and replayed by the worker.

Precedence (highest first): explicit ``options`` fields, the named
``preset``, the legacy ``quality``/``compression_level`` preset (applied
inside the encoder), then encoder defaults.
"""
from __future__ import annotations

import json

from encoding import EncodeOptions, EncodeOptionsError, get_builtin_preset, merge_options


class UnknownPresetError(EncodeOptionsError):
    """The requested preset is neither built in nor saved by this user."""


def load_preset_options(preset: str, user_id: str, preset_db) -> EncodeOptions:
    """Return the options of a built-in preset key or one of the user's saved presets."""
    builtin = get_builtin_preset(preset)
    if builtin is not None:
        return builtin.options
    row = preset_db.get_preset(preset, user_id) if preset_db is not None else None
    if row is None:
        raise UnknownPresetError(f"Unknown preset '{preset}'. List presets with GET /api/presets")
    return EncodeOptions.model_validate_json(row["options_json"])


def resolve_request_options(
    *,
    preset: str | None,
    options: EncodeOptions | None,
    user_id: str,
    preset_db=None,
) -> EncodeOptions | None:
    """Merge explicit options over a preset. ``None`` means the legacy path.

    An empty ``options`` object (``{}``) counts as no options so it keeps the
    exact legacy behavior.
    """
    if options is not None and not options.model_fields_set:
        options = None
    base = load_preset_options(preset, user_id, preset_db) if preset else None
    if base is None and options is None:
        return None
    return merge_options(base, options)


def validate_conversion_options(converter_type, input_format: str, output_format: str, quality: str | None, options: EncodeOptions) -> None:
    if not getattr(converter_type, "supports_options", False):
        raise EncodeOptionsError(
            f"Advanced options aren't supported for {input_format} to {output_format} conversions"
        )
    converter_type.validate_options(input_format, output_format, quality, options)


def validate_compression_options(compressor_type, media_format: str, compression_level: str | None, options: EncodeOptions) -> None:
    if not getattr(compressor_type, "supports_options", False):
        raise EncodeOptionsError(f"Advanced options aren't supported for {media_format} compression")
    compressor_type.validate_options(media_format, compression_level, options)


def options_to_json(options: EncodeOptions | None) -> str | None:
    return options.model_dump_json(exclude_none=True) if options is not None else None


def options_from_json(raw: str | None) -> EncodeOptions | None:
    return EncodeOptions.model_validate_json(raw) if raw else None


def options_to_dict(options: EncodeOptions | None) -> dict | None:
    return options.model_dump(mode="json", exclude_none=True) if options is not None else None


def options_json_to_dict(raw: str | None) -> dict | None:
    """Decode stored options JSON for API responses (``None`` if absent or corrupt)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
