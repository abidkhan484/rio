from __future__ import annotations

import re
import typing as t

import introspection

__all__ = [
    "mark_as_private",
    "mark_constructor_as_private",
    "insert_links_into_markdown",
]


Class = t.TypeVar("Class", bound=type)
ClassOrFunction = t.TypeVar("ClassOrFunction", bound=t.Callable)


def mark_as_private(obj: ClassOrFunction) -> ClassOrFunction:
    """
    Adds `public: False` to the `## Metadata` section of the given object's
    docstring.
    """

    if obj.__doc__ is None:
        obj.__doc__ = "## Metadata"
    elif "## Metadata" not in obj.__doc__:
        obj.__doc__ += "\n## Metadata"

    obj.__doc__ += "\n`public`: False"

    return obj


def mark_constructor_as_private(cls: Class) -> Class:
    """
    Calls `mark_as_private` on the class's `__init__` method. (If the `__init__`
    method is inherited from a parent class, a new one will be created.)
    """

    try:
        constructor = vars(cls)["__init__"]
    except KeyError:

        @introspection.mark.does_not_alter_signature
        def constructor(self, *args, **kwargs):
            super(cls, self).__init__(*args, **kwargs)  # type: ignore (wtf?)

        introspection.add_method_to_class(constructor, cls, "__init__")

    mark_as_private(constructor)  # type: ignore (wtf?)

    return cls


_CODE_BLOCK_REGEX = re.compile(r"(?!$)(.*?)(```.*?```|$)", flags=re.S)
_NAME_TO_LINK_REGEX = re.compile(
    r"`([a-zA-Z_.]+)`(?!\])"
)  # TODO: Why does this specifically look for a "]" character?


def insert_links_into_markdown(
    markdown: str,
    url_for_name: t.Callable[[str], str | None],
) -> str:
    r"""
    Looks for references to functions/classes/etc and turns them into
    hyperlinks.

    References are identifiers enclosed in backticks, for example:

    - `` `MyClass` ``
    - `` `my_module.MyClass` ``

    Every found reference is passed to the `url_for_name` function. If the
    function returns `None`, no hyperlink will be created.
    """

    def repl(match: re.Match) -> str:
        url = url_for_name(match.group(1))

        if url is None:
            return match.group()

        return f"[{match.group()}]({url})"

    # We want to look for single-line text like `MyClass` and turn it
    # into a link. The problem is that such text might be appear inside
    # of a code block (in a comment). So we'll search for code blocks,
    # and only apply the substituation in the text before the code
    # block.
    chunks = list[str]()

    for match_ in _CODE_BLOCK_REGEX.finditer(markdown):
        text, code_block = match_.groups()

        chunks.append(_NAME_TO_LINK_REGEX.sub(repl, text))
        chunks.append(code_block)

    return "".join(chunks)
