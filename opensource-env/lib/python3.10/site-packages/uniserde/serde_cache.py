from __future__ import annotations

import enum
import inspect
import typing as t
from abc import ABC, abstractmethod

import typing_extensions as te

from . import codegen, type_hint
from .errors import SerdeError

IN = t.TypeVar("IN")
OUT = t.TypeVar("OUT")


UserHandler: te.TypeAlias = t.Callable[
    [
        "SerdeCache",
        IN,
        t.Type[OUT],
    ],
    OUT,
]


InternalHandler: te.TypeAlias = t.Callable[
    [
        "SerdeCache",
        IN,
        type_hint.TypeHint,
    ],
    OUT,
]


# This function is provided with a context, code generator, the name of a
# variable that stores the value to be converted, and the type of the value. It
# should write code which converts the value.
#
# Returns a a short code snippet that can be used to retrieve the result. This
# is usually the name of a variable, but can also be some other **fast**,
# **pure** code, like `some_list[1]`.
HandlerBuilder: te.TypeAlias = t.Callable[
    [
        "SerdeCache",
        codegen.Codegen,
        str,
        type_hint.TypeHint,
    ],
    str,
]


class SerdeCache(ABC, t.Generic[IN, OUT]):
    """
    Applies a conversion handler function (such as a serializer or deserializer) to an
    object, recursively. Which function is applied depends on the type of the
    object, allowing you to define different behavior for different types.

    Some of these functions can take substantial time to create. For example, a
    function handling a class might have to look up all of the class's
    attributes. For this reason, the converter caches handlers so subsequent
    accesses are faster.

    Handling also often entails converting casing in strings. For example, a
    field may be called `field_name` in Python, but `fieldName` in JSON. Those
    string conversions are also cached.
    """

    # The cache for all conversion handlers. Passthrough types are mapped to
    # `None` instead of a handler.
    _all_handler_builders: dict[t.Type, HandlerBuilder]

    def __init__(
        self,
        *,
        context: t.Any,
        eager_class_handler_builders: dict[t.Type, HandlerBuilder],
        lazy_class_handler_builders: dict[t.Type, HandlerBuilder],
        override_method_name: str,
        user_provided_handlers: dict[t.Type, InternalHandler],
        lazy: bool,
        python_attribute_name_to_doc_name: t.Callable[[str], str],
        python_class_name_to_doc_name: t.Callable[[str], str],
        python_enum_name_to_doc_name: t.Callable[[str], str],
    ) -> None:
        """
        Creates a new context.

        ## Parameters

        `eager_class_handlers`: Maps type keys to handlers. This acts as cache
            for previously seen types. Types may also map to `None`, in which
            case they're passed through without any function calls, saving some
            time.

        `lazy_class_handlers`: Same as above, but for lazy handlers. Any
            handlers in here take precedence over the eager handlers if the
            context is lazy. They're ignored by eager contexts.

        `override_method_name`: If a method of this name is present in a class
            (and it isn't the one inherited from `Serde`) this will be used for
            handling that class, rather than the default behavior.

        `custom_handlers`: A dictionary of custom handlers. These handlers take
            precedence over the default handlers.

        `lazy`: Whether to defer work until it's actually needed. This can
            improve performance, but can also lead to more surprising errors.

        `python_attribute_name_to_doc_name`: A function that converts the name of a
            field as it would be named in Python, to what it should be called in
            the serialized format.

        `python_class_name_to_doc_name`: A function that converts the name of a
            class as it would be named in Python, to what it should be called
            in the serialized format.

        `python_enum_name_to_doc_name`: A function that converts the name of an
            enumeration as it would be named in Python, to what it should be
            called in the serialized format.
        """

        self._context = context

        self._override_method_name = override_method_name
        self._user_provided_handlers = user_provided_handlers
        self._lazy = lazy

        self._python_attribute_name_to_doc_name = python_attribute_name_to_doc_name
        self._python_class_name_to_doc_name = python_class_name_to_doc_name
        self._python_enum_name_to_doc_name = python_enum_name_to_doc_name

        # Build a combined dictionary of handler functions
        self._all_handler_builders = eager_class_handler_builders.copy()

        if lazy:
            self._all_handler_builders.update(lazy_class_handler_builders)

        # All previously created and now cached handlers
        self._handler_cache: dict[type_hint.TypeHint, InternalHandler] = {}

        # This is used by the lazy wrapper to cache field information
        self._field_map_cache: dict[
            t.Type, dict[str, tuple[str, type_hint.TypeHint]]
        ] = {}

    @abstractmethod
    def _build_attribute_by_attribute_class_handler(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        type_key: type_hint.TypeHint,
    ) -> str:
        """
        Builds a handler for generic classes that will be handled
        field-by-field. To be implemented by subclasses.
        """
        raise NotImplementedError()

    @abstractmethod
    def _build_flag_enum_handler(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        as_type: type_hint.TypeHint,
    ) -> str:
        """
        Builds a handler for flag enums. To be implemented by subclasses.
        """
        raise NotImplementedError()

    @abstractmethod
    def _build_enum_handler(
        self,
        gen: codegen.Codegen,
        input_variable_name: str,
        as_type: type_hint.TypeHint,
    ) -> str:
        """
        Builds a handler for enums. To be implemented by subclasses.
        """
        raise NotImplementedError()

    def _get_handler(
        self,
        as_type: type_hint.TypeHint,
    ) -> InternalHandler:
        """
        Given a type key, return a function for converting values of that type
        key.

        If a user-provided handler exists, it is returned. Otherwise, if a
        cached handler exists, that is used. Finally, if neither is available,
        a new converter will be created, cached and returned.
        """
        # If a handler for this type key has already been cached, use that. This
        # also takes care of user-provided handlers.
        try:
            return self._handler_cache[as_type]
        except KeyError:
            pass

        # If the user has provided a handler for this type, use that
        try:
            return self._user_provided_handlers[as_type.origin]
        except KeyError:
            pass

        # If the class has a custom method defined for processing itself, use
        # that
        try:
            override_method = getattr(as_type.origin, self._override_method_name)
        except AttributeError:
            pass
        else:
            return lambda _, value_in, as_type: override_method(
                value_in,
                self._context,
                as_type.as_python(),
            )

        # Build a fresh handler
        handler_builder = self._get_handler_builder(as_type)
        handler = self._create_handler_from_handler_builder(handler_builder, as_type)

        # Cache it for later
        self._handler_cache[as_type] = handler
        return handler

    def _get_handler_builder(
        self,
        as_type: type_hint.TypeHint,
    ) -> HandlerBuilder:
        """
        Given a type key, return a function capable of building a handler for it.
        """
        # Was a custom handler provided for this type?
        try:
            override_method = self._user_provided_handlers[as_type.origin]
        except KeyError:
            pass
        else:
            return self._create_handler_builder_from_internal_handler(
                lambda serde, value, as_type: override_method(serde, value, as_type)
            )

        # If the class has a custom method defined for processing itself, use
        # that
        try:
            override_method = getattr(as_type.origin, self._override_method_name)
        except AttributeError:
            pass
        else:
            return self._create_handler_builder_from_internal_handler(
                lambda serde, value, as_type: override_method(serde, value, as_type)
            )

        # Is a builder registered with this cache?
        try:
            return self._all_handler_builders[as_type.origin]
        except KeyError:
            pass

        # Some sort of class
        assert inspect.isclass(as_type.origin), as_type

        # Is the class a flag enum?
        if issubclass(as_type.origin, enum.Flag):
            return type(self)._build_flag_enum_handler  # type: ignore

        # Is the class an enum?
        if issubclass(as_type.origin, enum.Enum):
            return type(self)._build_enum_handler  # type: ignore

        # Since nothing better was found, build a field-by-field handler
        return type(self)._build_attribute_by_attribute_class_handler  # type: ignore

    def _write_single_handler(
        self,
        gen: codegen.Codegen,
        input_variable_name,
        as_type: type_hint.TypeHint,
    ) -> str:
        """
        Write the code necessary to convert a single value of a given type.

        Returns a a short code snippet that can be used to retrieve the result.
        This is usually the name of a variable, but can also be some other
        **fast**, **pure** code, like `some_list[1]`.
        """
        # Get the handler builder for the subtype
        handler_builder = self._get_handler_builder(as_type)

        # Write it
        return handler_builder(
            self,
            gen,
            input_variable_name,
            as_type,
        )

    def _create_handler_builder_from_internal_handler(
        self,
        handler: InternalHandler,
    ) -> HandlerBuilder:
        """
        Given a handler, create a handler builder that will call that handler
        when the generated code is executed.
        """

        def handler_based_handler_builder(
            serde: SerdeCache,
            gen: codegen.Codegen,
            input_variable_name: str,
            as_type: type_hint.TypeHint,
        ) -> str:
            result_var = gen.get_new_variable()

            handler_var = gen.get_new_variable()
            serde_var = gen.get_new_variable()
            as_type_var = gen.get_new_variable()

            gen.expose_value(handler_var, handler)
            gen.expose_value(serde_var, serde)
            gen.expose_value(as_type_var, as_type)

            gen.write(
                f"{result_var} = {handler_var}({serde_var}, {input_variable_name}, {as_type_var})",
            )
            return result_var

        return handler_based_handler_builder

    def _create_handler_from_handler_builder(
        self,
        handler_builder: HandlerBuilder,
        as_type: type_hint.TypeHint,
    ) -> InternalHandler:
        """
        Create a new handler for the given type, based on the given handler
        builder.
        """
        # Get the code needed to convert a single value
        gen = self._write_code_from_handler_builder(
            handler_builder,
            as_type,
        )

        # Evaluate the result to obtain a function. The function may depend on
        # other functions, so those must be provided in the same scope.
        #
        # Start out preparing the scope
        scope: dict[str, t.Any] = {
            "SerdeError": SerdeError,
        }

        # Expose all requested handlers
        for (
            external_as_value,
            external_variable_name,
        ) in gen.external_processors():
            # Don't run in circles!
            if external_as_value == as_type:
                raise NotImplementedError(
                    f"TODO: Processing `{as_type}` depends on itself. This is not yet implemented."
                )

            scope[external_variable_name] = self._get_handler(external_as_value)

        # Expose values that were explicitly requested
        for exposed_name, exposed_value in gen.exposed_values():
            try:
                old_export = scope[exposed_name]
            except KeyError:
                pass
            else:
                assert (
                    old_export is exposed_value
                ), f"Clashing exports for `{exposed_name}`: {old_export!r} vs {exposed_value!r}"

            scope[exposed_name] = exposed_value

        # Evaluate generated code
        exec(gen.resulting_code(), scope)

        # Retrieve the handler function from the namespace
        return scope["handler"]

    def _write_code_from_handler_builder(
        self,
        handler_builder: HandlerBuilder,
        as_type: type_hint.TypeHint,
    ) -> codegen.Codegen:
        """
        Writes the code needed to convert a single value of a given type.
        Returns the code generator containing the code.
        """
        # Create a new code generator
        gen = codegen.Codegen()

        # Write a function header
        gen.write(
            "def handler(",
            "    serde,",
            "    value_in,",
            "    as_type,",
            "):",
        )

        # Let the handler write the main code
        gen.indentation_level = 1
        result_variable_name = self._write_single_handler(
            gen,
            "value_in",
            as_type,
        )
        assert gen.indentation_level == 1, gen.indentation_level

        # Make sure the function returns its result
        gen.newline()
        gen.write(f"return {result_variable_name}")

        return gen
