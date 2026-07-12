"""
Provides functionality for lazily deserializing classes field-by-field.

When deserializing an object, rather than deserializing all of its fields
immediately, some additional fields/methods are added:

- `_uniserde_field_definitions_`: A dictionary mapping field names to tuples of
  (field document name, field type).

- `_uniserde_remaining_fields_`: A dictionary mapping field document names to
  unparsed field values.

- `_uniserde_cache_`: The cache instance that was used to deserialize the
  object.

- `__getattr__`: A function that deserializes fields when they are first
  accessed, and then caches them in the instance.

Note that this approach allows for doing a lot of work up-front: The class,
along with all of its fields, and the `__getattr__` method only have to be
created once and can be reused for all future deserializations of that class.
"""

from __future__ import annotations

import inspect
import typing as t

from . import serde_cache, type_hint, utils
from .errors import SerdeError


def _lazy_getattr(self, name: str) -> t.Any:
    # Fetch the field definitions. This will fail if this particular instance
    # isn't lazy
    try:
        field_definitions: dict[str, tuple[str, type_hint.TypeHint]] = vars(self)[
            "_uniserde_field_definitions_"
        ]
    except KeyError:
        raise AttributeError(name) from None

    # See if there is a field definition for this field. This will fail if the
    # field doesn't exist
    try:
        field_doc_name, field_type = field_definitions[name]
    except KeyError:
        raise AttributeError(name) from None

    # Get the field value
    try:
        field_raw_value = self._uniserde_remaining_fields_.pop(field_doc_name)
    except KeyError:
        raise SerdeError(f"Missing field {field_doc_name!r}") from None

    # Deserialize it
    field_handler = self._uniserde_cache_._get_handler(
        field_type,
    )
    parsed_value = field_handler(
        self._uniserde_cache_,
        field_raw_value,
        field_type,
    )

    # Cache it
    vars(self)[name] = parsed_value

    # Return it
    return parsed_value


def _get_attribute_map(
    as_type: type_hint.TypeHint,
    serde: serde_cache.SerdeCache,
) -> dict[str, tuple[str, type_hint.TypeHint]]:
    # Already cached?
    try:
        return serde._field_map_cache[as_type.origin]
    except KeyError:
        pass

    # Fetch the attributes
    result = {
        attribute_py_name: (
            serde._python_attribute_name_to_doc_name(attribute_py_name),
            attribute_type,
        )
        for (
            attribute_py_name,
            attribute_type,
        ) in utils.get_class_attributes_recursive(as_type.origin).items()
    }

    # Cache the result
    serde._field_map_cache[as_type.origin] = result

    # Return it
    return result


def can_create_lazy_instance(as_type: type_hint.TypeHint) -> bool:
    """
    Verify that some conditions are met for creating a lazy instance of the
    given type.
    """

    # The class mustn't have a `__getattr__` method, since that would be
    # overwritten. If it is already overwritten that's fine though.
    try:
        return as_type.origin.__getattr__ is _lazy_getattr
    except AttributeError:
        return True


def create_lazy_instance(
    serialized: dict[str, t.Any],
    serdeserializer: serde_cache.SerdeCache,
    as_type: type_hint.TypeHint,
) -> t.Any:
    assert isinstance(serialized, dict), serialized
    assert inspect.isclass(as_type.origin), as_type
    assert serdeserializer._lazy, serdeserializer
    assert can_create_lazy_instance(as_type), as_type

    # Instantiate the result, skipping the constructor
    result = object.__new__(as_type.origin)

    # Set additional, internal fields
    type(result).__getattr__ = _lazy_getattr
    result._uniserde_field_definitions_ = _get_attribute_map(as_type, serdeserializer)
    result._uniserde_cache_ = serdeserializer
    result._uniserde_remaining_fields_ = serialized.copy()

    # Eagerly deserialize fields that have class-level defaults.
    #
    # This is necessary because `__getattr__` only triggers when an attribute is
    # not found. If the class has a default value Python will find it before
    # `__getattr__` is called. By eagerly deserializing these fields into the
    # instance __dict__, we ensure the instance value takes precedence over the
    # default stored in the class itself.
    _eagerly_deserialize_fields_with_defaults(result, as_type, serdeserializer)

    # Done
    return result


def _eagerly_deserialize_fields_with_defaults(
    instance: t.Any,
    as_type: type_hint.TypeHint,
    serdeserializer: serde_cache.SerdeCache,
) -> None:
    """
    Eagerly deserialize any fields that have class-level attributes.

    This prevents issues where class-level attributes (like dataclass defaults)
    shadow lazy deserialization via __getattr__.
    """
    field_definitions = instance._uniserde_field_definitions_
    remaining_fields = instance._uniserde_remaining_fields_

    # Eagerly deserialize fields that exist as class attributes
    for field_name in field_definitions.keys():
        if hasattr(as_type.origin, field_name):
            # This field exists as a class attribute - eagerly deserialize it
            # to ensure the instance value takes precedence

            # Get the field mapping
            field_doc_name, field_type = field_definitions[field_name]

            # Get the raw value
            try:
                field_raw_value = remaining_fields.pop(field_doc_name)
            except KeyError:
                # Field not in serialized data - this is fine, the class
                # attribute will be used as the default
                continue

            # Deserialize it
            field_handler = serdeserializer._get_handler(field_type)
            parsed_value = field_handler(
                serdeserializer,
                field_raw_value,
                field_type,
            )

            # Store directly in instance __dict__ to override class attribute
            vars(instance)[field_name] = parsed_value
