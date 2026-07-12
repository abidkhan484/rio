import io
import typing as t

from . import type_hint


class Codegen:
    def __init__(self) -> None:
        # How far to indent all lines of code
        self._indentation_level = 0
        self._indentation_str = ""

        # Stores the intermediate code
        self._stream = io.StringIO()

        # Counter for generating unique variables
        self._next_free_variable_count = 0

        # Ser-/Deserialization of one class may have to call other
        # ser-/deserializers (or this one). This attribute keeps track of which other
        # deserializers are needed. The resulting code expects them to be
        # available as `external_0`, `external_1`, etc.
        self._external_processors: list[type_hint.TypeHint] = []

        # Manually listed values that need to be exposed in the scope, and under
        # which name
        self._exposed_values: dict[str, t.Any] = {}

    @property
    def indentation_level(self) -> int:
        return self._indentation_level

    @indentation_level.setter
    def indentation_level(self, value: int) -> None:
        self._indentation_level = value
        self._indentation_str = "    " * value

    def newline(self) -> None:
        """
        Writes a newline to the code stream.
        """
        self._stream.write("\n")

    def write(self, *lines: str) -> None:
        """
        Writes the given lines to the code stream. Each line is automatically
        prefixed with the current indentation level and terminated with a
        newline.
        """

        for line in lines:
            self._stream.write(self._indentation_str + line + "\n")

    def resulting_code(self) -> str:
        """
        Returns all code that has been written to this generator, as a single
        string.
        """
        return self._stream.getvalue()

    def get_new_variable(self) -> str:
        """
        Returns a new unique variable name.
        """
        self._next_free_variable_count += 1
        return f"var_{self._next_free_variable_count}"

    def get_external_processor_name(self, as_type: type_hint.TypeHint) -> str:
        """
        Gets the Python name under which the handler for the given type key
        will be available at runtime.
        """
        # Check if the processor is already registered
        try:
            return f"external_{self._external_processors.index(as_type) + 1}"
        except ValueError:
            pass

        # Register the processor
        self._external_processors.append(as_type)
        return f"external_{len(self._external_processors)-1}"

    def external_processors(self) -> t.Iterable[tuple[type_hint.TypeHint, str]]:
        """
        Returns all external processors that this code depends on, alongside the
        name under which they are expected to be available.
        """
        for ii, processor in enumerate(self._external_processors):
            yield processor, f"external_{ii }"

    def expose_value(
        self,
        name: str,
        value: t.Any,
    ) -> None:
        """
        Signals to the creator of the code generator that the given value should
        be exposed in the scope of the generated code, under the given name.
        """
        self._exposed_values[name] = value

    def exposed_values(self) -> t.Iterable[tuple[str, t.Any]]:
        """
        Returns all values that have been exposed to the generated code.
        """
        return self._exposed_values.items()
