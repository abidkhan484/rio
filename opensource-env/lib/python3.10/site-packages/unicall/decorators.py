import functools
import inspect
import typing as t

import typing_extensions as te

import unicall

from . import data_models, utils

__all__ = [
    "local",
    "remote",
]


def _function_meta_from_python_method(
    method: t.Callable,
    name_override: str | None,
    parameter_name_transform: t.Callable[[str], str] | None,
) -> data_models.FunctionMetadata:
    # Make sure the method is callable and awaitable
    if not callable(method):
        raise TypeError(f"Expected a method, not {type(method)}")

    if not inspect.iscoroutinefunction(method):
        raise TypeError(
            f"RPC methods need to be asynchronous. Did you forget `async` before `def {method.__name__}`?"
        )

    # Make sure the function has a return type annotation. None is also okay
    if "return" not in method.__annotations__:
        raise ValueError(
            f"The method `{method.__name__}` is missing a return type annotation. Did you forget a `-> None`?",
        )

    # Get the method name
    if name_override is None:
        name = method.__name__
    else:
        name = name_override

    del name_override

    # Get the parameters, taking care to strip `self`
    parsed_signature = utils._get_parsed_signature(method)
    signature_parameters = list(parsed_signature.parameters.values())[1:]

    # Build the parameter list
    parameters: list[data_models.Parameter] = []

    for param in signature_parameters:
        # Make sure the parameter is annotated
        if param.annotation is param.empty:
            raise ValueError(
                f"The parameter `{param.name}` is missing a type annotation",
            )

        assert param.annotation is not None, param

        # Get the parameter name
        if parameter_name_transform is None:
            param_name = param.name
        else:
            param_name = parameter_name_transform(param.name)

        # Create the parameter
        parameters.append(
            data_models.Parameter(
                name=param_name,
                type=param.annotation,
            )
        )

    # Build the result
    return data_models.FunctionMetadata(
        name=name,
        parameters=parameters,
        return_type=parsed_signature.return_annotation,
    )


def _process_local_method(
    method: t.Callable,
    name: str | None,
    parameter_name_transform: t.Callable[[str], str] | None,
) -> None:
    # Parse the function object
    function_meta = _function_meta_from_python_method(
        method,
        name_override=name,
        parameter_name_transform=parameter_name_transform,
    )

    # Store it in the method
    method._unicall_local_ = function_meta


@te.overload
def local(method: t.Callable[..., t.Any]): ...


@te.overload
def local(
    name: str | None = None,
    *,
    parameter_name_transform: t.Callable[[str], str] | None = None,
): ...


def local(*args, **kwargs):
    """
    Marks the decorated method as a local RPC method. Local methods run locally,
    i.e. they can be called by the _other_ process. (Though the decorated method
    can also still be called locally.)

    The method's arguments must be supported by `uniserde`. Parameters may not
    be keyword-only, and not be variadic.

    If the function raises an `RpcError`, the error will be sent to the remote
    unchanged, allowing you to control what the remote end sees. Any other
    exceptions are also wrapped up into a `RpcError`, but with little
    information to ensure no sensitive implementation details are leaked.
    """

    # If called with a single method argument, register the method
    if len(args) == 1 and not kwargs and callable(args[0]):
        _process_local_method(args[0], None, lambda x: x)
        return args[0]

    # Otherwise, return a decorator
    def build_decorator(
        name: str | None = None,
        *,
        parameter_name_transform: t.Callable[[str], str] | None = None,
    ):
        def decorator(method: t.Callable[..., t.Any]):
            _process_local_method(method, name, parameter_name_transform)
            return method

        return decorator

    return build_decorator(*args, **kwargs)


P = t.ParamSpec("P")
T = t.TypeVar("T")
V = t.TypeVar("V")
W = t.TypeVar("W")


def _process_remote_method(
    python_function: t.Callable,
    name: str | None,
    parameter_name_transform: t.Callable[[str], str] | None,
    await_response: bool,
) -> t.Callable:
    # Parse the function object
    function_meta = _function_meta_from_python_method(
        python_function,
        name_override=name,
        parameter_name_transform=parameter_name_transform,
    )

    # Create a new function which delegates to the remote method without ever
    # calling the original one
    signature = utils._get_parsed_signature(python_function)

    async def wrapper(self, *args: t.Any, **kwargs: t.Any) -> t.Any:
        assert isinstance(self, unicall.Unicall), self

        # Bind the arguments, taking care to drop `self`
        bound_args = signature.bind(self, *args, **kwargs)
        bound_args.apply_defaults()
        bound_args.arguments.pop("self")

        # Delegate to the transport
        return await self._transport.call_remote_function(
            function_meta=function_meta,
            arguments=list(bound_args.arguments.values()),
            await_response=await_response,
        )

    # Create the result, taking care to add the function object
    result = functools.wraps(python_function)(wrapper)
    result._unicall_remote_ = function_meta  # type: ignore
    return result


@te.overload
def remote(method: t.Callable[P, t.Awaitable[T]]) -> t.Callable[P, t.Awaitable[T]]: ...


@te.overload
def remote(
    name: str | None = None,
    *,
    parameter_name_transform: t.Callable[[str], str] | None = None,
    await_response: bool = True,
) -> t.Callable[[t.Callable[P, t.Awaitable[T]]], t.Callable[P, t.Awaitable[T]]]: ...


def remote(*args, **kwargs) -> t.Any:
    """
    Marks the decorated method as a remote RPC method. Remote methods run
    in the _other_ process, i.e. they can be called by the local process.
    Because of that, remote methods don't have to provide any function body,
    because that would never be executed (this decorator makes sure of that). By
    convention, you can just raise a `NotImplementedError` to indicate that the
    method is not implemented on the local side.

    The method's arguments must be supported by `uniserde`. Parameters may not
    be keyword-only, and not be variadic.

    If the remote function fails during a call, a `RpcError` will be raised
    with the error message from the remote end.
    """

    # If called with a single method argument, register it
    if len(args) == 1 and not kwargs and callable(args[0]):
        return _process_remote_method(
            python_function=args[0],
            name=None,
            parameter_name_transform=None,
            await_response=True,
        )

    # Otherwise, return a decorator
    def build_decorator(
        name: str | None = None,
        *,
        parameter_name_transform: t.Callable[[str], str] | None = None,
        await_response: bool = True,
    ):
        def decorator(method: t.Callable):
            return _process_remote_method(
                python_function=method,
                name=name,
                parameter_name_transform=parameter_name_transform,
                await_response=await_response,
            )

        return decorator

    return build_decorator(*args, **kwargs)
