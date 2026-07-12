from __future__ import annotations

import collections.abc
import typing as t
import typing_extensions as te


__all__ = ["IdentitySet"]

T = t.TypeVar("T")
X = t.TypeVar("X")


class IdentitySet(collections.abc.MutableSet[T]):
    def __init__(self, items: t.Iterable[T] = ()):
        self._items: dict[int, T] = {}

        self.update(items)

    def __contains__(self, value: object) -> bool:
        return id(value) in self._items

    def __iter__(self) -> t.Iterator[T]:
        return iter(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def add(self, value: T) -> None:
        self._items[id(value)] = value

    def remove(self, value: T) -> None:
        try:
            self._items.pop(id(value))
        except KeyError:
            raise ValueError(value) from None

    def discard(self, value: T) -> None:
        self._items.pop(id(value), None)

    def clear(self) -> None:
        self._items.clear()

    def update(self, values: t.Iterable[T]) -> None:
        for value in values:
            self.add(value)

    def copy(self) -> te.Self:
        cls = type(self)
        return cls(self)

    def union(self, values: t.Iterable[X]) -> IdentitySet[T | X]:
        result = t.cast(IdentitySet["T | X"], self.copy())
        result.update(values)
        return result

    def __or__(self, other: t.Iterable[X]) -> IdentitySet[T | X]:
        return self.union(other)

    def __ior__(self, values: t.Iterable[T]) -> IdentitySet[T]:
        self.update(values)
        return self

    def intersection(self, values: t.Iterable[T]) -> IdentitySet[T]:
        cls = type(self)
        return cls(value for value in values if value in self)

    def __and__(self, other: t.Iterable[T]) -> IdentitySet[T]:
        return self.intersection(other)

    def intersection_update(self, values: t.Iterable[T]) -> None:
        self._items = {id(value): value for value in values if value in self}

    def __iand__(self, values: t.Iterable[T]) -> IdentitySet[T]:
        self.intersection_update(values)
        return self

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        items = ", ".join(map(repr, self))
        return f"{cls_name}([{items}])"
