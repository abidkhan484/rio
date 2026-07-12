from __future__ import annotations

import typing as t
import uuid
from datetime import datetime

from . import (
    codegen,
    json_serialize,
    objectid_proxy,
    serde_cache,
    type_hint,
    typedefs,
)
from .objectid_proxy import ObjectId


def _build_handler_datetime_to_datetime(
    serde: BsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.expose_value("datetime", datetime)

    gen.write(
        f"assert isinstance({value}, datetime), {value}",
        f'assert {value}.tzinfo is not None, "Encountered datetime without a timezone. Please always set timezones, or expect hard to find bugs."',
    )
    return value


def _build_handler_objectid_to_objectid(
    serde: BsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.expose_value("bson", objectid_proxy)

    gen.write(
        f"assert isinstance({value}, bson.ObjectId), {value}",
    )
    return value


def _build_handler_uuid_to_uuid(
    serde: BsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.expose_value("uuid", uuid)

    gen.write(
        f"assert isinstance({value}, uuid.UUID), {value}",
    )
    return value


BSON_HANDLER_BUILDERS = {
    **json_serialize.JSON_HANDLER_BUILDERS,
    bytes: json_serialize._build_passthrough_handler,
    datetime: _build_handler_datetime_to_datetime,
    ObjectId: _build_handler_objectid_to_objectid,
    uuid.UUID: _build_handler_uuid_to_uuid,
}


class BsonSerializationCache(serde_cache.SerdeCache[typedefs.Bsonable, t.Any]):
    """
    Configuration & cache for serializing BSON into Python objects.
    """

    def __init__(
        self,
        *,
        context: t.Any,
        custom_handlers: dict[t.Type, serde_cache.InternalHandler],
        python_attribute_name_to_doc_name: t.Callable[[str], str],
        python_class_name_to_doc_name: t.Callable[[str], str],
        python_enum_name_to_doc_name: t.Callable[[str], str],
    ) -> None:
        super().__init__(
            context=context,
            eager_class_handler_builders=BSON_HANDLER_BUILDERS,
            lazy_class_handler_builders={},
            override_method_name="_uniserde_as_bson_",
            user_provided_handlers=custom_handlers,
            lazy=False,
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
        )

    _build_attribute_by_attribute_class_handler = json_serialize.JsonSerializationCache._build_attribute_by_attribute_class_handler  # type: ignore

    _build_attribute_by_attribute_class_handler_without_children = json_serialize.JsonSerializationCache._build_attribute_by_attribute_class_handler_without_children  # type: ignore

    _build_flag_enum_handler = (
        json_serialize.JsonSerializationCache._build_flag_enum_handler
    )

    _build_enum_handler = json_serialize.JsonSerializationCache._build_enum_handler
