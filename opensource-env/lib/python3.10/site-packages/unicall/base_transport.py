from __future__ import annotations

import abc
import typing as t

import unicall

from . import data_models


class Transport(abc.ABC):
    @abc.abstractmethod
    async def call_remote_function(
        self,
        function_meta: data_models.FunctionMetadata,
        arguments: list[t.Any],
        await_response: bool,
    ) -> t.Any:
        """
        Call a function on the remote end of the channel, (optionally) wait for
        it to complete, and return the result.

        The number of arguments must match the number of parameters defined in
        the function.

        If `await_response` is `True`, this will block until the remote end
        finishes executing the function and returns a response. The result is of
        the same type as recorded in the `function`, already deserialized. If
        `False`, the method _may_ return before and will return `None`. (Some
        channels may not be able to return before the function completes, e.g.
        because they hand control of the thread to that function.)

        ## Raises

        `RpcError`: If communication with the remote end fails.

        `RpcError`: If the remote end raises an exception while executing the
            function.

        `RpcError`: If the remote end returns an invalid response.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def listen_for_request(
        self,
        interface: unicall.Unicall,
    ) -> tuple[
        data_models.FunctionMetadata,
        t.Callable,
        list[t.Any],
        t.Callable[[t.Any], t.Awaitable[None]],
        t.Callable[[Exception], t.Awaitable[None]],
    ]:
        """
        Waits for a single request from the client and returns all information
        necessary to handle it.

        The result is a tuple of:

        - The metadata of the function to call.
        - The actual function to call.
        - The arguments to pass to the function.
        - A function to call with the result of the request
        - A function to call with an error if the request fails

        It is this function's responsibility to ensure that the correct number
        of arguments was passed, and that they are of the correct type.
        """
        raise NotImplementedError()
