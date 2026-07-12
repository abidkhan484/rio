from __future__ import annotations

import typing as t

from .identity_dict import IdentityDict, K, V

__all__ = ["IdentityDefaultDict"]


class IdentityDefaultDict(IdentityDict[K, V]):
    def __init__(
        self,
        default_factory: t.Callable[[], V],
        items: t.Mapping[K, V] | t.Iterable[tuple[K, V]] = (),
        **kwargs: V,
    ):
        super().__init__(items, **kwargs)

        self._default_factory = default_factory

    def __getitem__(self, key: K) -> V:
        try:
            return super().__getitem__(key)
        except KeyError:
            value = self._default_factory()
            self[key] = value
            return value

    def __contains__(self, key: object) -> bool:
        try:
            super().__getitem__(key)  # type: ignore
            return True
        except KeyError:
            return False

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        items = self._repr_items()
        return f"{cls_name}({self._default_factory!r}, {items})"
