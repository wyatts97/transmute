from fastapi import HTTPException

from encoding import EncodeOptionsError
from services.encode_options import UnknownPresetError


def options_validation_error(exc: EncodeOptionsError, field: str | None = None) -> HTTPException:
    """A 422 shaped exactly like FastAPI's request validation errors.

    Keeping one 422 shape (``detail`` is a list of ``{loc, msg, type}``) means
    clients that already handle validation errors handle option errors too.
    """
    field = field or ("preset" if isinstance(exc, UnknownPresetError) else "options")
    return HTTPException(
        status_code=422,
        detail=[{"loc": ["body", field], "msg": str(exc), "type": "value_error"}],
    )
