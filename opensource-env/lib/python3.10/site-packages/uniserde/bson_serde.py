from __future__ import annotations

import copy
import typing as t

from . import (
    bson_deserialize,
    bson_serialize,
    case_convert,
    schema_mongodb,
    type_hint,
    typedefs,
)

T = t.TypeVar("T")


class BsonSerde:
    """
    A serializer/deserializer for BSON.

    This class is the main entrypoint for serializing and deserializing Python
    objects to and from BSON, as well as generating MongoDB schemas for them.

    ## Maximizing Performance

    Whenever a new type is encountered during serialization or deserialization,
    `uniserde` will create and cache the handler for that type. This means that
    types get faster to handle after the first time they are encountered. To
    make sure you benefit from this as much as possible, create few Serde
    instances and keep them around. This way the cache is reused across
    different calls in your script.
    """

    def __init__(
        self,
        *,
        custom_serializers: dict[
            t.Type,
            t.Callable[[BsonSerde, t.Any, t.Type], typedefs.Bsonable],
        ] = {},
        custom_deserializers: dict[
            t.Type,
            t.Callable[[BsonSerde, t.Any, t.Type], typedefs.Bsonable],
        ] = {},
        custom_schema_handlers: dict[
            t.Type,
            t.Callable[[BsonSerde, t.Type], typedefs.JsonDoc],
        ] = {},
        python_attribute_name_to_doc_name: t.Callable[
            [str], str
        ] = case_convert.identity,
        python_class_name_to_doc_name: t.Callable[[str], str] = case_convert.identity,
        python_enum_name_to_doc_name: t.Callable[[str], str] = case_convert.identity,
        lazy: bool = False,
    ) -> None:
        """
        Creates a new serializer/deserializer.

        ## Parameters

        `custom_serializers`: A dictionary mapping types to custom serializers.
            This allows you to override default behavior or add support for
            additional types. Handlers are called with the Serde instance, the
            value to serialize, and the type to serialize as.

        `custom_deserializers`: A dictionary mapping types to custom
            deserializers. This allows you to override default behavior or add
            support for additional types. Handlers are called with the Serde
            instance, the value to deserialize, and the type to deserialize as.

        `custom_schema_handlers`: A dictionary mapping types to custom schema
            handlers. This allows you to override default behavior or add
            support for additional types. Handlers are called with the Serde
            instance and the type to generate a schema for.

        `python_attribute_name_to_doc_name`: A function that derives the name
            attributes are stored as in the document from the attribute name in
            the Python class. The default uses the Python names verbatim.

        `python_class_name_to_doc_name`: A function that derives the name
            classes are stored as in the document from the class name in Python.
            The default uses the Python names verbatim.

        `python_enum_name_to_doc_name`: A function that derives the name enums
            are stored as in the document from the enum name in Python. The
            default uses the Python names verbatim.

        `lazy`: If `True` class deserialization will be deferred for as long as
            needed. Have a look at the README for details and caveats.
        """

        # Create caches
        self._serialization_cache = bson_serialize.BsonSerializationCache(
            context=self,
            custom_handlers={
                key: lambda _, value, as_type: handler(self, value, as_type.as_python())
                for key, handler in custom_serializers.items()
            },
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
        )

        self._deserialization_cache = bson_deserialize.BsonDeserializationCache(
            context=self,
            custom_handlers={
                key: lambda _, value, as_type: handler(self, value, as_type.as_python())
                for key, handler in custom_deserializers.items()
            },
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
            lazy=lazy,
        )

        self._mongodb_schema_converter = schema_mongodb.MongodbSchemaConverter(
            context=self,
            custom_handlers={
                key: lambda as_type: handler(self, as_type.as_python())
                for key, handler in custom_schema_handlers.items()
            },
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
        )

    @staticmethod
    def new_camel_case(
        *,
        custom_serializers: dict[
            t.Type,
            t.Callable[[BsonSerde, t.Any, t.Type], typedefs.Bsonable],
        ] = {},
        custom_deserializers: dict[
            t.Type,
            t.Callable[[BsonSerde, t.Any, t.Type], typedefs.Bsonable],
        ] = {},
        custom_schema_handlers: dict[
            t.Type,
            t.Callable[[BsonSerde, t.Type], typedefs.JsonDoc],
        ] = {},
        python_attribute_name_to_doc_name: t.Callable[
            [str], str
        ] = case_convert.all_lower_to_camel_case_with_id_exception,
        python_class_name_to_doc_name: t.Callable[
            [str], str
        ] = case_convert.upper_camel_case_to_camel_case,
        python_enum_name_to_doc_name: t.Callable[
            [str], str
        ] = case_convert.all_upper_to_camel_case,
        lazy: bool = False,
    ) -> BsonSerde:
        """
        Creates a new `BsonSerde` using the old camel-case naming conventions.

        This is identical to calling `BsonSerde()` except with different naming
        conventions. Unlike the constructor, this method does not attempt to
        preserve Python style names and instead maps them to JavaScript style
        camel-case names - which is often preferred when working with BSON.

        Default settings:

        - Attributes: all_lower_case -> camelCase (and "id" -> "_id")
        - Classes: UpperCamelCase -> camelCase
        - Enums: ALL_UPPER_CASE -> camelCase

        These names also match the default `uniserde` names before version 0.4,
        making it compatible with old codebases.
        """
        return BsonSerde(
            custom_serializers=custom_serializers,
            custom_deserializers=custom_deserializers,
            custom_schema_handlers=custom_schema_handlers,
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
            lazy=lazy,
        )

    def as_bson(
        self,
        value: t.Any,
        *,
        as_type: t.Type | None = None,
    ) -> typedefs.BsonDoc:
        """
        Serializes the given value to BSON.

        How a value gets serialized depends on its type. For example, you can
        serialize a child class as its parent by passing the parent into
        `as_type`. If no type is given, `type(value)` is used. _This is fine for
        classes, but will not work with generics._ For example, if passing in a
        list to serialize, `uniserde` needs to know how to handle the values in
        the list. In cases like this, you must pass in the type explicitly.
        """
        # What type to serialize as?
        if as_type is None:
            as_type = type(value)

        # Serialize the value
        as_type_hint = type_hint.TypeHint(as_type)

        handler = self._serialization_cache._get_handler(as_type_hint)

        return handler(
            self._serialization_cache,
            value,
            as_type_hint,
        )

    def from_bson(
        self,
        as_type: t.Type[T],
        value: t.Any,
        *,
        allow_mutation: bool = False,
    ) -> T:
        """
        Deserializes a Python instance from BSON.

        ## Parameters

        `as_type`: The type to deserialize the document as.

        `value`: The BSON document to deserialize from.

        `allow_mutation`: If `True`, the deserialization process is allowed to
            modify the document in-place. This can lead to better performance,
            but may not be suitable for all use-cases.

        ## Raises

        `uniserde.SerdeError`: If the document is not valid for the given type.
        """
        # Get the handler for the type
        as_type_hint = type_hint.TypeHint(as_type)
        handler = self._deserialization_cache._get_handler(as_type_hint)

        # Make a copy if needed
        if not allow_mutation:
            value = copy.deepcopy(value)

        # Deserialize the value
        return handler(
            self._deserialization_cache,
            value,
            as_type_hint,
        )

    def as_mongodb_schema(
        self,
        as_type: t.Type,
    ) -> typedefs.Jsonable:
        """
        Return a MongoDB schema for the given type class. The schema matches
        values that you would retrieve from `as_bson`. Adding them to your
        MongoDB collection can be used as an additional check to make sure you
        don't save corrupt data by accident.

        Note that not everything can be checked via schemas. They act as
        additional layer of protection, but will not catch all errors.
        """
        return self._mongodb_schema_converter._process(
            type_hint.TypeHint(as_type),
        )
