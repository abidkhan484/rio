import logging
import typing as t

import imy.async_utils

from . import base_transport, data_models, errors

_logger = logging.getLogger(__name__)


def _default_error_callback(error: Exception) -> None:
    """
    Default error callback that logs the error.
    """
    _logger.exception("Error in RPC request:")


class Unicall:
    """
    Base class for all RPC interfaces.

    Unicall is a base class for all interfaces that you want to expose to the
    outside world. It acts as a registry of functions that can be called either
    by you (@remote), or by a remote client (@local).
    """

    # Maps function names of all @local functions to function objects. The name
    # (key) is the name as would be seen by a remote client. The function object
    # contains already parsed metadata about the function. The callable is the
    # actual method to call.
    #
    # This value must be separate for each class. Thus, it is never actually
    # initialized here, but rather by `__init_subclass__`.
    _local_methods_: dict[str, tuple[data_models.FunctionMetadata, t.Callable]]

    # Maps function names of all @remote functions to function objects. The name
    # (key) is the name as would be seen by a remote client.
    _remote_methods_: dict[str, data_models.FunctionMetadata]

    def __init__(
        self,
        *,
        transport: base_transport.Transport,
        error_callback: t.Callable[[Exception], None] = _default_error_callback,
    ) -> None:
        """
        Creates a new RPC instance.

        This function creates a new RPC instance, that exposes all of it's
        `@local` functions to the outside world as well as providing the ability
        to call `@remote` functions.

        ## Parameters

        `transport`: A connection used to communicate with the remote end.

        `error_callback`: A callback that is called whenever an error occurs
            during the processing of a `@local` function. The default simply
            logs the error.
        """
        self._transport = transport
        self._error_callback = error_callback

    def __init_subclass__(cls) -> None:
        # Initialize per-class attributes. These mustn't be inherited, but
        # rather be local to each class.
        cls._local_methods_ = {}
        cls._remote_methods_ = {}

        # Find all methods annotated with @local and register them
        for member in vars(cls).values():
            # Local method?
            try:
                function_meta = member._unicall_local_
            except AttributeError:
                pass
            else:
                assert callable(member), member
                cls._local_methods_[function_meta.name] = (function_meta, member)

            # Remote method?
            try:
                function_meta = member._unicall_remote_
            except AttributeError:
                pass
            else:
                assert callable(member), member
                cls._remote_methods_[function_meta.name] = function_meta

    async def _handle_single_request(
        self,
        python_function,
        arguments: list[t.Any],
        success_callback: t.Callable[[t.Any], t.Awaitable[None]],
        error_callback: t.Callable[[Exception], t.Awaitable[None]],
    ) -> None:
        """
        Processes a single request to run a local function, responding as
        needed.

        No exceptions are ever raised by this function. Instead, they are
        reported using the `error_callback` function. (Though exceptions in the
        callbacks themselves are not caught.)
        """

        # Call the function
        try:
            result = await python_function(self, *arguments)
        except Exception as error:
            self._error_callback(error)
            await error_callback(error)
            return

        # Woo-hoo!
        await success_callback(result)

    async def serve(self) -> None:
        """
        Starts the RPC server.

        This method makes the server start listen for incoming requests and
        handles them. The function will never return - cancel it using `asyncio`
        mechanisms if you need it to stop early.

        If the transport raises an `RpcError`, the error is logged, but serving
        continues. Any other exceptions are propagated.
        """

        try:
            async with imy.async_utils.TaskGroup() as tasks:
                while True:
                    # Get a request
                    try:
                        (
                            function_meta,
                            python_function,
                            arguments,
                            success_callback,
                            error_callback,
                        ) = await self._transport.listen_for_request(self)
                    # RpcErrors can be used to indicate transient problems. Log
                    # them but don't give up.
                    #
                    # Any other exceptions propagate.
                    except errors.RpcError:
                        _logger.exception("Error in RPC request:")
                        continue

                    # Handle the request. Do that in a separate task so that
                    # multiple requests can be handled in parallel.
                    #
                    # Notice that this part cannot possibly raise any
                    # exceptions, because the task is never awaited, and the
                    # called function uses its `error_callback` to report
                    # exceptions, rather than raising them.
                    tasks.create_task(
                        self._handle_single_request(
                            python_function,
                            arguments,
                            success_callback,
                            error_callback,
                        ),
                        name=f"Request handler for function `{function_meta.name}`",
                    )

        # If anything goes wrong, `asyncio` raises an exception group,
        # containing the exceptions of all failed tasks. Since only getting
        # requests can actually fail, there should always be exactly one
        # exception in the group in our case. Propagate it.
        except imy.async_utils.ExceptionGroup as group:
            assert len(group.exceptions) == 1
            raise group.exceptions[0] from None
