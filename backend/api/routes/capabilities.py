from fastapi import APIRouter, Depends

from api.deps import get_current_active_user
from api.schemas import CapabilitiesResponse
from encoding import BUILTIN_PRESETS, get_capabilities
from encoding.codec_matrix import describe_containers
from encoding.image import describe_image_formats

router = APIRouter(prefix="/capabilities", tags=["capabilities"], dependencies=[Depends(get_current_active_user)])


@router.get(
    "",
    summary="Describe the advanced encoding options this server supports",
    responses={
        200: {
            "model": CapabilitiesResponse,
            "description": "Usable encoders (including verified hardware encoders), container/codec rules, image option support, and built-in presets",
        }
    },
)
def get_encoding_capabilities():
    """Everything a client needs to build valid ``options`` for this host.

    Hardware encoders are listed only after a one-frame test encode succeeded
    on the configured device, so anything listed here can be requested.
    """
    caps = get_capabilities().describe()
    return {
        **caps,
        "containers": describe_containers(),
        "image_formats": describe_image_formats(),
        "presets": [preset.describe() for preset in BUILTIN_PRESETS.values()],
    }
