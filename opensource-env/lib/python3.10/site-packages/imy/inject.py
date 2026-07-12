"""
A very simple dependency injection system, in pure Python.

To use this, create an `Injector` instance, and bind factory functions to it.
Each factory may depend on types provided by other factories, and returns a
value, which is then stored in the injector.

When a value is requested from the injector, it will either return an existing
value if one is already available, or call the appropriate factory function(s)
to create it.

For convenience, a global injector is also provided, which can be accessed using
global functions such as `get` and `bind`.
"""

from __future__ import annotations

import inspect
import io
import typing as t

import introspection.typing
import typing_extensions as te

__all__ = [
    "DependencyCycleError",
    "Injector",
    "get",
    "set",
    "bind",
]

T = t.TypeVar("T")
P = te.ParamSpec("P")
R = t.TypeVar("R")


def _key_from_type_annotation(
    annotation: t.Any,
    forward_ref_context: str,
) -> t.Type:
    """
    Given a type annotation, return the type that should be used as a key.
    """
    info = introspection.typing.TypeInfo(
        annotation,
        forward_ref_context=forward_ref_context,
    )

    if info.type is None:
        raise ValueError("`None` cannot be used as a key.")

    assert inspect.isclass(info.type), (annotation, info.type)

    return info.type  # type: ignore


def _key_from_type(parameter: t.Type) -> t.Type:
    """
    Given a type as would be passed into a function (like __getitem__), return
    the type that should be used as a key.

    This is in contrast to a type annotation, which may contain strings, forward
    references, etc.
    """
    origin = t.get_origin(parameter)
    key = parameter if origin is None else parameter

    assert inspect.isclass(key), (parameter, key)

    return key


class DependencyCycleError(Exception):
    def __init__(self, sequence: t.Sequence[t.Type]) -> None:
        super().__init__()
        self._sequence = sequence

    def __str__(self) -> str:
        f = io.StringIO()

        f.write(f"<{self.__class__.__name__} ")
        f.write(" -> ".join(key.__name__ for key in self._sequence))
        f.write(">")

        return f.getvalue()


def _parse_factory(factory: t.Callable) -> tuple[list[t.Type], t.Type]:
    """
    Given a factory function, return a tuple containing the set of types it
    depends on and the type of item generated. The types are extracted from the
    factory's signature and order is preserved.
    """
    signature = inspect.signature(factory)

    # TODO: What if the factory uses kwargs?

    # Parameters
    parameter_types: list[t.Type] = []

    for parameter in signature.parameters.values():
        # Make sure the parameter has a type annotation
        if parameter.annotation is parameter.empty:
            raise ValueError(
                f"All parameters of factory functions need to have type annotations. `{parameter.name}` is missing one."
            )

        # Return type
        parameter_types.append(
            _key_from_type_annotation(
                parameter.annotation,
                factory.__module__,
            )
        )

    # Return type
    return_type = signature.return_annotation

    if return_type is signature.empty:
        raise ValueError("Factory functions need to have a return type annotation.")

    return_type_key = _key_from_type_annotation(
        return_type,
        factory.__module__,
    )

    # Done
    return parameter_types, return_type_key


class Injector:
    """
    TODO

    Note on generic keys (e.g. "list[int]"): Factory functions may use arbitrarily
    complex type annotations, however only the base type is used as a key. This
    means that even though a `list[int]` may be attached, during retrieval,
    `list[str]` will return the same, in this case incorrect, instance.

    This is a compromise to keep the system simple and fast, since hashing
    recursive types would be slow and is rarely useful anyway.
    """

    def __init__(
        self,
        *,
        items: t.Iterable[t.Any] = [],
    ) -> None:
        # Keeps track of all components currently attached to the injector
        self._components: dict[t.Type, t.Any] = {type(item): item for item in items}

        # Factories can be used to create items if they are not already
        # available in the injector. Each factory may depend on any number of
        # other items and returns the newly created item.
        self._factories: dict[t.Type, tuple[list[t.Type], t.Callable]] = {}

    def _get(
        self,
        raw_key: t.Type[T],
        *,
        in_flight: list[t.Type],
    ) -> T:
        """
        Helper function for `__getitem__`.
        """
        # Get the actual key to use
        key = _key_from_type(raw_key)

        # If the item is already available in this injector, just return it
        try:
            return self._components[key]
        except KeyError:
            pass

        # If an item of this type is currently being constructed, there's a
        # dependency cycle. Report it.
        if key in in_flight:
            raise DependencyCycleError(in_flight + [key])

        # Try to find a factory that can create the item
        try:
            factory_param_types, factory = self._factories[key]
        except KeyError:
            raise KeyError(raw_key)

        # Get all of the factory's dependencies
        factory_params: list[t.Any] = []

        for param_type in factory_param_types:
            factory_params.append(
                self._get(
                    param_type,
                    in_flight=in_flight + [key],
                )
            )

        # Create the item, register it and return
        item = factory(*factory_params)
        self._components[key] = item

        return item

    def __getitem__(self, key: t.Type[T]) -> T:
        """
        Given an item type, return the component of that type.

        ## Raises

        `KeyError`: If no item of the given type is available in this injector.

        `DependencyCycleError`: If the item cannot be constructed due to a
            dependency cycle.
        """
        # Delegate to the helper function
        return self._get(
            key,
            in_flight=[],
        )

    def __setitem__(self, item_type: t.Type[T], item: T) -> None:
        """
        Adds the given item to the injector. If the item is already present, it
        will be replaced.

        ## Raises

        `ValueError`: If the item is not an instance of the given type.
        """
        # Get the actual key to use
        key = _key_from_type(item_type)

        # Make sure the item is of the correct type
        if not isinstance(item, key):
            raise ValueError(
                f"Item has to be of type `{item_type}`, not `{type(item)}`"
            )

        # Add the item to the injector
        self._components[key] = item

    def bind(
        self,
        as_type: t.Type | None = None,
    ) -> t.Callable[[t.Callable[P, R]], t.Callable[P, R]]:
        """
        Adds the decorated function to the injector as a factory. The function's
        result must be in instance of the given type or subclass thereof.

        ## Raises

        `ValueError`: If the function's return type is not a subclass of the given
            type.

        `TypeError`: If there is already a factory for the type.
        """

        def decorator(func: t.Callable[P, R]) -> t.Callable[P, R]:
            # Parse the factory
            param_keys, return_key = _parse_factory(func)

            if as_type is None:
                key_type = return_key
            else:
                key_type = _key_from_type(as_type)

                # Make sure the factory indeed returns the correct type
                if not issubclass(return_key, key_type):
                    raise ValueError(
                        f"The factory has to return values of type `{key_type}` (or any subclass), not `{return_key}`"
                    )

            # Make sure there isn't already a factory for this type
            if key_type in self._factories:
                raise TypeError(
                    f"There is already a factory for type `{key_type}`. Only one factory per type is allowed."
                )

            # Register the factory
            self._factories[key_type] = (param_keys, func)
            return func

        return decorator

    def clear(self) -> None:
        """
        Removes any previously added components and factories from the injector.
        """
        self._components.clear()
        self._factories.clear()


# Expose a global injector
GLOBAL_INJECTOR = Injector()

get = GLOBAL_INJECTOR.__getitem__
set = GLOBAL_INJECTOR.__setitem__
bind = GLOBAL_INJECTOR.bind
clear = GLOBAL_INJECTOR.clear
