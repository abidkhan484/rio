from __future__ import annotations

import inspect
import types
import typing as t
import uuid
from datetime import datetime, timedelta

import typing_extensions as te

from .objectid_proxy import ObjectId


class TypeHint:
    """
    Represents a type hint with its origin and arguments.

    Unlike plain type hints these are easily comparable and support parsing
    themselves from string type hints.
    """

    def __init__(
        self,
        type_hint: t.Type | str,
        *,
        scope: dict[str, t.Any] | None = None,
    ) -> None:
        """
        Initialize the TypeHint instance.

        The origin and arguments are extracted from the given type hint. If any
        of the types are strings, they will be evaluated in the given scope.

        Some standardizations are performed on the type hint:

        - `Annotated[T, metadata...]` unwraps to `T`
        - `types.UnionType` and `typing_extensions` types are normalized to
          their `typing` module equivalents
        - `Union[T, None]` becomes `Optional[T]`

        ## Parameters

        `type_hint`: The type hint to be processed.

        ## Raises

        `TypeError`: If the type hint isn't supported by `uniserde` (e.g.
            `Callable`).

        `TypeError`: If one of the type hints was a string but no scope was
            provided.

        `TypeError`: If one of the type hints was a string and has raised an
            exception during evaluation.
        """
        # If the type hint is a string, evaluate it
        if isinstance(type_hint, str):
            if scope is None:
                raise TypeError(
                    "A scope must be provided to evaluate string type hints."
                )

            type_hint = TypeHint.evaluate_type_hint(type_hint, scope)

        # Get the origin and args
        self._origin: t.Type
        origin = t.get_origin(type_hint)
        args = t.get_args(type_hint)

        # Some built-in types like `str` or `int` are not recognized by
        # `get_origin`
        if origin is None:
            origin = type_hint

        # Perform standardizations
        #
        # Unwrap Annotated[T, metadata...] to T. Note that there is no need to
        # unpack in a loop here, because Python automatically flattens nested
        # Annotated types.
        if origin is t.Annotated:
            if args:
                type_hint = args[0]
                origin = t.get_origin(type_hint)
                args = t.get_args(type_hint)
                if origin is None:
                    origin = type_hint

        # Normalize the origin. Some conceptually identical types have multiple
        # conflicting implementations in different modules.
        origin = {
            te.Annotated: t.Annotated,
            te.Any: t.Any,
            te.Literal: t.Literal,
            te.Optional: t.Optional,
            te.Union: t.Union,
            types.UnionType: t.Union,
        }.get(origin, origin)

        # Convert Union[T, None] to Optional[T]
        if origin is t.Union and len(args) == 2 and type(None) in args:
            origin = t.Optional
            args = tuple(arg for arg in args if arg is not type(None))

        # Catch unsupported type hints
        is_user_class = inspect.isclass(origin) and origin.__module__ != "builtins"

        if (
            origin
            not in (
                bool,
                int,
                float,
                bytes,
                str,
                tuple,
                list,
                set,
                dict,
                t.Optional,
                datetime,
                timedelta,
                ObjectId,
                uuid.UUID,
                t.Any,
                t.Literal,
            )
            and not is_user_class
        ):
            raise TypeError(f"`{origin}` is not supported by `uniserde`.")

        # Single argument type hints
        if origin in (list, set, t.Optional):
            if len(args) != 1:
                raise TypeError(f"Expected one argument for `{origin}`, got {args!r}.")

        # Dict (the only dual argument type hint)
        elif origin is dict:
            if len(args) != 2:
                raise TypeError(f"Expected two arguments for `dict`, got {args!r}.")

            if args[0] not in (str, int):
                raise TypeError(
                    f"`dict` keys must be of type `str` or `int`, not {args[0]!r}."
                )

        # Any number of arguments type hints
        elif origin in (tuple, t.Literal):
            pass

        # Zero argument type hints
        elif args:
            raise TypeError(f"Unexpected arguments for `{origin}`: {args!r}")

        # Store the origin
        self._origin = origin  # type: ignore

        # Get the args
        self._args: tuple[TypeHint, ...]
        self._literal_args: tuple[str, ...]

        if self._origin is t.Literal:
            for arg in args:
                if not isinstance(arg, str):
                    raise TypeError(
                        f"`uniserde` currently only supports string literals, not `{type_hint}`."
                    )

            self._args = tuple()
            self._literal_args = args

        else:
            parsed_args: list[TypeHint] = []

            for arg in args:
                parsed_args.append(TypeHint(arg, scope=scope))

            self._args = tuple(parsed_args)
            self._literal_args = tuple()

    @staticmethod
    def evaluate_type_hint(
        type_hint_str: str,
        scope: dict[str, t.Any],
    ) -> t.Type:
        """
        Evaluate a string representation of a type hint.

        ## Raises

        `TypeError`: If the string could not be evaluated.
        """
        try:
            return eval(type_hint_str, scope)
        except Exception as e:
            raise TypeError(f"Could not evaluate string type hint: {e}")

    @property
    def origin(self) -> t.Type:
        """
        Return the origin of the type hint.
        """
        return self._origin

    @property
    def args(self) -> tuple[TypeHint, ...]:
        """
        Return the arguments of the type hint.
        """
        return self._args

    @property
    def literal_args(self) -> tuple[str, ...]:
        """
        Return the literal arguments of the type hint.
        """
        return self._literal_args

    def as_python(self) -> t.Type:
        """
        Returns the type hint as a Python type. For example a type hint with
        origin `list` and arguments `(TypeHint(int))` will return `List[int]`.
        """
        # If not a generic, just return the origin
        if not self._args and not self._literal_args:
            assert not self._args, (self._origin, self._args)
            assert not self._literal_args, (self._origin, self._literal_args)

            return self._origin

        # Special case: Literals
        if self._origin is t.Literal:
            args = self.literal_args
        else:
            args = [arg.as_python() for arg in self._args]

        # Pass in the arguments, or not?
        if len(args) == 0:
            return self._origin  # type: ignore

        if len(args) == 1:
            return self._origin[args[0]]  # type: ignore

        return self._origin[tuple(args)]  # type: ignore

    def __hash__(self) -> int:
        """
        Return the hash of the TypeHint instance.

        ## Returns

        An integer hash value.
        """
        return hash((self._origin, self._args))

    def __eq__(self, other: t.Any) -> bool:
        """
        Compare the TypeHint instance with another instance for equality.

        ## Parameters

        `other`: The other instance to compare with.

        ## Returns

        `True` if both instances are equal, `False` otherwise.
        """
        if not isinstance(other, TypeHint):
            return False

        return self._origin == other._origin and self._args == other._args

    def pretty_string(self) -> str:
        # Special case: Literals
        if self._origin is t.Literal:
            return f"Literal[{', '.join(self.literal_args)}]"

        # Type without arguments
        if not self._args:
            return self._origin.__name__

        # Type with arguments
        args = [arg.pretty_string() for arg in self._args]
        return f"{self._origin.__name__}[{', '.join(args)}]"

    def __repr__(self) -> str:
        return f"TypeHint({self.pretty_string()})"
