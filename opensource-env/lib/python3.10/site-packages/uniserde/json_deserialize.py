from __future__ import annotations

import base64
import binascii
import enum
import inspect
import pathlib
import typing as t
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import dateutil.parser

from . import (
    codegen,
    lazy_wrapper,
    objectid_proxy,
    serde_cache,
    type_hint,
    typedefs,
    utils,
)
from .objectid_proxy import ObjectId


def _build_passthrough_handler(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    simple_type_hint: type_hint.TypeHint,
) -> str:
    """
    Builds a handler that simply checks the type of the value and raises an
    exception if it is not the expected type.

    The value itself is returned as-is.
    """
    gen.write(
        f"if not isinstance({value}, {simple_type_hint.origin.__name__}):",
        f"    raise SerdeError('Expected {simple_type_hint.origin.__name__}, got {{}}'.format({value}))",
    )

    return value


def _build_handler_int_from_int(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.write(
        f"if not isinstance({value}, int) and not (isinstance({value}, float) and {value}.is_integer()):",
        f"    raise SerdeError('Expected int, got {{}}'.format({value}))",
    )
    return f"int({value})"


def _build_handler_float_from_float(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.write(
        f"if not isinstance({value}, (int, float)):",
        f"    raise SerdeError('Expected float, got {{}}'.format({value!r}))",
    )
    return f"float({value})"


def _build_handler_bytes_from_str(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("base64", base64)
    gen.expose_value("binascii", binascii)

    gen.write(
        f"if not isinstance({value}, str):",
        f"    raise SerdeError('Expected bytes encoded as base64, got {{}}'.format({value}))",
        f"",
        f"try:",
        f"    {result_var} = base64.b64decode({value}.encode('utf-8'))",
        f"except binascii.Error as e:",
        f"    raise SerdeError('Encountered invalid base64 string: {{}}'.format(e)) from None",
    )

    return result_var


def _build_handler_datetime_from_str(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("dateutil_parser", dateutil.parser)

    gen.write(
        f"if not isinstance({value}, str):",
        f"    raise SerdeError('Expected date/time string, got {{}}'.format({value}))",
        f"",
        f"try:",
        f"  {result_var} = dateutil_parser.isoparse({value})",
        f"except ValueError:",
        f"  raise SerdeError('Invalid date/time string: {{}}'.format({value})) from None",
        f"",
        f"if {result_var}.tzinfo is None:",
        f"    raise SerdeError('The date/time value `{{}}` is missing a timezone.'.format({value}))",
    )

    return result_var


def _build_handler_float_to_timedelta(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("timedelta", timedelta)

    gen.write(
        f"if not isinstance({value}, (int, float)):",
        f"    raise SerdeError('Expected duration in seconds, got {{}}'.format({value}))",
        f"",
        f"{result_var} = timedelta(seconds={value})",
    )

    return result_var


def _build_handler_list_to_tuple(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.write(
        f"if not isinstance({value}, list):",
        f"    raise SerdeError('Expected list, got {{}}'.format({value}))",
        f"",
        f"if len({value}) != {len(as_type.args)}:",
        f"    raise SerdeError('Expected list of length {len(as_type.args)}, got {{}}'.format(len({value})))",
        f"",
    )

    # Convert the individual values
    subresults: list[str] = []

    for ii, sub_type in enumerate(as_type.args):
        subresult = serde._write_single_handler(
            gen,
            f"{value}[{ii}]",
            sub_type,
        )
        subresults.append(subresult)

    # Return the result
    result_var = gen.get_new_variable()

    gen.write("", f"{result_var} = tuple([{', '.join(subresults)}])")

    return result_var


def _build_handler_list_to_list(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()
    count_var = gen.get_new_variable()

    gen.write(
        f"if not isinstance({value}, list):",
        f"    raise SerdeError('Expected list, got {{}}'.format({value}))",
        f"",
        f"{result_var} = []",
        f"",
        f"for {count_var} in {value}:",
    )

    gen.indentation_level += 1

    subresult = serde._write_single_handler(
        gen,
        count_var,
        as_type.args[0],
    )

    gen.write(f"{result_var}.append({subresult})")

    gen.indentation_level -= 1
    return result_var


def _build_handler_list_to_set(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()
    count_var = gen.get_new_variable()

    gen.write(
        f"if not isinstance({value}, list):",
        f"    raise SerdeError('Expected list, got {{}}'.format({value}))",
        f"",
        f"{result_var} = set()",
        f"",
        f"for {count_var} in {value}:",
    )

    gen.indentation_level += 1

    subresult = serde._write_single_handler(
        gen,
        count_var,
        as_type.args[0],
    )

    gen.write(f"{result_var}.add({subresult})")

    gen.indentation_level -= 1
    return result_var


def _build_handler_dict_to_dict(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()
    key_var = gen.get_new_variable()
    value_var = gen.get_new_variable()

    key_as_type, value_as_type = as_type.args

    gen.write(
        f"if not isinstance({value}, dict):",
        f"    raise SerdeError('Expected dict, got {{}}'.format({value}))",
        f"",
        f"{result_var} = {{}}",
        f"",
        f"for {key_var}, {value_var} in {value}.items():",
    )

    gen.indentation_level += 1

    # Deserialize the key
    if key_as_type.origin is str:
        key_result = f"{key_var}"
    elif key_as_type.origin is int:
        key_result = gen.get_new_variable()
        gen.write(
            f"try:",
            f"    {key_result} = int({key_var})",
            f"except ValueError:",
            f'    raise SerdeError("Invalid key in object: Expected integer, got {{}}".format({key_var})) from None',
        )
    else:
        raise AssertionError(
            f"{key_as_type.pretty_string()} is not supported for dictionary keys"
        )

    # Deserialize the value
    value_result = serde._write_single_handler(
        gen,
        value_var,
        value_as_type,
    )

    gen.write(f"{result_var}[{key_result}] = {value_result}")

    gen.indentation_level -= 1
    return result_var


def _build_handler_object_id_from_str(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("bson", objectid_proxy)

    gen.write(
        f"if not isinstance({value}, str):",
        f"    raise SerdeError('Expected str, got {{}}'.format({value}))",
        f"",
        f"try:",
        f"    {result_var} = bson.ObjectId({value})",
        f"except bson.errors.InvalidId as e:",
        f"    raise SerdeError('Invalid ObjectId: {{}}'.format(e)) from None",
    )

    return result_var


def _build_handler_optional(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> t.Any:
    # Don't get too clever here. Yes, it would be nice to reuse the same result
    # variable as the subresult, but that would not only require a needless
    # negation in the `if`, but also lead to problems if a subresult doesn't
    # actually return a variable, but say `int(variable)`.
    result_var = gen.get_new_variable()

    gen.write(
        f"if {value} is None:",
        f"    {result_var} = None",
        f"else:",
    )

    gen.indentation_level += 1
    subresult_var = serde._write_single_handler(
        gen,
        value,
        as_type.args[0],
    )
    gen.write(f"{result_var} = {subresult_var}")
    gen.indentation_level -= 1

    return result_var


def _build_handler_any_to_any(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> t.Any:
    return value


def _build_handler_literal_from_str(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> t.Any:
    gen.write(
        f"if not isinstance({value}, str):",
        f"    raise SerdeError('Expected str, got {{}}'.format({value}))",
        f"",
        f"if {value} not in {as_type.literal_args!r}:",
        f'    raise SerdeError("Expected one of {as_type.literal_args!r}, got {{}}".format({value}))',
    )

    return value


def _build_handler_path_from_str(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("pathlib", pathlib)

    gen.write(
        f"if not isinstance({value}, str):",
        f"    raise SerdeError('Expected str, got {{}}'.format({value}))",
        f"",
        f"{result_var} = pathlib.Path({value})",
    )

    return result_var


def _build_handler_uuid_from_str(
    serde: JsonDeserializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("uuid", uuid)

    gen.write(
        f"if not isinstance({value}, str):",
        f"    raise SerdeError('Expected str, got {{}}'.format({value}))",
        f"",
        f"try:",
        f"    {result_var} = uuid.UUID({value})",
        f"except ValueError as e:",
        f"    raise SerdeError('Invalid UUID: {{}}'.format(e)) from None",
    )

    return result_var


JSON_HANDLER_BUILDERS: dict[t.Type, serde_cache.HandlerBuilder] = {
    bool: _build_passthrough_handler,
    int: _build_handler_int_from_int,
    float: _build_handler_float_from_float,
    str: _build_passthrough_handler,
    bytes: _build_handler_bytes_from_str,
    datetime: _build_handler_datetime_from_str,
    timedelta: _build_handler_float_to_timedelta,
    tuple: _build_handler_list_to_tuple,
    list: _build_handler_list_to_list,
    set: _build_handler_list_to_set,
    dict: _build_handler_dict_to_dict,
    t.Optional: _build_handler_optional,
    t.Any: _build_handler_any_to_any,
    ObjectId: _build_handler_object_id_from_str,
    t.Literal: _build_handler_literal_from_str,
    Path: _build_handler_path_from_str,
    type(Path()): _build_handler_path_from_str,
    uuid.UUID: _build_handler_uuid_from_str,
}  # type: ignore


class JsonDeserializationCache(serde_cache.SerdeCache[typedefs.Jsonable, t.Any]):
    """
    Configuration & cache for deserializing JSON into Python objects.
    """

    def __init__(
        self,
        *,
        context: t.Any,
        custom_handlers: dict[t.Type, serde_cache.InternalHandler],
        lazy: bool,
        python_attribute_name_to_doc_name: t.Callable[[str], str],
        python_class_name_to_doc_name: t.Callable[[str], str],
        python_enum_name_to_doc_name: t.Callable[[str], str],
    ) -> None:
        super().__init__(
            context=context,
            eager_class_handler_builders=JSON_HANDLER_BUILDERS,
            lazy_class_handler_builders={},
            override_method_name="_uniserde_from_json_",
            user_provided_handlers=custom_handlers,
            lazy=lazy,
            python_attribute_name_to_doc_name=python_attribute_name_to_doc_name,
            python_class_name_to_doc_name=python_class_name_to_doc_name,
            python_enum_name_to_doc_name=python_enum_name_to_doc_name,
        )

    def _build_attribute_by_attribute_class_handler(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        as_type: type_hint.TypeHint,
    ) -> str:
        assert inspect.isclass(as_type.origin), as_type

        # Make sure the input is a dictionary. By handling it here the code
        # isn't repeated in every subclass.
        gen.write(
            f"if not isinstance({input_variable_name}, dict):",
            f"    raise SerdeError('Expected class instance stored as object, got {{}}'.format({input_variable_name}))",
            f"",
        )

        # If this class is not serialized `@as_child`, create regular
        # deserialization logic.
        result_var = gen.get_new_variable()
        serialize_as_root = utils.root_of_serialize_as_child(as_type.origin)

        if serialize_as_root is None:
            self._build_attribute_by_attribute_class_handler_without_children(
                gen,
                input_variable_name,
                result_var,
                as_type,
            )
            return result_var

        # Otherwise precompute a list of possible classes. Then delegate to a
        # deserializer for every possible child class.
        doc_key_to_child_class = {
            self._python_class_name_to_doc_name(sub_cls.__name__): sub_cls
            for sub_cls in utils.all_subclasses(serialize_as_root, True)
        }

        # Which class to deserialize is stored in the `type` field
        type_var = gen.get_new_variable()

        gen.write(
            f"try:",
            f'    {type_var} = {input_variable_name}.pop("type")',
            f"except KeyError:",
            f'    raise SerdeError("Missing `type` field in {as_type.origin.__name__} instance") from None',
            f"",
            f"match {type_var}:",
        )
        gen.indentation_level += 1

        for sub_cls_type_key, sub_cls in doc_key_to_child_class.items():
            gen.write(
                f"case {sub_cls_type_key!r}:",
            )
            gen.indentation_level += 1

            self._build_attribute_by_attribute_class_handler_without_children(
                gen,
                input_variable_name,
                result_var,
                type_hint.TypeHint(sub_cls),
            )

            gen.indentation_level -= 1

        # Error case
        gen.write(
            f"case _:",
            f'    raise SerdeError("Invalid `type` value in {as_type.origin.__name__} instance: {{}}".format({type_var}))',
        )

        gen.indentation_level -= 1

        # Phew!
        return result_var

    def _build_attribute_by_attribute_class_handler_without_children(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        result_var: str,
        as_type: type_hint.TypeHint,
    ) -> None:
        dict_var = gen.get_new_variable()

        # Go lazy?
        if self._lazy and lazy_wrapper.can_create_lazy_instance(as_type):
            lazy_wrapper_var = gen.get_new_variable()
            self_var = gen.get_new_variable()
            cls_var = gen.get_new_variable()

            gen.expose_value(lazy_wrapper_var, lazy_wrapper)
            gen.expose_value(self_var, self)
            gen.expose_value(cls_var, as_type)

            gen.write(
                f"{result_var} = {lazy_wrapper_var}.create_lazy_instance({input_variable_name}, {self_var}, {cls_var})",
            )
            return

        # Go eager!
        cls_var = gen.get_new_variable()
        gen.expose_value(cls_var, as_type.origin)

        gen.write(
            f"{result_var} = object.__new__({cls_var})",
            f"{dict_var} = vars({result_var})",
            f"",
        )

        # Deserialize all fields
        for field_py_name, field_as_type in utils.get_class_attributes_recursive(
            as_type.origin
        ).items():
            field_doc_name = self._python_attribute_name_to_doc_name(field_py_name)

            gen.write(f"# {field_py_name}")
            field_var = gen.get_new_variable()
            gen.write(
                f"try:",
                f"    {field_var} = {input_variable_name}.pop({field_doc_name!r})",
                f"except KeyError:",
                f"    raise SerdeError('Missing field {{}}'.format({field_doc_name!r})) from None",
                f"",
            )

            subresult = self._write_single_handler(
                gen,
                field_var,
                field_as_type,
            )
            gen.write(f"{dict_var}[{field_py_name!r}] = {subresult}")

        # Make sure no superfluous fields are present
        gen.write(
            f"",
            f"if {input_variable_name}:",
            f"    raise SerdeError('Object contains superfluous fields: {{}}'.format({input_variable_name}.keys()))",
        )

    def _build_flag_enum_handler(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        as_type: type_hint.TypeHint,
    ) -> str:
        assert issubclass(as_type.origin, enum.Flag), as_type

        result_var = gen.get_new_variable()
        cls_var = gen.get_new_variable()
        options_var = gen.get_new_variable()
        count_var = gen.get_new_variable()

        gen.expose_value(cls_var, as_type.origin)

        # Prepare a serialized version of all options. Do this right in the
        # code, so the enum options can already be instantiated.
        gen.write(f"{options_var} = {{")

        for option in as_type.origin:
            # How can opt_py_type be None here? According to VSCode it can be
            assert option.name is not None, option
            option_py_name = option.name
            option_doc_name = self._python_enum_name_to_doc_name(option_py_name)

            gen.write(f"    {option_doc_name!r}: {cls_var}.{option_py_name},")

        # Look up all received options and add them to the result
        gen.write(
            f"}}",
            f"",
            f"{result_var} = {cls_var}(0)",
            f"",
            f"for {count_var} in {input_variable_name}:",
            f"    if not isinstance({count_var}, str):",
            f"        raise SerdeError('Expected enumeration value as string, got `{{}}`'.format({count_var}))",
            f"",
            f"    try:",
            f"        {result_var} |= {options_var}[{count_var}]",
            f"    except KeyError:",
            f"        raise SerdeError('Invalid enumeration value `{{}}`'.format({count_var})) from None",
        )

        return result_var

    def _build_enum_handler(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        as_type: type_hint.TypeHint,
    ) -> str:
        assert issubclass(as_type.origin, enum.Enum), as_type

        result_var = gen.get_new_variable()
        cls_var = gen.get_new_variable()
        options_var = gen.get_new_variable()

        gen.expose_value(cls_var, as_type.origin)

        # Prepare a serialized version of all options. Do this right in the
        # code, so the enum options can already be instantiated.
        gen.write(f"{options_var} = {{")

        for option in as_type.origin:
            option_py_name = option.name
            option_doc_name = self._python_enum_name_to_doc_name(option_py_name)

            gen.write(f"    {option_doc_name!r}: {cls_var}.{option_py_name},")

        # Look up the value
        gen.write(
            f"}}",
            f"",
            f"if not isinstance({input_variable_name}, str):",
            f"    raise SerdeError('Expected enumeration value as string, got `{{}}`'.format({input_variable_name}))",
            f"",
            f"try:",
            f"    {result_var} = {options_var}[{input_variable_name}]",
            f"except KeyError:",
            f"    raise SerdeError('Invalid enumeration value `{{}}`'.format({input_variable_name})) from None",
        )

        return result_var
