from __future__ import annotations

import base64
import enum
import inspect
import pathlib
import typing as t
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import codegen, objectid_proxy, serde_cache, type_hint, typedefs, utils
from .objectid_proxy import ObjectId


def _build_passthrough_handler(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    """
    Builds a handler that simply checks the type of the value and raises an
    exception if it is not the expected type.

    The value itself is returned as-is.
    """
    gen.write(
        f'assert isinstance({value}, {as_type.origin.__name__}), "Value annotated as `{as_type.origin.__name__}` has value {{!r}}".format({value})'
    )

    return value


def _build_handler_float_to_float(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.write(
        f'assert isinstance({value}, (int, float)), "Value annotated as `float` has value {{!r}}".format({value})'
    )
    return value


def _build_handler_bytes_to_str(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("base64", base64)

    gen.write(
        f'assert isinstance({value}, bytes), "Field annotated as bytes has value {{!r}}".format({value})',
        f"{result_var} = base64.b64encode({value}).decode('utf-8')",
    )

    return result_var


def _build_handler_datetime_to_str(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("datetime", datetime)

    gen.write(
        f"assert isinstance({value}, datetime), {value}",
        f"assert {value}.tzinfo is not None, 'Encountered datetime without a timezone. Please always set timezones, or expect hard to find bugs.'",
        f"{result_var} = {value}.isoformat()",
    )

    return result_var


def _build_handler_timedelta_to_float(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("timedelta", timedelta)

    gen.write(
        f"assert isinstance({value}, timedelta), {value}",
        f"{result_var} = {value}.total_seconds()",
    )

    return result_var


def _build_handler_tuple_to_list(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    gen.write(
        f"assert isinstance({value}, tuple), {value}",
        f"assert len({value}) == {len(as_type.args)}, {value}",
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

    gen.write("", f"{result_var} = [{', '.join(subresults)}]")

    return result_var


def _build_handler_list_to_list(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()
    count_var = gen.get_new_variable()

    gen.write(
        f'assert isinstance({value}, list), "Field annotated as list has value {{!r}}".format({value})',
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


def _build_handler_set_to_list(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()
    count_var = gen.get_new_variable()

    gen.write(
        f"assert isinstance({value}, set), {value}",
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


def _build_handler_dict_to_dict(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()
    key_var = gen.get_new_variable()
    value_var = gen.get_new_variable()

    key_as_type, value_as_type = as_type.args

    gen.write(
        f"assert isinstance({value}, dict), {value}",
        f"{result_var} = {{}}",
        f"",
        f"for {key_var}, {value_var} in {value}.items():",
    )

    gen.indentation_level += 1

    # Serialize the key
    if key_as_type.origin is str:
        gen.write(
            f"assert isinstance({key_var}, str), {key_var}",
        )
        key_result = key_var
    elif key_as_type.origin is int:
        key_result = gen.get_new_variable()
        gen.write(
            f"assert isinstance({key_var}, int), {key_var}",
            f"{key_result} = str({key_var})",
        )
    else:
        raise AssertionError(
            f"{key_as_type.pretty_string()} is not supported for dictionary keys"
        )

    value_result = serde._write_single_handler(
        gen,
        value_var,
        value_as_type,
    )

    gen.write(f"{result_var}[{key_result}] = {value_result}")

    gen.indentation_level -= 1
    return result_var


def _build_handler_object_id_to_str(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("bson", objectid_proxy)

    gen.write(
        f"assert isinstance({value}, bson.ObjectId), {value}",
        f"{result_var} = str({value})",
    )

    return result_var


def _build_handler_optional(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> t.Any:
    # `Optional` is really just an alias for `Union`. Find the non-`None`
    # subtype
    result_var = gen.get_new_variable()

    # Don't get too clever here. Yes, it would be nice to reuse the same result
    # variable as the subresult, but that would not only require a needless
    # negation in the `if`, but also lead to problems if a subresult doesn't
    # actually return a variable, but say `int(variable)`.
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
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> t.Any:
    return value


def _build_handler_literal_to_str(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> t.Any:
    gen.write(f"assert isinstance({value}, str), {value}")
    return value


def _build_handler_path_to_str(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("pathlib", pathlib)

    gen.write(
        f"assert isinstance({value}, pathlib.Path), {value}",
        f"{result_var} = str({value}.absolute())",
    )

    return result_var


def _build_handler_uuid_to_str(
    serde: JsonSerializationCache,
    gen: codegen.Codegen,
    value: t.Any,
    as_type: type_hint.TypeHint,
) -> str:
    result_var = gen.get_new_variable()

    gen.expose_value("uuid", uuid)

    gen.write(
        f"assert isinstance({value}, uuid.UUID), {value}",
        f"{result_var} = str({value})",
    )

    return result_var


JSON_HANDLER_BUILDERS: dict[t.Type, serde_cache.HandlerBuilder] = {
    bool: _build_passthrough_handler,
    int: _build_passthrough_handler,
    float: _build_handler_float_to_float,
    str: _build_passthrough_handler,
    bytes: _build_handler_bytes_to_str,
    datetime: _build_handler_datetime_to_str,
    timedelta: _build_handler_timedelta_to_float,
    tuple: _build_handler_tuple_to_list,
    list: _build_handler_list_to_list,
    set: _build_handler_set_to_list,
    dict: _build_handler_dict_to_dict,
    t.Optional: _build_handler_optional,
    t.Any: _build_handler_any_to_any,
    ObjectId: _build_handler_object_id_to_str,
    t.Literal: _build_handler_literal_to_str,
    Path: _build_handler_path_to_str,
    type(Path()): _build_handler_path_to_str,
    uuid.UUID: _build_handler_uuid_to_str,
}  # type: ignore


class JsonSerializationCache(serde_cache.SerdeCache[typedefs.Jsonable, t.Any]):
    """
    Configuration & cache for serializing JSON into Python objects.
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
            eager_class_handler_builders=JSON_HANDLER_BUILDERS,
            lazy_class_handler_builders={},
            override_method_name="_uniserde_as_json_",
            user_provided_handlers=custom_handlers,
            lazy=False,
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

        # If this class is not serialized `@as_child`, create regular
        # serialization logic.
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

        # Otherwise delegate to a serializer for every possible child class.
        runtime_cls_var = gen.get_new_variable()

        gen.write(
            f"{runtime_cls_var} = type({input_variable_name})",
        )

        for ii, sub_cls in enumerate(utils.all_subclasses(serialize_as_root, True)):
            sub_cls_var = gen.get_new_variable()
            gen.expose_value(sub_cls_var, sub_cls)

            if ii == 0:
                gen.write(f"if {runtime_cls_var} is {sub_cls_var}:")
            else:
                gen.write(f"elif {runtime_cls_var} is {sub_cls_var}:")

            gen.indentation_level += 1

            self._build_attribute_by_attribute_class_handler_without_children(
                gen,
                input_variable_name,
                result_var,
                type_hint.TypeHint(sub_cls),
            )

            # Add the type tag
            gen.write(
                f"{result_var}['type'] = {self._python_class_name_to_doc_name(sub_cls.__name__)!r}",
            )

            gen.indentation_level -= 1

        # Error case
        gen.write(
            f"else:",
            f'    raise AssertionError("Unexpected class {{}}".format({runtime_cls_var}))',
        )

        # Phew!
        return result_var

    def _build_attribute_by_attribute_class_handler_without_children(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        result_var: str,
        as_type: type_hint.TypeHint,
    ) -> str:
        gen.write(
            f"{result_var} = {{}}",
        )

        # Serialize all fields
        for field_py_name, field_as_type in utils.get_class_attributes_recursive(
            as_type.origin
        ).items():
            field_doc_name = self._python_attribute_name_to_doc_name(field_py_name)

            gen.write(f"# {field_py_name}")

            subresult = self._write_single_handler(
                gen,
                f"{input_variable_name}.{field_py_name}",
                field_as_type,
            )

            gen.write(f"{result_var}[{field_doc_name!r}] = {subresult}")

        return result_var

    def _build_flag_enum_handler(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        as_type: type_hint.TypeHint,
    ) -> str:
        assert issubclass(as_type.origin, enum.Flag), as_type

        result_var = gen.get_new_variable()
        options_var = gen.get_new_variable()
        flag_cls_var = gen.get_new_variable()
        count_var = gen.get_new_variable()

        gen.expose_value(flag_cls_var, as_type.origin)

        # Prepare a serialized version of all options
        option_py_name_to_doc_name: dict[str, str] = {}

        for option in as_type.origin:
            # How can opt_py_type be None here? According to VSCode it can be
            assert option.name is not None, "How can this be None?"

            opt_doc_name = self._python_enum_name_to_doc_name(option.name)
            option_py_name_to_doc_name[option.name] = opt_doc_name

        # Iterate all options and look them up
        gen.write(
            f"{options_var} = {option_py_name_to_doc_name!r}",
            f"{result_var} = []",
            f"",
            f"for {count_var} in {flag_cls_var}:",
            f"   if {count_var} in {input_variable_name}:",
            f"        {result_var}.append({options_var}[{count_var}.name])",
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
        options_var = gen.get_new_variable()

        # Prepare a serialized version of all options
        option_py_name_to_doc_name = {
            opt.name: self._python_enum_name_to_doc_name(opt.name)
            for opt in as_type.origin
        }

        # Look up the value
        gen.write(
            f"{options_var} = {option_py_name_to_doc_name!r}",
            f"{result_var} = {options_var}[{input_variable_name}.name]",
        )

        return result_var
