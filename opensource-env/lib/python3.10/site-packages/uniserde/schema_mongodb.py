from __future__ import annotations

import enum
import inspect
import typing as t
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import type_hint, typedefs, utils
from .objectid_proxy import ObjectId


class MongodbSchemaConverter:
    def __init__(
        self,
        *,
        context: t.Any,
        custom_handlers: dict[
            t.Type, t.Callable[[type_hint.TypeHint], typedefs.JsonDoc]
        ],
        python_attribute_name_to_doc_name: t.Callable[[str], str],
        python_class_name_to_doc_name: t.Callable[[str], str],
        python_enum_name_to_doc_name: t.Callable[[str], str],
    ) -> None:
        self._context = context

        self._user_provided_handlers = custom_handlers
        self._python_attribute_name_to_doc_name = python_attribute_name_to_doc_name
        self._python_class_name_to_doc_name = python_class_name_to_doc_name
        self._python_enum_name_to_doc_name = python_enum_name_to_doc_name

        # This field can be used to disable UUIDs to be verified. This is useful
        # because the packages that's used in the unit tests to verify the
        # schemas doesn't recognize UUIDs as "binData", even though that's how
        # pymongo treats them.
        self._enable_uuid_verification = True

    def _process(self, as_type: type_hint.TypeHint) -> typedefs.JsonDoc:
        # Custom handlers take precedence
        try:
            handler = self._user_provided_handlers[as_type.origin]
        except KeyError:
            pass
        else:
            return handler(as_type)

        # Is there a special handler in that class?
        try:
            override_method = getattr(as_type.origin, "_uniserde_as_mongodb_schema_")
        except AttributeError:
            pass
        else:
            return override_method(self._context, as_type.as_python())

        # Plain old default handler
        try:
            handler = self._schema_builders[as_type.origin]
        except KeyError:
            pass
        else:
            return handler(self, as_type)

        assert inspect.isclass(as_type.origin), as_type

        # Flag enum
        if issubclass(as_type.origin, enum.Flag):
            return self._make_schema_flag_enum(as_type.origin)

        # Enum
        if issubclass(as_type.origin, enum.Enum):
            return self._make_schema_enum(as_type.origin)

        # General class
        serialize_as_root = utils.root_of_serialize_as_child(as_type.origin)

        if serialize_as_root is None:
            return self._make_schema_attribute_by_attribute_no_child(as_type.origin)
        else:
            return self._make_schema_attribute_by_attribute_as_child(as_type)

    def _make_schema_bool_to_bool(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {"type": "boolean"}

    def _make_schema_int_to_int(self, as_type: type_hint.TypeHint) -> typedefs.JsonDoc:
        return {"bsonType": ["int", "long"]}

    def _make_schema_float_to_float(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {"bsonType": ["int", "long", "double"]}

    def _make_schema_bytes_to_bytes(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {"bsonType": "binData"}

    def _make_schema_str_to_str(self, as_type: type_hint.TypeHint) -> typedefs.JsonDoc:
        return {"type": "string"}

    def _make_schema_datetime_to_datetime(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {"bsonType": "date"}

    def _make_schema_timedelta_to_float(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {"bsonType": ["int", "long", "double"]}

    def _make_schema_tuple_to_list(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {
            "type": "array",
            "items": [self._process(subtype) for subtype in as_type.args],
        }

    def _make_schema_list_to_list(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {
            "type": "array",
            "items": self._process(as_type.args[0]),
        }

    def _make_schema_set_to_list(self, as_type: type_hint.TypeHint) -> typedefs.JsonDoc:
        return {
            "type": "array",
            "items": self._process(as_type.args[0]),
        }

    def _make_schema_path_to_str(self, as_type: type_hint.TypeHint) -> typedefs.JsonDoc:
        return {"type": "string"}

    def _make_schema_uuid_to_uuid(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        if self._enable_uuid_verification:
            return {"bsonType": "binData"}

        return {}

    def _make_schema_dict_to_dict(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {
            "type": "object",
            "items": self._process(as_type.args[1]),
        }

    def _make_schema_object_id_to_object_id(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {"bsonType": "objectId"}

    def _make_schema_literal_to_str(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        return {"type": "string"}

    def _make_schema_optional(self, as_type: type_hint.TypeHint) -> typedefs.JsonDoc:
        # Create a schema for each subtype
        #
        # The function was originally written to support general unions. While
        # not supported by `uniserde` right now, the code is still here.
        sub_schemas: list[typedefs.JsonDoc] = [
            {"type": "null"},
        ]

        for sub_as_type in as_type.args:
            sub_schemas.append(self._process(sub_as_type))

        # Prettify the result: instead of `{anyof {type ...} {type ...}}` just
        # create one `type`
        types = []
        bson_types = []
        others = []

        for schema in sub_schemas:
            if len(schema) == 1:
                # Standard Json Schema type
                try:
                    type_field = schema["type"]
                except KeyError:
                    pass
                else:
                    if isinstance(type_field, list):
                        types.extend(type_field)
                    else:
                        types.append(type_field)

                    continue

                # BSON type
                try:
                    type_field = schema["bsonType"]
                except KeyError:
                    pass
                else:
                    if isinstance(type_field, list):
                        bson_types.extend(type_field)
                    else:
                        bson_types.append(type_field)

                    continue

            # General case
            others.append(schema)

        # Create new, merged schemas
        sub_schemas: list[typedefs.JsonDoc] = []

        if bson_types:
            sub_schemas.append({"bsonType": types + bson_types})
        elif types:
            sub_schemas.append({"type": types})

        sub_schemas.extend(others)

        if len(sub_schemas) == 1:
            return sub_schemas[0]

        return {"anyOf": sub_schemas}  # type: ignore  (pyright sillyness)

    def _make_schema_any(self, as_type: type_hint.TypeHint) -> typedefs.JsonDoc:
        return {}

    def _make_schema_attribute_by_attribute_no_child(
        self, cls: t.Type
    ) -> typedefs.JsonDoc:
        assert inspect.isclass(cls), cls

        doc_field_names = []
        doc_properties = {}
        result = {
            "type": "object",
            "properties": doc_properties,
            "additionalProperties": False,
        }

        for field_py_name, field_type in utils.get_class_attributes_recursive(
            cls
        ).items():
            field_doc_name = self._python_attribute_name_to_doc_name(field_py_name)

            doc_field_names.append(field_doc_name)
            doc_properties[field_doc_name] = self._process(field_type)

        # The `required` field may only be present if it contains at least one value
        if doc_field_names:
            result["required"] = doc_field_names

        return result

    def _make_schema_attribute_by_attribute_as_child(
        self, as_type: type_hint.TypeHint
    ) -> typedefs.JsonDoc:
        assert inspect.isclass(as_type.origin), as_type

        # Case: Class or one of its children
        #
        # Create the schemas for all allowable classes
        sub_schemas = []
        for subtype in utils.all_subclasses(as_type.origin, True):
            schema: t.Any = self._make_schema_attribute_by_attribute_no_child(subtype)
            assert schema["type"] == "object", schema

            schema["properties"]["type"] = {
                "enum": [self._python_class_name_to_doc_name(subtype.__name__)]
            }

            required = schema.setdefault("required", [])
            required.insert(0, "type")

            sub_schemas.append(schema)

        # Create the final, combined schema
        if len(sub_schemas) == 1:
            return sub_schemas[0]
        else:
            return {"anyOf": sub_schemas}

    def _make_schema_flag_enum(self, cls: t.Type[enum.Flag]) -> typedefs.JsonDoc:
        return {
            "type": "array",
            "items": {
                "enum": [
                    self._python_enum_name_to_doc_name(variant.name)  # type: ignore
                    for variant in cls
                ],
            },
        }

    def _make_schema_enum(self, cls: t.Type[enum.Enum]) -> typedefs.JsonDoc:
        return {
            "enum": [
                self._python_enum_name_to_doc_name(variant.name) for variant in cls
            ],
        }

    _schema_builders: dict[
        t.Type,
        t.Callable[[MongodbSchemaConverter, type_hint.TypeHint], typedefs.JsonDoc],
    ] = {
        bool: _make_schema_bool_to_bool,
        int: _make_schema_int_to_int,
        float: _make_schema_float_to_float,
        bytes: _make_schema_bytes_to_bytes,
        str: _make_schema_str_to_str,
        datetime: _make_schema_datetime_to_datetime,
        timedelta: _make_schema_timedelta_to_float,
        list: _make_schema_list_to_list,
        dict: _make_schema_dict_to_dict,
        t.Optional: _make_schema_optional,
        t.Any: _make_schema_any,
        ObjectId: _make_schema_object_id_to_object_id,
        t.Literal: _make_schema_literal_to_str,
        tuple: _make_schema_tuple_to_list,
        set: _make_schema_set_to_list,
        Path: _make_schema_path_to_str,
        type(Path()): _make_schema_path_to_str,
        uuid.UUID: _make_schema_uuid_to_uuid,
    }  # type: ignore
