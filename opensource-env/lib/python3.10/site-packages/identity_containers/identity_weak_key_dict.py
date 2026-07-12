from __future__ import annotations

import collections.abc
import typing as t
import weakref

from .identity_dict import K, V

__all__ = ["IdentityWeakKeyDict"]


class IdentityWeakKeyDict(collections.abc.MutableMapping[K, V]):
    """
    Added in version 1.1.0.
    """

    def __init__(self, items: t.Mapping[K, V] | t.Iterable[tuple[K, V]] = ()):
        # Maps the IDs of the key to the corresponding value
        self._values: dict[int, V] = {}

        # We use weakrefs with a callback to get notified when a key dies.
        self._key_id_to_weakref: dict[int, weakref.ref[K]] = {}
        self._weakref_id_to_key_id: dict[int, int] = {}

        self.update(items)

    def _on_key_death(self, key_ref: weakref.ReferenceType[K]) -> None:
        key_id = self._weakref_id_to_key_id.pop(id(key_ref))
        del self._values[key_id]
        del self._key_id_to_weakref[key_id]

    def __getitem__(self, key: K) -> V:
        try:
            return self._values[id(key)]
        except KeyError:
            raise KeyError(key) from None

    def __setitem__(self, key: K, value: V) -> None:
        self._values[id(key)] = value

        key_ref = weakref.ref(key, self._on_key_death)
        self._key_id_to_weakref[id(key)] = key_ref
        self._weakref_id_to_key_id[id(key_ref)] = id(key)

    def __delitem__(self, key: K) -> None:
        try:
            del self._values[id(key)]
        except KeyError:
            raise KeyError(key) from None

        key_ref = self._key_id_to_weakref.pop(id(key))
        del self._weakref_id_to_key_id[id(key_ref)]

    def __iter__(self) -> t.Iterator[K]:
        return iter([t.cast(K, key_ref()) for key_ref in self._key_id_to_weakref.values()])

    def __len__(self) -> int:
        return len(self._values)

    def _repr_items(self) -> str:
        return repr(list(self.items()))

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        items = self._repr_items()
        return f"{cls_name}({items})"
