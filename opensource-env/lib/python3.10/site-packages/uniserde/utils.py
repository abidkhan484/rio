from __future__ import annotations

import dataclasses
import inspect
import sys
import typing as t

from . import errors, type_hint

__all__ = [
    "as_child",
    "get_class_attributes_recursive",
]


T = t.TypeVar("T")


# Caches results of the `get_type_key` function to speed up lookups.
TYPE_KEY_CACHE: dict[t.Type, t.Type] = {}

# Track which classes are currently having their attributes parsed. This is used
# to detect recursive/self-referential types.
_CLASSES_BEING_PARSED: set[t.Type] = set()


def as_child(cls: t.Type[T]) -> t.Type[T]:
    """
    Marks the class to be serialized as one of its children. This will add an
    additional "type" field in the result, so the child can be deserialized
    properly.

    This decorator applies to children of the class as well, i.e. they will also
    be serialized with the "type" field.
    """
    assert inspect.isclass(cls), cls
    cls._uniserde_serialize_as_child_ = cls  # type: ignore
    return cls


def root_of_serialize_as_child(cls: t.Type) -> t.Type | None:
    """
    If the given class, or any of its parents, is marked to be serialized
    `@as_child`, returns the class that was marked. Otherwise, returns `None`.
    """
    assert inspect.isclass(cls), cls
    try:
        return cls._uniserde_serialize_as_child_  # type: ignore
    except AttributeError:
        return None


def all_subclasses(cls: t.Type, include_class: bool) -> t.Iterable[t.Type]:
    """
    Yields all classes directly or indirectly inheriting from `cls`. Does not
    perform any sort of cycle checks. If `include_class` is `True`, the class
    itself is also yielded.
    """

    if include_class:
        yield cls

    for subclass in cls.__subclasses__():
        yield from all_subclasses(subclass, True)


def _check_for_self_reference(hint: t.Any, cls: t.Type) -> bool:
    """
    Check if a type hint references a class that's currently being parsed.

    This is a shallow check - we only look at the immediate type and its
    direct generic arguments (e.g., list[T], Optional[T]), not nested generics.
    This is sufficient because the cycle will be detected when we try to
    parse the referenced class.
    """
    # Check the hint itself
    if inspect.isclass(hint) and hint in _CLASSES_BEING_PARSED:
        return True

    # Check generic type arguments (e.g., list[TreeNode], Optional[TreeNode])
    try:
        args = t.get_args(hint)
        if args:
            for arg in args:
                if inspect.isclass(arg) and arg in _CLASSES_BEING_PARSED:
                    return True
    except (AttributeError, TypeError):
        pass

    return False


def _get_class_attributes_local(
    cls: t.Type,
    result: dict[str, type_hint.TypeHint],
) -> None:
    """
    Gets all annotated attributes in the given class, without considering any
    parent classes. Applies the same rules as `get_class_attributes_recursive`.

    Instead of returning a result, the attributes are added to the given
    dictionary. If the dictionary already contains an attribute, it is not
    overwritten.
    """
    assert inspect.isclass(cls), cls

    # Get all annotated attributes
    try:
        annotations = cls.__annotations__
    except AttributeError:
        return

    if not isinstance(annotations, dict):
        return

    # Process them individually
    global_ns = sys.modules[cls.__module__].__dict__
    local_ns = vars(cls)

    for name, hint in annotations.items():
        # Because we're going in method resolution order, any previous
        # definitions win
        if name in result:
            continue

        # Resolve string annotations
        if isinstance(hint, str):
            try:
                hint = eval(hint, global_ns, local_ns)
            except NameError:
                raise ValueError(
                    f"Could not resolve string annotation `{hint}` in {cls.__name__}.{name}. Are you missing an import?"
                )

        assert not isinstance(hint, str), repr(hint)

        # By convention, `dataclasses.KW_ONLY` is used as though it were a
        # type hint, but it's not actually valid for that.
        if hint is dataclasses.KW_ONLY:
            continue

        # Check for self-referential types
        if _check_for_self_reference(hint, cls):
            raise errors.SerdeError(
                f"Recursive type detected: {cls.__name__}.{name} contains itself, but self-referential types are not supported by `uniserde`. Consider using a custom serializer/deserializer or restructuring your data model."
            )

        # Store the result
        result[name] = type_hint.TypeHint(hint)


def get_class_attributes_recursive(cls: t.Type) -> dict[str, type_hint.TypeHint]:
    """
    Returns the names and types of all attributes in the given class, including
    inherited ones. Attributes are determined from type hints, with some custom
    logic applied:

    - fields annotated with `dataclasses.KW_ONLY` are silently dropped

    - New-style unions are converted to old-style (`types.UnionType` ->
      `t.Union`).
    """
    assert inspect.isclass(cls), cls

    # Track that we're parsing this class to detect recursive types
    _CLASSES_BEING_PARSED.add(cls)

    try:
        result: dict[str, type_hint.TypeHint] = {}

        for subcls in cls.__mro__:
            _get_class_attributes_local(subcls, result)

        return result

    # Always remove from tracking set, even if an error occurred
    finally:
        _CLASSES_BEING_PARSED.discard(cls)
