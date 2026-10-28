from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import get_current_active_user, get_preset_db
from api.errors import options_validation_error
from api.schemas import (
    ErrorResponse,
    PresetCreateRequest,
    PresetListResponse,
    PresetResponse,
    PresetUpdateRequest,
)
from db import PresetDB
from encoding import BUILTIN_PRESETS, EncodeOptions, EncodeOptionsError, get_builtin_preset
from services import options_json_to_dict, options_to_json


router = APIRouter(prefix="/presets", tags=["presets"])

_AV_ONLY_FIELDS = ("video", "audio", "trim", "subtitles")


def _check_kind(kind: str, options: EncodeOptions) -> None:
    """Keep video presets free of image options and vice versa."""
    if kind == "video" and options.image is not None:
        raise options_validation_error(EncodeOptionsError("Video presets can't contain options.image"))
    if kind == "image":
        present = [name for name in _AV_ONLY_FIELDS if getattr(options, name) is not None]
        if present:
            raise options_validation_error(EncodeOptionsError(
                f"Image presets can't contain {', '.join('options.' + name for name in present)}"
            ))


def _serialize_preset(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "kind": row["kind"],
        "builtin": False,
        "options": options_json_to_dict(row.get("options_json")) or {},
        "created_at": str(row["created_at"]) if row.get("created_at") is not None else None,
        "updated_at": str(row["updated_at"]) if row.get("updated_at") is not None else None,
    }


def _reject_builtin(preset_id: str) -> None:
    if get_builtin_preset(preset_id) is not None:
        raise HTTPException(status_code=403, detail="Built-in presets are read-only")


@router.get(
    "",
    summary="List built-in and saved encode presets",
    responses={200: {"model": PresetListResponse, "description": "Built-in presets, then the current user's saved presets"}},
)
def list_presets(
    preset_db: PresetDB = Depends(get_preset_db),
    current_user: dict = Depends(get_current_active_user),
):
    builtin = [preset.describe() for preset in BUILTIN_PRESETS.values()]
    saved = [_serialize_preset(row) for row in preset_db.list_presets(current_user["uuid"])]
    return {"presets": builtin + saved}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Save a new encode preset",
    responses={
        201: {"model": PresetResponse, "description": "Preset saved; use its id as `preset` on a job"},
    },
)
def create_preset(
    request: PresetCreateRequest,
    preset_db: PresetDB = Depends(get_preset_db),
    current_user: dict = Depends(get_current_active_user),
):
    _check_kind(request.kind, request.options)
    row = preset_db.insert_preset(
        user_id=current_user["uuid"],
        name=request.name,
        description=request.description,
        kind=request.kind,
        options_json=options_to_json(request.options),
    )
    return _serialize_preset(row)


@router.get(
    "/{preset_id}",
    summary="Get one preset",
    responses={
        200: {"model": PresetResponse, "description": "The requested preset"},
        404: {"model": ErrorResponse, "description": "Preset not found"},
    },
)
def get_preset(
    preset_id: str,
    preset_db: PresetDB = Depends(get_preset_db),
    current_user: dict = Depends(get_current_active_user),
):
    builtin = get_builtin_preset(preset_id)
    if builtin is not None:
        return builtin.describe()
    row = preset_db.get_preset(preset_id, current_user["uuid"])
    if row is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    return _serialize_preset(row)


@router.patch(
    "/{preset_id}",
    summary="Update a saved preset",
    responses={
        200: {"model": PresetResponse, "description": "The updated preset"},
        403: {"model": ErrorResponse, "description": "Built-in presets are read-only"},
        404: {"model": ErrorResponse, "description": "Preset not found"},
    },
)
def update_preset(
    preset_id: str,
    request: PresetUpdateRequest,
    preset_db: PresetDB = Depends(get_preset_db),
    current_user: dict = Depends(get_current_active_user),
):
    _reject_builtin(preset_id)
    existing = preset_db.get_preset(preset_id, current_user["uuid"])
    if existing is None:
        raise HTTPException(status_code=404, detail="Preset not found")

    fields = request.model_dump(exclude_unset=True, exclude={"options"})
    kind = fields.get("kind", existing["kind"])
    options = request.options if "options" in request.model_fields_set else EncodeOptions.model_validate_json(existing["options_json"])
    if options is None:
        raise options_validation_error(EncodeOptionsError("options can't be null"))
    _check_kind(kind, options)
    if "options" in request.model_fields_set:
        fields["options_json"] = options_to_json(options)

    row = preset_db.update_preset(preset_id, current_user["uuid"], fields)
    return _serialize_preset(row)


@router.delete(
    "/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved preset",
    responses={
        204: {"description": "Preset deleted"},
        403: {"model": ErrorResponse, "description": "Built-in presets are read-only"},
        404: {"model": ErrorResponse, "description": "Preset not found"},
    },
)
def delete_preset(
    preset_id: str,
    preset_db: PresetDB = Depends(get_preset_db),
    current_user: dict = Depends(get_current_active_user),
):
    _reject_builtin(preset_id)
    if not preset_db.delete_preset(preset_id, current_user["uuid"]):
        raise HTTPException(status_code=404, detail="Preset not found")
    return None
