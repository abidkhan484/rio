import dataclasses
import typing as t


@dataclasses.dataclass
class Parameter:
    # Human readable name of the parameter. Protocols may also use this as a
    # unique identifier for the parameter.
    name: str

    # The type of any argument assigned to this parameter. Must be compatible
    # with `uniserde`.
    type: t.Type


@dataclasses.dataclass
class FunctionMetadata:
    # Human readable name of the function. Protocols may also use this as a
    # unique identifier for the function.
    name: str

    # The parameters that this function accepts.
    parameters: list[Parameter]

    # The type of the result of this function. If not `None`, must be compatible
    # with `uniserde`.
    #
    # Attention! This will by `type(None)` if the function returns `None`, NOT
    # `None`.
    return_type: t.Type = type(None)
