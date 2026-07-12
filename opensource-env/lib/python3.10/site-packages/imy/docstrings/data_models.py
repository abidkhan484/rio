from __future__ import annotations

import abc
import dataclasses
import types
import typing as t

import introspection.types
import introspection.typing
import typing_extensions as te

from ..deprecations import Deprecation
from . import parsers

__all__ = [
    "Unset",
    "UNSET",
    "Sentinel",
    "SENTINEL",
    "CommonMetadata",
    "Deprecation",
    "Docstring",
    "ModuleDocs",
    "ParameterDocs",
    "FunctionDocs",
    "AttributeDocs",
    "ClassDocs",
    "PropertyDocs",
]


AnyDocs = t.Union[
    "ModuleDocs",
    "ClassDocs",
    "FunctionDocs",
    "PropertyDocs",
    "AttributeDocs",
    "ParameterDocs",
]


class Unset:
    pass


UNSET = Unset()


class Sentinel:
    pass


SENTINEL = Sentinel()


@dataclasses.dataclass
class CommonMetadata:
    """
    Some metadata such as whether an object is public or not is shared between
    different types of objects. This class is used to hold that metadata.
    """

    # Whether the object is meant to be used by users of the library, or if it's
    # an internal implementation detail.
    public: bool = True

    # If `True`, this object is not yet ready for public use. Its API may change
    # between even patch releases.
    experimental: bool = False

    # The version when this object was first added.
    added_in_version: str | None = None

    # Contains all `key: value` pairs that don't correspond to known fields
    extras: dict[str, str] = dataclasses.field(default_factory=dict)

    @staticmethod
    def _parse_bool(value: str) -> bool:
        """
        Attempts to parse a boolean value from metadata.

        ## Raises

        `ValueError`: If the key is invalid.
        """
        # Postprocess the value
        if isinstance(value, str):
            value = value.strip()

        # Recognized strings
        if value == "True":
            return True

        if value == "False":
            return False

        # Invalid value
        raise ValueError(f"Cannot parse {value!r} as a boolean")

    @staticmethod
    def _parse_literal(
        metadata: dict[str, str],
        key_name: str,
        options: t.Set[str],
        default_value: str | None,
    ) -> str:
        """
        Attempts to parse a literal value from metadata.

        ## Raises

        `ValueError`: If the key is missing or invalid.
        """

        # Try to get the value
        try:
            raw = metadata[key_name]
        except KeyError:
            # No value provided
            if default_value is None:
                raise ValueError(f"Missing value for `{key_name}` in metadata")

            return default_value

        # Postprocess the value
        if isinstance(raw, str):
            raw = raw.strip()

        # Check if the value is valid
        if raw not in options:
            raise ValueError(f'Invalid value for `{key_name}` in metadata: "{raw}"')

        return raw

    @classmethod
    def from_dictionary(cls, metadata: dict[str, t.Any]) -> te.Self:
        """
        Parses a `CommonMetadata` object from a dictionary. This is useful for
        parsing metadata from a docstring key section.
        """

        kwargs = {}
        extras = {}

        type_hints = t.get_type_hints(cls)

        for key, value in metadata.items():
            try:
                annotation = type_hints[key]
            except KeyError:
                # Unknown field
                extras[key] = value
                continue

            try:
                if annotation is bool:
                    parsed_value = cls._parse_bool(value)
                elif annotation is str:
                    parsed_value = value
                else:
                    raise NotImplementedError(
                        f"Can't parse values of type {annotation} yet"
                    )
            except ValueError:
                raise ValueError(f"Invalid value for {key!r}: {value!r}")

            kwargs[key] = parsed_value

        # Construct the result
        return cls(**kwargs, extras=extras)


@dataclasses.dataclass
class FunctionMetadata(CommonMetadata):
    decorator: bool = False


@dataclasses.dataclass
class ClassMetadata(CommonMetadata):
    pass


@dataclasses.dataclass
class ModuleMetadata(CommonMetadata):
    pass


@dataclasses.dataclass
class PropertyMetadata(CommonMetadata):
    @staticmethod
    def from_function_metadata(
        function_metadata: FunctionMetadata,
    ) -> PropertyMetadata:
        return PropertyMetadata(
            public=function_metadata.public,
            experimental=function_metadata.experimental,
            added_in_version=function_metadata.added_in_version,
            extras=function_metadata.extras.copy(),
        )


@dataclasses.dataclass
class Docstring:
    """
    A generic docstring object.

    Docstrings are split into multiple sections: The **summary** is a brief,
    one-line description of the object. This is intended to be displayed right
    next to the object's name in a list of objects for example.

    The **details** section is a more in-depth explanation of the object. This
    may span multiple paragraphs and gives an explanation of the object

    Finally, **key_sections** are sections which consist entirely of `key:
    value` pairs. These can be used for raised exceptions, parameters, and
    similar.
    """

    summary: str | None
    details: str | None

    key_sections: dict[str, dict[str, str]]

    @staticmethod
    def from_string(
        docstring: str,
        *,
        key_sections: t.Iterable[str],
    ) -> Docstring:
        return parsers.parse_docstring(
            docstring,
            key_sections=key_sections,
        )


DirectChildrenType = t.TypeVar("DirectChildrenType", bound="_Docs")
IndirectChildrenType = t.TypeVar("IndirectChildrenType", bound="_Docs")
OwnerType = t.TypeVar("OwnerType", bound="_Docs")
ObjectType = t.TypeVar("ObjectType")


@dataclasses.dataclass
class _Docs(abc.ABC, t.Generic[OwnerType, DirectChildrenType, IndirectChildrenType]):
    """
    `_Docs[OwnerType, DirectChildrenType, IndirectChildrenType]`

    Base class for all Docs.
    """

    # These two attributes contain the *public* name/location of this object,
    # *not* the location where it was defined. For example, the `owner` of
    # `requests.Session` would be the `requests` module, even though that class
    # is defined in the `requests.session` sub-module.
    owner: OwnerType | None = dataclasses.field(repr=False)
    name: str

    deprecations: list[Deprecation]

    @t.overload
    def iter_children(
        self,
        *,
        recursive: t.Literal[False],
        include_self: t.Literal[False] = False,
    ) -> t.Iterable[DirectChildrenType]: ...

    @t.overload
    def iter_children(
        self,
        *,
        recursive: t.Literal[True],
        include_self: t.Literal[False] = False,
    ) -> t.Iterable[DirectChildrenType | IndirectChildrenType]: ...

    @t.overload
    def iter_children(
        self,
        *,
        recursive: t.Literal[False],
        include_self: t.Literal[True],
    ) -> t.Iterable[te.Self | DirectChildrenType]: ...

    @t.overload
    def iter_children(
        self,
        *,
        recursive: t.Literal[True],
        include_self: t.Literal[True],
    ) -> t.Iterable[te.Self | DirectChildrenType | IndirectChildrenType]: ...

    def iter_children(
        self, *, recursive: bool, include_self: bool = False
    ) -> t.Iterable[te.Self | DirectChildrenType | IndirectChildrenType]:
        """
        Yields all child docs of this docs object. (For example, a
        `FunctionDocs` will yield its `ParameterDocs`.)
        """

        if include_self:
            yield self

        yield from self._iter_children(recursive=recursive)

    @abc.abstractmethod
    def _iter_children(
        self, *, recursive: bool
    ) -> t.Iterable[DirectChildrenType | IndirectChildrenType]:
        raise NotImplementedError

    @abc.abstractmethod
    def transform_docstrings(self, transform: t.Callable[[str], str]) -> None:
        """
        Applies a transformation function to all "docstrings" of this docs
        object. (This is useful because some docs have a `description`, while
        others have a `summary` and `details`.)
        """
        raise NotImplementedError


@dataclasses.dataclass
class _SummaryAndDetailsMixin:
    summary: str | None
    details: str | None

    def transform_docstrings(self, transform: t.Callable[[str], str]) -> None:
        if self.summary is not None:
            self.summary = transform(self.summary)

        if self.details is not None:
            self.details = transform(self.details)


@dataclasses.dataclass
class _DescriptionMixin:
    description: str | None

    def transform_docstrings(self, transform: t.Callable[[str], str]) -> None:
        if self.description is not None:
            self.description = transform(self.description)


class _DocsWithoutChildren(_Docs[OwnerType, te.Never, te.Never]):
    def _iter_children(self, *, recursive: bool) -> t.Iterable[te.Never]:
        return ()


@dataclasses.dataclass
class _ObjectDocs(
    _SummaryAndDetailsMixin,
    _Docs[OwnerType, DirectChildrenType, IndirectChildrenType],
    t.Generic[OwnerType, DirectChildrenType, IndirectChildrenType, ObjectType],
):
    """
    `_ObjectDocs[OwnerType, DirectChildrenType, IndirectChildrenType, ObjectType]`

    Base class for everything that's an object, i.e. exists at runtime.
    (i.e. modules, classes, functions, properties, ...)
    """

    object: ObjectType

    @property
    def full_name(self) -> str:
        """
        The "full name" of this object, in other words, how users are expected
        to access it. (For example, "requests.Session")
        """
        parts = list[str]()

        obj = self
        while obj is not None:
            parts.append(obj.name)
            obj = obj.owner

        parts.reverse()
        return ".".join(parts)


@dataclasses.dataclass
class _ScopeDocs(
    _ObjectDocs[OwnerType, DirectChildrenType, IndirectChildrenType, ObjectType]
):
    """
    `_ScopeDocs[OwnerType, DirectChildrenType, IndirectChildrenType, ObjectType]`

    Base class for objects that store other objects as attributes, like modules
    and classes.
    """

    members: dict[str, DirectChildrenType] = dataclasses.field(repr=False)

    def add_member(
        self,
        member: DirectChildrenType,
        *,
        name: str | None = None,
    ) -> None:
        """
        Adds the given object as a member. You can use this method to add
        objects that were incorrectly assumed to be private.
        """
        if name is None:
            name = member.name

        self.members[name] = member

    def _iter_children(
        self, *, recursive: bool
    ) -> t.Iterable[DirectChildrenType | IndirectChildrenType]:
        for member in self.members.values():
            yield member

            if recursive:
                yield from member._iter_children(recursive=True)  # type: ignore


ModuleOwnerType: te.TypeAlias = "ModuleDocs"
ModuleDirectChildrenType = t.Union["ModuleDocs", "ClassDocs", "FunctionDocs"]
ModuleIndirectChildrenType = t.Union["PropertyDocs", "AttributeDocs", "ParameterDocs"]
ModuleObjectType = types.ModuleType


@dataclasses.dataclass
class ModuleDocs(
    _ScopeDocs[
        ModuleOwnerType,
        ModuleDirectChildrenType,
        ModuleIndirectChildrenType,
        ModuleObjectType,
    ]
):
    metadata: ModuleMetadata

    @staticmethod
    def from_module(
        module: types.ModuleType,
        *,
        owner: ModuleDocs | None = None,
    ) -> ModuleDocs:
        """
        Parses a `ModuleDocs` object from a module object.
        """
        return parsers.parse_module(module, owner=owner)

    def _iter_children(
        self, *, recursive: bool
    ) -> t.Iterable[ModuleDirectChildrenType | ModuleIndirectChildrenType]:
        for member in self.members.values():
            yield member

            if recursive:
                yield from member._iter_children(recursive=True)

    def add_member(
        self,
        member: ModuleObjectType
        | ClassObjectType
        | FunctionObjectType
        | ModuleDirectChildrenType,
        *,
        name: str | None = None,
    ) -> None:
        if not isinstance(member, _Docs):
            member = parsers.parse(member, owner=self)

        return super().add_member(member, name=name)


FunctionOwnerType = t.Union["ModuleDocs", "ClassDocs", "PropertyDocs"]
FunctionDirectChildrenType: te.TypeAlias = "ParameterDocs"
FunctionIndirectChildrenType = te.Never
FunctionObjectType: te.TypeAlias = t.Callable


@dataclasses.dataclass
class FunctionDocs(
    _ObjectDocs[
        FunctionOwnerType,
        FunctionDirectChildrenType,
        FunctionIndirectChildrenType,
        FunctionObjectType,
    ]
):
    parameters: dict[str, ParameterDocs]
    return_type: introspection.types.TypeAnnotation | Unset
    synchronous: bool

    class_method: bool
    static_method: bool

    raises: list[tuple[str, str]]  # type, description

    metadata: FunctionMetadata

    @property
    def has_implicit_first_parameter(self) -> bool:
        """
        Returns `True` for instance methods, class methods, property getters and
        property setters.

        Note that this may incorrectly return `False` if `owner` is set to
        `None`.
        """
        if self.static_method:
            return False

        if self.class_method:
            return True

        return isinstance(self.owner, (ClassDocs, PropertyDocs))

    @staticmethod
    def from_function(
        func: FunctionObjectType,
        *,
        owner: FunctionOwnerType | None = None,
    ) -> FunctionDocs:
        """
        Parses a `FunctionDocs` object from a function or method. This takes
        both the function's docstring as well as its signature and type hints
        into account.
        """
        return parsers.parse_function(func, owner=owner)

    def _iter_children(
        self, *, recursive: bool
    ) -> t.Iterable[FunctionDirectChildrenType | FunctionIndirectChildrenType]:
        yield from self.parameters.values()


@dataclasses.dataclass
class ParameterDocs(_DescriptionMixin, _DocsWithoutChildren["FunctionDocs"]):
    type: introspection.types.TypeAnnotation | Unset
    default: object | Unset

    kw_only: bool

    collect_positional: bool
    collect_keyword: bool


@dataclasses.dataclass
class AttributeDocs(_DescriptionMixin, _DocsWithoutChildren["ClassDocs"]):
    type: introspection.types.TypeAnnotation | Unset
    default: object | Unset


PropertyOwnerType: te.TypeAlias = "ClassDocs"
PropertyDirectChildrenType: te.TypeAlias = "FunctionDocs"
PropertyIndirectChildrenType = t.Union[
    FunctionDirectChildrenType, FunctionIndirectChildrenType
]
PropertyObjectType = property


@dataclasses.dataclass
class PropertyDocs(
    _ObjectDocs[
        PropertyOwnerType,
        PropertyDirectChildrenType,
        PropertyIndirectChildrenType,
        PropertyObjectType,
    ]
):
    getter: FunctionDocs
    setter: FunctionDocs | None

    metadata: PropertyMetadata

    @staticmethod
    def from_property(
        prop: PropertyObjectType,
        *,
        owner: PropertyOwnerType | None = None,
    ) -> PropertyDocs:
        return parsers.parse_property(prop, owner=owner)

    def _iter_children(
        self, *, recursive: bool
    ) -> t.Iterable[PropertyDirectChildrenType | PropertyIndirectChildrenType]:
        yield self.getter
        if recursive:
            yield from self.getter._iter_children(recursive=True)

        if self.setter is not None:
            yield self.setter
            if recursive:
                yield from self.setter._iter_children(recursive=True)


ClassOwnerType: te.TypeAlias = "ModuleDocs"
ClassDirectChildrenType = t.Union["AttributeDocs", "PropertyDocs", "FunctionDocs"]
ClassIndirectChildrenType = t.Union[
    PropertyDirectChildrenType,
    PropertyIndirectChildrenType,
    FunctionDirectChildrenType,
    FunctionIndirectChildrenType,
]
ClassObjectType = type


@dataclasses.dataclass
class ClassDocs(
    _ScopeDocs[
        ClassOwnerType,
        ClassDirectChildrenType,
        ClassIndirectChildrenType,
        ClassObjectType,
    ]
):
    attributes: dict[str, AttributeDocs]

    metadata: ClassMetadata

    @property
    def properties(self) -> t.Mapping[str, PropertyDocs]:
        return {
            name: docs
            for name, docs in self.members.items()
            if isinstance(docs, PropertyDocs)
        }

    @property
    def functions(self) -> t.Mapping[str, FunctionDocs]:
        return {
            name: docs
            for name, docs in self.members.items()
            if isinstance(docs, FunctionDocs)
        }

    @property
    def init_method(self) -> FunctionDocs | None:
        """
        Returns the `FunctionDocs` for this class's `__init__` method, if it has
        one.
        """
        try:
            init_method = self.members["__init__"]
        except KeyError:
            pass
        else:
            if isinstance(init_method, FunctionDocs):
                return init_method

        return None

    @staticmethod
    def from_class(
        typ: ClassObjectType,
        *,
        owner: ClassOwnerType | None = None,
    ) -> ClassDocs:
        """
        Parses a `ClassDocs` object from a class. This takes both the class's
        docstring as well as its methods and attributes into account.
        """
        return parsers.parse_class(typ, owner=owner)

    def _iter_children(
        self, *, recursive: bool
    ) -> t.Iterable[ClassDirectChildrenType | ClassIndirectChildrenType]:
        yield from super()._iter_children(recursive=recursive)
        yield from self.attributes.values()

    def add_member(
        self,
        member: FunctionObjectType | PropertyObjectType | ClassDirectChildrenType,
        *,
        name: str | None = None,
    ) -> None:
        if not isinstance(member, _Docs):
            member = parsers.parse(member, owner=self)

        return super().add_member(member, name=name)
