from __future__ import annotations

import collections.abc
import typing as t


__all__ = ["IdentityDict"]


K = t.TypeVar("K")
V = t.TypeVar("V")


class IdentityDict(collections.abc.MutableMapping[K, V]):
    def __init__(self, items: t.Mapping[K, V] | t.Iterable[tuple[K, V]] = ()):
        # Maps the IDs of the key to the corresponding value
        self._values: dict[int, V] = {}

        # Keeps the keys alive so that their IDs don't get re-used
        self._keys: dict[int, K] = {}

        self.update(items)

    def __getitem__(self, key: K) -> V:
        try:
            return self._values[id(key)]
        except KeyError:
            raise KeyError(key) from None

    def __setitem__(self, key: K, value: V) -> None:
        self._values[id(key)] = value
        self._keys[id(key)] = key

    def __delitem__(self, key: K) -> None:
        try:
            del self._values[id(key)]
            del self._keys[id(key)]
        except KeyError:
            raise KeyError(key) from None

    def __iter__(self) -> t.Iterator[K]:
        return iter(self._keys.values())

    def __len__(self) -> int:
        return len(self._keys)

    def _repr_items(self) -> str:
        return repr(list(self.items()))

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        items = self._repr_items()
        return f"{cls_name}({items})"
