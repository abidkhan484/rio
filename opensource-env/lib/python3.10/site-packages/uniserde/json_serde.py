from __future__ import annotations

import copy
import typing as t

from . import case_convert, json_deserialize, json_serialize, type_hint, typedefs

T = t.TypeVar("T")


class JsonSerde:
    """
    A serializer/deserializer for JSON.

    This class is the main entrypoint for serializing and deserializing Python
    objects to and from JSON.

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
            t.Callable[
                [JsonSerde, t.Any, t.Type],
                typedefs.Jsonable,
            ],
        ] = {},
        custom_deserializers: dict[
            t.Type,
            t.Callable[
                [JsonSerde, t.Any, t.Type],
                typedefs.Jsonable,
            ],
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
        self._serialization_cache = json_serialize.JsonSerializationCache(
            context=self,
            custom_handlers={
                key: lambda _, value, as_type: handler(self, value, as_type.as_python())
                for key, handler in custom_serializers.items()
            },
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
        )

        self._deserialization_cache = json_deserialize.JsonDeserializationCache(
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

    @staticmethod
    def new_camel_case(
        *,
        custom_serializers: dict[
            t.Type,
            t.Callable[[JsonSerde, t.Any, t.Type], typedefs.Jsonable],
        ] = {},
        custom_deserializers: dict[
            t.Type,
            t.Callable[[JsonSerde, t.Any, t.Type], typedefs.Jsonable],
        ] = {},
        python_attribute_name_to_doc_name: t.Callable[
            [str], str
        ] = case_convert.all_lower_to_camel_case,
        python_class_name_to_doc_name: t.Callable[
            [str], str
        ] = case_convert.upper_camel_case_to_camel_case,
        python_enum_name_to_doc_name: t.Callable[
            [str], str
        ] = case_convert.all_upper_to_camel_case,
        lazy: bool = False,
    ) -> JsonSerde:
        """
        Creates a new `JsonSerde` using the old camel-case naming conventions.

        This is identical to calling `JsonSerde()` except with different naming
        conventions. Unlike the constructor, this method does not attempt to
        preserve Python style names and instead maps them to JavaScript style
        camel-case names - which is often preferred when working with JSON.

        Default settings:

        - Attributes: all_lower_case -> camelCase
        - Classes: UpperCamelCase -> camelCase
        - Enums: ALL_UPPER_CASE -> camelCase

        These names also match the default `uniserde` names before version 0.4,
        making it compatible with old codebases.
        """
        return JsonSerde(
            custom_serializers=custom_serializers,
            custom_deserializers=custom_deserializers,
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
            lazy=lazy,
        )

    def as_json(
        self,
        value: t.Any,
        *,
        as_type: t.Type | None = None,
    ) -> typedefs.JsonDoc:
        """
        Serializes the given value to JSON.

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

    def from_json(
        self,
        as_type: t.Type[T],
        value: t.Any,
        *,
        allow_mutation: bool = False,
    ) -> T:
        """
        Deserializes a Python instance from JSON.

        ## Parameters

        `as_type`: The type to deserialize the document as.

        `value`: The JSON document to deserialize from.

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
