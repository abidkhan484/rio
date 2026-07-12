from __future__ import annotations

import re

_SPLIT_CAMEL_CASE_PATTERN = re.compile(
    ".+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)"
)


def _is_lower(c: str) -> bool:
    """
    Does the obvious.

    The built-in `str.islower` method is not used because it mysteriously
    returns `False` for some strings, such as `_`.
    """
    return c == c.lower()


def _is_upper(c: str) -> bool:
    """
    Does the obvious.

    The built-in `str.islower` method is not used because it mysteriously
    returns `False` for some strings, such as `_`.
    """
    return c == c.upper()


def all_lower_to_camel_case(name: str) -> str:
    """
    Converts a string from all_lower_case to camelCase.
    """
    assert _is_lower(name), name

    if not name:
        return ""

    parts = name.split("_")
    assert parts, (name, parts)

    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def all_lower_to_camel_case_with_id_exception(name: str) -> str:
    """
    Convert all lower case names to camel case, except for the string "id",
    which becomes "_id".
    """
    if name == "id":
        return "_id"

    return all_lower_to_camel_case(name)


def identity(name: str) -> str:
    """
    Keeps the name the same.
    """
    return name


def all_upper_to_camel_case(name: str) -> str:
    """
    Converts a string from ALL_UPPER_CASE to camelCase.
    """
    assert _is_upper(name), name

    if not name:
        return ""

    parts = name.split("_")
    assert parts, (name, parts)

    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:])


def all_upper_to_upper_camel_case(name: str) -> str:
    """
    Converts a string from ALL_UPPER_CASE to UpperCamelCase.
    """
    assert _is_upper(name), name

    if not name:
        return ""

    parts = name.split("_")
    assert parts, (name, parts)

    return "".join(p.capitalize() for p in parts)


def camel_case_to_all_upper(name: str) -> str:
    """
    Converts a string from camelCase to ALL_UPPER_CASE.
    """
    matches = _SPLIT_CAMEL_CASE_PATTERN.finditer(name)
    groups = [m.group(0).upper() for m in matches]
    return "_".join(groups)


def upper_camel_case_to_camel_case(name: str) -> str:
    """
    Converts a string from UpperCamelCase to camelCase.
    """
    if not name:
        return ""

    return name[0].lower() + name[1:]


def all_lower_to_kebab_case(name: str) -> str:
    """
    Converts a string from all_lower_case to kebab-case.
    """
    assert _is_lower(name), name
    return name.replace("_", "-")
