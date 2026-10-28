"""Service layer for executing conversions.

This module isolates the actual work of running a converter and persisting
its result so the same code path can be invoked from:

- The legacy synchronous ``POST /api/conversions`` route.
- The background queue worker that processes ``ConversionJobDB`` entries.

The service does not raise ``HTTPException``; callers translate exceptions
into the appropriate error response (HTTP for the route, ``mark_failed``
for the worker).
"""
from __future__ import annotations

import errno
from pathlib import Path
import shutil
import threading
import uuid
from zipfile import ZIP_DEFLATED, ZipFile

from converters import ConverterInterface
from core import (
    compute_sha256_checksum,
    delete_file_and_metadata,
    get_settings,
    media_type_extensions,
    validate_safe_path,
)
from db import (
    ConversionDB,
    ConversionRelationsDB,
    DefaultQualitiesDB,
    FileDB,
    SettingsDB,
)
from encoding import EncodeOptions
from encoding.ffmpeg_runner import ProgressCallback

from .encode_options import options_to_dict


# Synthetic input formats produced by URL downloaders that pass straight
# through to a real base format without re-encoding. Mirrors the table in
# ``api.routes.conversions`` (kept here so the worker doesn't need to import
# from a route module).
WEB_ALIAS_PASSTHROUGH: dict[str, str] = {
    "webvideo": "mp4",
    "webaudio": "m4a",
}


class ConversionFailedError(RuntimeError):
    """Raised when the underlying converter fails to produce output."""


def _copy_web_alias_to_base(
    input_path: str, temp_dir: Path, converted_id: str, output_format: str
) -> list[str]:
    """Pass-through copy for downloader-backed aliases (no re-encoding)."""
    output_path = temp_dir / f"{converted_id}.{output_format}"
    shutil.copy2(input_path, output_path)
    return [str(output_path)]


def _move_output_file(source_path: Path, target_path: Path) -> Path:
    """Persist a converter output even when temp/output dirs are separate mounts."""
    try:
        return source_path.rename(target_path)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise

    shutil.move(str(source_path), str(target_path))
    return target_path


def run_conversion_job(
    *,
    source_metadata: dict,
    output_format: str,
    quality: str | None,
    converter_type: type[ConverterInterface],
    user_id: str,
    file_db: FileDB,
    conversion_db: ConversionDB,
    conversion_relations_db: ConversionRelationsDB,
    settings_db: SettingsDB,
    default_qualities_db: DefaultQualitiesDB | None = None,
    options: EncodeOptions | None = None,
    preset: str | None = None,
    progress_cb: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Execute a conversion and persist the resulting metadata.

    Args:
        source_metadata: Result of ``FileDB.get_file_metadata`` for the
            source file. Must already be ownership-checked by the caller.
        output_format: Sanitized target format string (e.g. ``"png"``).
        quality: Optional quality hint. If ``None`` and
            ``default_qualities_db`` is provided, the user's default for the
            output format (if any) is applied.
        converter_type: A converter class returned by
            ``registry.get_converter_for_conversion``.
        user_id: UUID of the owning user (the converted file is stored
            under this user).
        file_db, conversion_db, conversion_relations_db, settings_db:
            Shared DB handles supplied by the caller.
        default_qualities_db: Optional handle used to resolve a default
            quality when ``quality`` is ``None``.
        options: Resolved advanced options (see ``encode_options``). ``None``
            keeps the legacy behavior.
        preset: Preset key or id the options came from, recorded with the output.
        progress_cb: Receives encode progress (advanced options path only).
        cancel_event: Set to stop a running encode (advanced options path only).

    Returns:
        The converted file metadata dict (including ``id``,
        ``storage_path``, ``size_bytes``, ``sha256_checksum``, and
        ``quality`` if used).

    Raises:
        ConversionFailedError: The converter raised an exception.
    """
    settings = get_settings()
    temp_dir = settings.tmp_dir
    converted_dir = settings.output_dir

    validate_safe_path(source_metadata["storage_path"], raise_exception=True)

    input_format = source_metadata["media_type"]
    output_extension = f".{media_type_extensions.get(output_format, output_format)}"
    converted_id = str(uuid.uuid4())

    # Resolve default quality lazily so the user's current setting wins.
    if quality is None and default_qualities_db is not None:
        default_quality = default_qualities_db.get(user_id, output_format)
        if default_quality:
            quality = default_quality["quality"]

    converter: ConverterInterface = converter_type(
        source_metadata["storage_path"],
        f"{temp_dir}/",
        input_format,
        output_format,
    )

    convert_kwargs: dict = {"quality": quality}
    if options is not None:
        if not getattr(converter_type, "supports_options", False):
            raise ConversionFailedError(
                f"Advanced options aren't supported for {input_format} to {output_format} conversions"
            )
        convert_kwargs.update(options=options, progress_cb=progress_cb, cancel_event=cancel_event)

    try:
        passthrough_base = WEB_ALIAS_PASSTHROUGH.get(input_format)
        # Advanced options always re-encode, so they skip the pass-through copy.
        if passthrough_base is not None and output_format == passthrough_base and options is None:
            output_files = _copy_web_alias_to_base(
                source_metadata["storage_path"], Path(temp_dir), converted_id, output_format
            )
        else:
            output_files = converter.convert(**convert_kwargs)
    except Exception as exc:
        raise ConversionFailedError(str(exc)) from exc

    if not output_files:
        raise ConversionFailedError("Converter produced no output files")

    if len(output_files) == 1:
        moved_output_file = _move_output_file(
            Path(output_files[0]),
            Path(f"{converted_dir}/{converted_id}{output_extension}"),
        )
        final_media_type = output_format
        final_extension = output_extension
    else:
        # Multiple output files (e.g. multi-page PDF -> image). Package them
        # into a single ZIP so the rest of the pipeline (DB, downloads,
        # history) can keep treating each conversion as one persisted
        # artifact.
        moved_output_file = Path(f"{converted_dir}/{converted_id}.zip")
        # Rename entries to use the original uploaded filename's stem
        # instead of the UUID-based temp filename, so the user sees
        # something recognizable inside the archive.
        original_stem = Path(source_metadata.get("original_filename") or "output").stem or "output"
        try:
            with ZipFile(moved_output_file, "w", ZIP_DEFLATED) as zf:
                for path_str in output_files:
                    src = Path(path_str)
                    # Keep any "-page-NNN" suffix and the extension; just
                    # swap the leading UUID stem for the original stem.
                    src_stem = src.stem
                    suffix = src.suffix
                    # Drop the leading temp stem if present.
                    if "-page-" in src_stem:
                        page_part = src_stem.split("-page-", 1)[1]
                        arc_stem = f"{original_stem}-page-{page_part}"
                    else:
                        arc_stem = original_stem
                    arcname = f"{arc_stem}{suffix}"
                    zf.write(src, arcname=arcname)
        except Exception as exc:
            if moved_output_file.exists():
                try:
                    moved_output_file.unlink()
                except OSError:
                    pass
            raise ConversionFailedError(
                f"Failed to package multi-file conversion output: {exc}"
            ) from exc
        # Best-effort cleanup of the per-page temp files now that they are
        # safely inside the ZIP. Leave them on disk if removal fails — the
        # cleanup task will reap them later.
        for path_str in output_files:
            try:
                Path(path_str).unlink(missing_ok=True)
            except OSError:
                pass
        final_media_type = "zip"
        final_extension = ".zip"

    converted_metadata = dict(source_metadata)
    converted_metadata["id"] = converted_id
    converted_metadata["media_type"] = final_media_type
    converted_metadata["extension"] = final_extension
    converted_metadata["storage_path"] = str(moved_output_file)
    converted_metadata["size_bytes"] = moved_output_file.stat().st_size
    converted_metadata["sha256_checksum"] = compute_sha256_checksum(moved_output_file)
    converted_metadata["user_id"] = user_id
    converted_metadata.pop("created_at", None)
    if quality:
        converted_metadata["quality"] = quality
    encode_metadata = {}
    if options is not None:
        encode_metadata = {
            "options": options_to_dict(options),
            "preset": preset,
            "encoder_used": getattr(converter, "encoder_used", None),
        }
    converted_metadata.update(encode_metadata)

    conversion_db.insert_file_metadata(converted_metadata)
    if quality:
        # ``insert_file_metadata`` pops quality off; re-attach for the return value.
        converted_metadata["quality"] = quality
    converted_metadata.update(encode_metadata)

    conversion_relations_db.insert_conversion_relation({
        "original_file_id": source_metadata["id"],
        "converted_file_id": converted_id,
        "original_filename": source_metadata["original_filename"],
        "original_media_type": source_metadata["media_type"],
        "original_extension": source_metadata["extension"],
        "original_size_bytes": source_metadata["size_bytes"],
        "user_id": user_id,
    })

    if settings_db.get_settings(user_id).get("keep_originals", True) is False:
        delete_file_and_metadata(file_id=source_metadata["id"], file_db=file_db)

    return converted_metadata
