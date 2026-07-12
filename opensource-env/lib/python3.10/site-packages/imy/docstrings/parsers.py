from __future__ import annotations

import collections
import dataclasses
import enum
import inspect
import sys
import textwrap
import types
import typing as t
import warnings
from dataclasses import is_dataclass

import introspection
import introspection.types
import introspection.typing
from uniserde import Jsonable

from ..deprecations import deprecated_objects, deprecated_parameters
from . import data_models


def split_docstring_into_sections(docstring: str) -> tuple[str, dict[str, str]]:
    """
    Splits the given docstring into sections separated by markdown headings. The
    result is the part of the string before the first heading, and a dictionary
    mapping the heading names to the text of the sections ("the summary").

    If the docstring starts with a heading it will not create a separate section
    and the text of that section will be considered part of the summary.
    """
    # Drop the title if it exists
    if docstring.startswith("#") and not docstring.startswith("##"):
        docstring = docstring.split("\n", 1)[1]

    # Split the docstring into sections
    sections: dict[str, list[str]] = {}
    details: list[str] = []
    current_section: list[str] = details
    currently_inside_code_block: bool = False

    # Process the individual lines
    for line in docstring.splitlines():
        # Code block?
        if line.startswith("```"):
            currently_inside_code_block = not currently_inside_code_block
            current_section.append(line)

        # Section Header
        elif line.startswith("#") and not currently_inside_code_block:
            section_name = line.strip()
            current_section = sections.setdefault(section_name, [])

        # Nothing to see here
        else:
            current_section.append(line)

    # Post-process the sections
    def postprocess(section: list[str]) -> str:
        return "\n".join(section).strip()

    return postprocess(details), {
        name: postprocess(section) for name, section in sections.items()
    }


def parse_key_value_section(section_string: str) -> dict[str, str]:
    """
    Some docstring sections are formatted as a list of key-value pairs, such as
    this:

    ```
    key: A description of the key.
    `key_in_code`: A description of the key in code.
    ```

    (Note the optional backticks around the key - these are stripped if present)

    This function splits such a section into a dictionary of key-value pairs.
    """
    result_lines: dict[str, list[str]] = {}
    current_value: list[str] = []

    # Process the lines individually
    for raw_line in section_string.splitlines():
        # Strip the line and calculate the indentation
        strip_line = raw_line.lstrip()
        indent = len(raw_line) - len(strip_line)
        strip_line = strip_line.rstrip()

        # Continuation of the previous value
        if indent > 0 or not strip_line:
            current_value.append(raw_line)
            continue

        # New value?
        parts = strip_line.split(":", 1)

        # Kinda, but it's mistyped
        if len(parts) == 1:
            # TODO: Warn somehow?
            current_value.append(raw_line)
            continue

        # Yes, for real this time
        key, value = parts
        key = key.strip().strip("`").strip()
        value = value.lstrip()
        current_value = [value]
        result_lines[key] = current_value

    # Postprocess the values. The lines need to be joined and the values
    # dedented.
    result: dict[str, str] = {}

    for key, lines in result_lines.items():
        assert lines, (key, lines)

        # The first line has weird indendation, due to following the separator.
        # Strip it.
        value = lines[0].lstrip()

        # The remaining lines need to be dedented
        if len(lines) > 1:
            tail = "\n".join(lines[1:])
            tail = textwrap.dedent(tail)
            value = f"{value}\n{tail}"

        result[key] = value

    return result


def parse_details(details: str) -> tuple[str | None, str | None]:
    """
    Given the details part of a docstring, split it into summary and details.
    Either value may be Nonne if they are not present in the original string.
    """
    details = details.strip()

    # Split into summary & details
    lines = details.split("\n")

    short_lines: list[str] = []
    long_lines: list[str] = []
    cur_lines = short_lines

    for raw_line in lines:
        strip_line = raw_line.strip()

        cur_lines.append(raw_line)

        if not strip_line:
            cur_lines = long_lines

    # Join the lines
    short_description = "\n".join(short_lines).strip()
    long_description = "\n".join(long_lines).strip()

    if not short_description:
        short_description = None

    if not long_description:
        long_description = None

    # Done
    return short_description, long_description


def parse_docstring(
    docstring: str,
    *,
    key_sections: t.Iterable[str],
) -> data_models.Docstring:
    """
    Parses a docstring into

    - summary
    - details
    - sections

    Any sections listed in `key_sections` will be parsed as key-value pairs and
    returned as sections. Any remaining sections will be re-joined into the
    details.

    Any sections listed in `key_sections` that are not present in the docstring
    will be imputed as empty.
    """
    # Remove consistent indentation
    docstring = textwrap.dedent(docstring).strip()

    # Split the docstring into (summary + details) and sections
    summary_and_details, sections = split_docstring_into_sections(docstring)

    # Split into summary and details
    summary, details = parse_details(summary_and_details)
    del summary_and_details

    if details is None:
        details = ""

    # Find and parse all key-value sections
    key_sections = set(key_sections)
    key_value_sections: dict[str, dict[str, str]] = {}

    for section_name, section_contents in sections.items():
        # Key section?
        normalized_section_name = section_name.lstrip("#").strip().lower()

        if normalized_section_name in key_sections:
            key_value_sections[normalized_section_name] = parse_key_value_section(
                section_contents
            )

        # Text section
        else:
            details += f"\n\n{section_name}\n\n{section_contents}"

    # Don't keep around an empty details section
    details = details.strip()

    if not details:
        details = None

    # Make sure all requested sections are present
    missing_sections = key_sections - key_value_sections.keys()

    for missing_section in missing_sections:
        key_value_sections[missing_section] = {}

    # Done
    return data_models.Docstring(
        summary=summary,
        details=details,
        key_sections=key_value_sections,
    )


@t.overload
def parse(
    obj: data_models.ModuleObjectType,
    *,
    owner: data_models.ModuleDocs | None = None,
) -> data_models.ModuleDocs: ...


@t.overload
def parse(  # type: ignore (not mutually exclusive with the `Callable` overload)
    obj: data_models.ClassObjectType,
    *,
    owner: data_models.ModuleDocs | data_models.ClassDocs | None = None,
) -> data_models.ClassDocs: ...


@t.overload
def parse(
    obj: data_models.PropertyObjectType,
    *,
    owner: data_models.ClassDocs | None = None,
) -> data_models.PropertyDocs: ...


@t.overload
def parse(
    obj: data_models.FunctionObjectType,
    *,
    owner: data_models.ModuleDocs
    | data_models.ClassDocs
    | data_models.PropertyDocs
    | None = None,
) -> data_models.FunctionDocs: ...


def parse(
    obj: data_models.ModuleObjectType
    | data_models.FunctionObjectType
    | data_models.ClassObjectType
    | data_models.PropertyObjectType,
    *,
    owner: data_models.ModuleDocs
    | data_models.ClassDocs
    | data_models.PropertyDocs
    | None = None,
) -> (
    data_models.ModuleDocs
    | data_models.FunctionDocs
    | data_models.ClassDocs
    | data_models.PropertyDocs
):
    if isinstance(obj, types.ModuleType):
        return parse_module(obj, owner=t.cast(t.Any, owner))
    elif isinstance(obj, type):
        return parse_class(obj, owner=t.cast(t.Any, owner))
    elif isinstance(obj, property):
        return parse_property(obj, owner=t.cast(t.Any, owner))
    else:
        return parse_function(obj, owner=owner)


def parse_module(
    module: types.ModuleType,
    *,
    owner: data_models.ModuleDocs | None = None,
) -> data_models.ModuleDocs:
    # Parse the docstring
    docstring = inspect.getdoc(module)

    if docstring is None:
        parsed = data_models.Docstring(None, None, {})
        metadata = data_models.ModuleMetadata.from_dictionary({})
    else:
        parsed = parse_docstring(
            docstring,
            key_sections=["metadata"],
        )
        metadata = data_models.ModuleMetadata.from_dictionary(
            parsed.key_sections["metadata"]
        )

    # Collect all the public members
    module_dict = vars(module)
    try:
        public_member_names = module.__all__
    except AttributeError:

        def is_public(name: str, obj: object) -> bool:
            if name.startswith("_"):
                return False

            # Most modules are imported because they're required, not because
            # they're part of the public interface
            if isinstance(obj, types.ModuleType):
                # External modules are never public
                if obj.__package__ != module.__name__:
                    return False

                # Submodules may be public, but it's very rare and I can't think
                # of a reliable way to figure it out. Treating them all as
                # private has a much lower error rate than anything else I've
                # tried.
                return False

            # Classes and functions are considered public if they've been
            # defined in this module or a submodule
            if hasattr(obj, "__module__"):
                return (obj.__module__ + ".").startswith(module.__name__ + ".")

            # Some things, like TypeVars, are almost certainly not public
            if isinstance(obj, (t.TypeVar,)):
                return False

            return True

        public_member_names = [
            name for name, obj in module_dict.items() if is_public(name, obj)
        ]

    module_ = data_models.ModuleDocs(
        object=module,
        owner=owner,
        name=module.__name__.split(".")[-1],
        summary=parsed.summary,
        details=parsed.details,
        members={},
        metadata=metadata,
        deprecations=[],
    )

    for name in public_member_names:
        obj = module_dict[name]

        # Currently, we only support modules, classes and functions, so...
        if not isinstance(obj, (types.ModuleType, types.FunctionType, type)):
            continue

        member_docs = parse(obj, owner=module_)

        if member_docs.metadata.public:
            module_.add_member(member_docs)

    return module_


def parse_function(
    func: data_models.FunctionObjectType | classmethod | staticmethod,
    *,
    owner: data_models.ModuleDocs
    | data_models.ClassDocs
    | data_models.PropertyDocs
    | None = None,
) -> data_models.FunctionDocs:
    """
    Given a function, parse its signature and docstring into a `Function`
    object.
    """

    def parse_annotation(
        annotation: introspection.types.TypeAnnotation | type[inspect._empty],
    ) -> introspection.types.TypeAnnotation | data_models.Unset:
        if annotation is inspect.Parameter.empty:
            return data_models.UNSET

        # Recursive types can cause issues. In particular, we have `Jsonable`,
        # which is a recursive type, and `JsonDoc`, which references `Jsonable`.
        # So if a module imports `JsonDoc` but doesn't import `Jsonable`, it's
        # impossible to evaluate the forward reference `"Jsonable"` in that
        # module.
        #
        # As a workaround, we'll make the missing names available in every
        # module.
        extra_globals = collections.ChainMap(
            {"Jsonable": Jsonable},
            vars(t),  # type: ignore
        )

        # A similar problem exists due to dataclasses: The type annotations of
        # parent classes are copied into the signature of a child class's
        # `__init__` function, leading to unresolvable forward references if the
        # child class is in a different file than the parent class.
        #
        # Note: Since other `dataclass_transforms` exist, we won't apply
        # workaround *only* to dataclasses.
        forward_ref_context = func.__module__

        if func.__name__ == "__init__" and owner is not None:
            cls = owner.object

            if isinstance(cls, type):
                modules = [sys.modules[cls.__module__] for cls in cls.mro()]
                forward_ref_context = collections.ChainMap(
                    *[vars(module) for module in modules]
                )

        return introspection.typing.resolve_forward_refs(
            annotation,
            forward_ref_context,
            extra_globals=extra_globals,
            mode="ast",
            treat_name_errors_as_imports=True,
            strict=True,
        )

    is_class_method = is_static_method = False

    if isinstance(func, staticmethod):
        is_static_method = True
        func = t.cast(data_models.FunctionObjectType, func.__func__)
    elif isinstance(func, classmethod):
        is_class_method = True
        func = t.cast(data_models.FunctionObjectType, func.__func__)

    try:
        signature = inspect.signature(func)
    except ValueError:
        # Some builtins don't have an accessible signature. For now, we'll just
        # use a dummy.
        signature = inspect.Signature()

    # Parse the docstring
    docstring = inspect.getdoc(func)

    # Ignore the default docstring (inherited from `object`, I believe)
    if docstring == "Initialize self.  See help(type(self)) for accurate signature.":
        docstring = None

    if docstring is None:
        parsed = data_models.Docstring(
            summary=None, details=None, key_sections={"parameters": {}}
        )
        raises = []
        metadata = data_models.FunctionMetadata.from_dictionary({})
    else:
        parsed = parse_docstring(
            docstring,
            key_sections=[
                "parameters",
                "raises",
                "metadata",
            ],
        )

        # Add information about raised exceptions
        raises = list(parsed.key_sections["raises"].items())

        # Parse the metadata
        metadata = data_models.FunctionMetadata.from_dictionary(
            parsed.key_sections["metadata"]
        )

    # Check for deprecations
    unwrapped_func = inspect.unwrap(func)
    try:
        deprecations = deprecated_objects[unwrapped_func].copy()
    except KeyError:
        deprecations = []

    # Build the result
    function_ = data_models.FunctionDocs(
        object=func,
        owner=owner,
        name=func.__name__,
        parameters={},
        return_type=parse_annotation(signature.return_annotation),
        synchronous=not inspect.iscoroutinefunction(unwrapped_func),
        class_method=is_class_method,
        static_method=is_static_method,
        summary=parsed.summary,
        details=parsed.details,
        raises=raises,
        metadata=metadata,
        deprecations=deprecations,
    )

    # Parse the parameters
    for param_name, param in signature.parameters.items():
        # Skip private parameters. (It's rare to have private parameters, but
        # they do exist. Dataclasses in particular tend to have them.)
        if is_private_name(param_name):
            continue

        if param.default == inspect.Parameter.empty:
            param_default = data_models.UNSET
        else:
            param_default = param.default

        # Check for deprecations
        try:
            deprecations = deprecated_parameters[func][param_name].copy()
        except KeyError:
            deprecations = []

        param_ = data_models.ParameterDocs(
            owner=function_,
            name=param_name,
            type=parse_annotation(param.annotation),
            default=param_default,
            kw_only=param.kind == inspect.Parameter.KEYWORD_ONLY,
            collect_positional=param.kind == inspect.Parameter.VAR_POSITIONAL,
            collect_keyword=param.kind == inspect.Parameter.VAR_KEYWORD,
            description=None,
            deprecations=deprecations,
        )
        function_.parameters[param_name] = param_

    # Add any information learned about parameters from the docstring
    for param_name, param_details in parsed.key_sections["parameters"].items():
        try:
            result_param = function_.parameters[param_name]
        except KeyError:
            warnings.warn(
                f"The docstring for function `{func.__name__}` mentions a parameter `{param_name}` that does not exist in the function signature."
            )
            continue

        result_param.description = param_details

    return function_


def _parse_class_docstring_with_inheritance(
    cls: type,
    *,
    key_sections: t.Iterable[str],
    merge_key_section: t.Callable[
        [str, dict[str, str], dict[str, str]], dict[str, str]
    ] = lambda name, parent, child: {**parent, **child},
) -> data_models.Docstring:
    """
    Parses the docstring of a class in the same format as `parse_docstring`, but
    accounts for inheritance: Key-Value sections of all classes are merged, in a
    way that preserves child  over parent .
    """

    # Parse the docstring for this class
    raw_ = inspect.getdoc(cls)

    key_sections = set(key_sections)
    parsed_ = parse_docstring(
        "" if raw_ is None else raw_,
        key_sections=key_sections,
    )

    # Get the docstrings for the base classes
    base_: list[data_models.Docstring] = []

    for base in cls.__bases__:
        base_.append(
            _parse_class_docstring_with_inheritance(
                base,
                key_sections=key_sections,
                merge_key_section=merge_key_section,
            )
        )

    # Merge the docstrings
    result_sections: dict[str, dict[str, str]] = {}
    all_in_order = base_ + [parsed_]

    for cur_ in all_in_order:
        for section_name, cur_section in cur_.key_sections.items():
            result_section = result_sections.get(section_name, {})
            result_section = merge_key_section(
                section_name, result_section, cur_section
            )
            result_sections[section_name] = result_section

    parsed_.key_sections = result_sections

    # Done
    return parsed_


def parse_class(
    cls: type,
    *,
    owner: data_models.ClassOwnerType | None = None,
) -> data_models.ClassDocs:
    """
    Given a class, parse its signature an docstring into a `Class` object.
    """

    # Prepare a function for merging key sections
    def merge_key_section(
        name: str,
        parent: dict[str, str],
        child: dict[str, str],
    ) -> dict[str, str]:
        # Metadata is special: The parent doesn't matter, the child always wins.
        # This is to avoid unexpected situations, where a class would be e.g.
        # private, just because the parent is private.
        if name == "metadata":
            return child

        # Otherwise merge the two. Child values override parent values.
        return {**parent, **child}

    # Parse the docstring
    docstring = _parse_class_docstring_with_inheritance(
        cls,
        key_sections=[
            "attributes",
            "metadata",
        ],
        merge_key_section=merge_key_section,
    )

    # Check for deprecations
    try:
        deprecations = deprecated_objects[cls].copy()
    except KeyError:
        deprecations = []

    # Build the result. Functions have a backreference to the class , so
    # they will be added later.
    class_ = data_models.ClassDocs(
        object=cls,
        owner=owner,
        name=cls.__name__,
        members={},
        attributes={},
        summary=docstring.summary,
        details=docstring.details,
        metadata=data_models.ClassMetadata.from_dictionary(
            docstring.key_sections["metadata"]
        ),
        deprecations=deprecations,
    )

    # Parse the fields
    #
    # Make sure to add fields from base classes as well
    def add_fields(cls: type) -> None:
        # Processing `type` causes all sorts of problems, since it's the "root
        # metaclass". Best to just skip it.
        if cls is type:
            return

        # Chain to the base classes
        for base in cls.__bases__:
            add_fields(base)

        # Then process this class. This way locals fields override inherited
        # ones.
        for attribute_name, annotation in vars(cls).get("__annotations__", {}).items():
            # Skip `_: KW_ONLY` and `_private_attributes`
            if is_private_name(attribute_name):
                continue

            attribute_type = introspection.typing.resolve_forward_refs(
                annotation=annotation,
                context=cls.__module__,
                mode="ast",
                strict=True,
                treat_name_errors_as_imports=True,
            )

            field = data_models.AttributeDocs(
                owner=class_,
                name=attribute_name,
                type=attribute_type,
                default=data_models.UNSET,
                description=None,
                deprecations=[],
            )
            class_.attributes[attribute_name] = field

        # Properties are also fields
        for prop_name, prop in vars(cls).items():
            # Skip private attributes
            if is_private_name(prop_name):
                continue

            if isinstance(prop, property):
                prop_docs = data_models.PropertyDocs.from_property(prop, owner=class_)

                if prop_docs.metadata.public:
                    class_.members[prop_name] = prop_docs

    add_fields(cls)

    # Is this a dataclass? If so, get the fields from there
    if is_dataclass(cls):
        for dataclass_field in dataclasses.fields(cls):
            try:
                doc_field = class_.attributes[dataclass_field.name]
            except KeyError:
                # If it's not in the dict, it was deemed private. Skip it.
                continue

            # Default value?
            if dataclass_field.default is not dataclasses.MISSING:
                doc_field.default = dataclass_field.default

            # Default factory?
            elif dataclass_field.default_factory is not dataclasses.MISSING:
                doc_field.default = data_models.SENTINEL

    # Add any information learned about fields from the docstring
    for field_name, field_details in docstring.key_sections["attributes"].items():
        try:
            result_field = class_.attributes[field_name]
        except KeyError:
            # Warn about the missing field, unless there's a property with that
            # name
            if not isinstance(getattr(cls, field_name, None), property):
                warnings.warn(
                    f"The docstring for class `{cls.__name__}` mentions a field `{field_name}` that does not exist in the class."
                )
            continue

        result_field.description = field_details

    # Parse the functions
    #
    # Make sure to add functions from base classes as well
    seen_functions = set[str]()

    def add_functions(cls: type) -> None:
        # Skip well-known base classes like `Enum`
        if cls is enum.Enum:
            return

        # First process this class...
        for name, func in vars(cls).items():
            # Skip private methods
            if is_private_name(name):
                continue

            # Skip overridden methods
            if name in seen_functions:
                continue

            if (
                inspect.isfunction(func)
                or isinstance(func, classmethod)
                or isinstance(func, staticmethod)
            ):
                seen_functions.add(name)

                func_ = parse_function(func, owner=class_)

                if func_.metadata.public:
                    class_.members[name] = func_

        # ...then chain to the base classes
        for base in cls.__bases__:
            add_functions(base)

    add_functions(cls)

    # If `__init__` is missing documentation for any parameters, try to copy the
    # values from matching fields.
    init_method = class_.init_method
    if init_method is not None:
        for param in init_method.parameters.values():
            if param.description is not None:
                continue

            try:
                attr = class_.attributes[param.name]
            except KeyError:
                continue

            param.description = attr.description

    return class_


def parse_property(
    prop: property, owner: data_models.PropertyOwnerType | None
) -> data_models.PropertyDocs:
    assert prop.fget is not None

    if isinstance(owner, type):
        owner = data_models.ClassDocs.from_class(owner)

    getter = data_models.FunctionDocs.from_function(
        t.cast(data_models.FunctionObjectType, prop.fget)
    )
    summary = getter.summary
    details = getter.details
    deprecations = getter.deprecations
    metadata = getter.metadata

    if prop.fset is None:
        setter = None
    else:
        setter = data_models.FunctionDocs.from_function(
            t.cast(data_models.FunctionObjectType, prop.fset)
        )
        summary = summary or setter.summary
        details = details or setter.details
        deprecations = deprecations + setter.deprecations  # DON'T use `+=`!
        metadata = metadata or setter.metadata

    property_docs = data_models.PropertyDocs(
        object=prop,
        owner=owner,
        name=getter.name,
        getter=getter,
        setter=setter,
        summary=summary,
        details=details,
        metadata=data_models.PropertyMetadata.from_function_metadata(metadata),
        deprecations=deprecations,
    )

    getter.owner = property_docs
    if setter is not None:
        setter.owner = property_docs

    return property_docs


def is_private_name(name: str) -> bool:
    # Rules:
    # - `_foo` is private
    # - `__init__` is public
    # - `__foo__` is private
    if name == "__init__":
        return False

    return name.startswith("_")
