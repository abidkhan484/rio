import typing as t

from uniserde import Jsonable

__all__ = [
    "RpcError",
    "InvalidRequestError",
    "NoSuchFunctionError",
    "InvalidArgumentsError",
    "FailedFunctionError",
]


class RpcError(Exception):
    """
    Indicates an RPC related error.

    ## Attributes

    `message`: A human-readable error message. This may be sent to the remote
        and thus shouldn't contain any sensitive information.

    `error_code`: An optional error code. Some transports support these to give
        additional information to the remote.

    `error_data`: Some transports support transmitting data (like an exception)
        to the remote in the case of an error. This is where that data would be
        stored.

    `debug_object`: An optional object that may be useful for debugging. This
        will not be sent to the remote and will never be serialized. It can thus
        be any Python object that could help you debug the error.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: t.Any = None,
        error_data: Jsonable | None = None,
        debug_object: t.Any = None,
    ) -> None:
        super().__init__(message, error_code, error_data, debug_object)

    @property
    def message(self) -> str:
        return self.args[0]

    @property
    def error_code(self) -> t.Any:
        return self.args[1]

    @property
    def error_data(self) -> Jsonable | None:
        return self.args[2]

    @property
    def debug_object(self) -> t.Any:
        return self.args[3]


class InvalidRequestError(RpcError):
    """
    Generic error indicating that a request was invalid. Use more specific
    errors if available.
    """


class NoSuchFunctionError(RpcError):
    """
    Error indicating that the requested function does not exist.
    """


class InvalidArgumentsError(RpcError):
    """
    Error indicating that the arguments passed to a function were invalid.
    """


class FailedFunctionError(RpcError):
    """
    Error indicating that the function has raised an exception.
    """
