import os

from .bson_serde import BsonSerde as BsonSerde
from .errors import SerdeError as SerdeError
from .json_serde import JsonSerde as JsonSerde
from .objectid_proxy import ObjectId as ObjectId
from .typedefs import *
from .utils import as_child as as_child

# Be compatible with versions <0.4 if requested
if os.environ.get("UNISERDE_BACKWARDS_COMPATIBILITY"):
    from .compat import (
        Serde as Serde,
    )
    from .compat import (
        as_bson as as_bson,
    )
    from .compat import (
        as_json as as_json,
    )
    from .compat import (
        from_bson as from_bson,
    )
    from .compat import (
        from_json as from_json,
    )
