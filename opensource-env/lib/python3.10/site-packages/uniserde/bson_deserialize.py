from __future__ import annotations

import typing as t
import uuid
from datetime import datetime, timezone

from . import (
    codegen,
    json_deserialize,
    objectid_proxy,
    serde_cache,
    type_hint,
    typedefs,
)
from .objectid_proxy import ObjectId


def _build_handler_datetime_from_datetime(
    serde: BsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("datetime", datetime)
    gen.expose_value("timezone", timezone)

    # BSON doesn't support timezones, and MongoDB convention dictates UTC to be
    # assumed. Impute that.
    gen.write(
        f"if not isinstance({value}, datetime):",
        f"    raise SerdeError('Expected datetime, got {{}}'.format({value}))",
        f"",
        f"if {value}.tzinfo is None:",
        f"    {result_var} = {value}.replace(tzinfo=timezone.utc)",
        f"else:",
        f"    {result_var} = {value}",
    )

    return result_var


def _build_handler_object_id_from_objectid(
    serde: BsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.expose_value("bson", objectid_proxy)

    gen.write(
        f"if not isinstance({value}, bson.ObjectId):",
        f"    raise SerdeError('Expected ObjectId, got {{}}'.format({value}))",
    )

    return value


def _build_handler_uuid_from_uuid(
    serde: BsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.expose_value("uuid", uuid)

    gen.write(
        f"if not isinstance({value}, uuid.UUID):",
        f"    raise SerdeError('Expected UUID, got {{}}'.format({value}))",
    )

    return value


BSON_HANDLER_BUILDERS = {
    **json_deserialize.JSON_HANDLER_BUILDERS,
    bytes: json_deserialize._build_passthrough_handler,
    datetime: _build_handler_datetime_from_datetime,
    ObjectId: _build_handler_object_id_from_objectid,
    uuid.UUID: _build_handler_uuid_from_uuid,
}


class BsonDeserializationCache(serde_cache.SerdeCache[typedefs.Bsonable, t.Any]):
    """
    Configuration & cache for deserializing BSON into Python objects.
    """

    def __init__(
        self,
        *,
        context: t.Any,
        custom_handlers: dict[t.Type, serde_cache.InternalHandler],
        lazy: bool = False,
        python_attribute_name_to_doc_name: t.Callable[[str], str],
        python_class_name_to_doc_name: t.Callable[[str], str],
        python_enum_name_to_doc_name: t.Callable[[str], str],
    ) -> None:
        super().__init__(
            context=context,
            eager_class_handler_builders=BSON_HANDLER_BUILDERS,
            lazy_class_handler_builders={},
            override_method_name="_uniserde_from_bson_",
            user_provided_handlers=custom_handlers,
            lazy=lazy,
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
        )

    _build_attribute_by_attribute_class_handler = json_deserialize.JsonDeserializationCache._build_attribute_by_attribute_class_handler  # type: ignore

    _build_attribute_by_attribute_class_handler_without_children = json_deserialize.JsonDeserializationCache._build_attribute_by_attribute_class_handler_without_children

    _build_flag_enum_handler = (
        json_deserialize.JsonDeserializationCache._build_flag_enum_handler
    )
    _build_enum_handler = json_deserialize.JsonDeserializationCache._build_enum_handler
