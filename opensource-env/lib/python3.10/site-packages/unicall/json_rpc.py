import asyncio
import functools
import json
import typing as t

import typing_extensions as te
import uniserde
from uniserde import Jsonable, JsonDoc

import unicall

from . import base_transport, data_models
from .errors import (
    FailedFunctionError,
    InvalidArgumentsError,
    InvalidRequestError,
    NoSuchFunctionError,
    RpcError,
)

__all__ = [
    "STATUS_CODE_PARSE_ERROR",
    "STATUS_CODE_INVALID_REQUEST",
    "STATUS_CODE_METHOD_NOT_FOUND",
    "STATUS_CODE_INVALID_PARAMS",
    "STATUS_CODE_INTERNAL_ERROR",
    "STATUS_CODE_SERVER_ERROR",
    "JsonRpcTransport",
]


# JSON-RPC Error Codes
STATUS_CODE_PARSE_ERROR = -32700  # Invalid JSON was received by the server
STATUS_CODE_INVALID_REQUEST = -32600  # The JSON sent is not a valid Request object
STATUS_CODE_METHOD_NOT_FOUND = -32601  # The method does not exist / is not available
STATUS_CODE_INVALID_PARAMS = -32602  # Invalid method parameter(s)
STATUS_CODE_INTERNAL_ERROR = -32603  # Internal JSON-RPC error
STATUS_CODE_SERVER_ERROR = -32000  # Reserved for implementation-defined server-errors


class JsonRpcTransport(base_transport.Transport):
    def __init__(
        self,
        send: t.Callable[[str], t.Awaitable[None]],
        receive: t.Callable[[], t.Awaitable[str]],
        *,
        serde: uniserde.JsonSerde | None = None,
        parameter_format: t.Literal["list", "dict"] = "dict",
        json_dumps: t.Callable[[JsonDoc], str] = json.dumps,
        json_loads: t.Callable[[str], JsonDoc] = json.loads,
    ) -> None:
        """
        A transport using the JSON-RPC 2.0 standard.

        ## Parameters

        `send`: This function will be called whenever a message needs to be sent
            to the client. The sent values are JSON documents, already encoded
            as strings.

        `receive`: This function will be called whenever the transport is ready
            to receive another message. It should block until a message is
            available, and then return the message as a string.

        `serde`: Optional a custom `uniserde.JsonSerde` instance to use for
            serialization and deserialization. If not provided, an instance with
            default settings will be used.

        `parameter_format`: JSON-RPC allows sending parameters as either a list
            or a dictionary. This parameter specifies which format to use.

        `json_dumps`: A function that serializes a JSON document to a string. If
            not provided, Python's built-in `json.dumps` will be used.
            Overriding this allows you to e.g. handle types that aren't natively
            serializable by Python's `json` module.

            This function should raise a `TypeError` if the input is not
            serializable.

        `json_loads`: A function that deserializes a JSON string to a document.
            If not provided, Python's built-in `json.loads` will be used.
            Overriding this allows you to e.g. handle types that aren't natively
            deserializable by Python's `json` module.

            This function should raise a `JSONDecodeError` if the input is not
            valid JSON.
        """
        # Functions to communicate with the outside world
        self._send_message = send
        self._receive_message = receive

        # Prepare a serializer/deserializer. Reusing the same one allows for
        # maximum caching.
        if serde is None:
            self._serde = uniserde.JsonSerde()
        else:
            self._serde = serde

        # JSON-RPC supports allows parameter to be passed as either a list or a
        # dictionary. This is the format that will be used.
        self._argument_format = parameter_format

        # Overrides for JSON serialization/deserialization
        self._json_dumps = json_dumps
        self._json_loads = json_loads

        # The next free id to use for a remote call
        self._next_free_remote_id = 1

        # A dictionary of in-flight requests. The key is the id of the request,
        # and the value is a future that will be resolved once the response has
        # been received.
        self._in_flight_requests: dict[int | str, asyncio.Future[JsonDoc]] = {}

    @te.override
    async def call_remote_function(
        self,
        function_meta: data_models.FunctionMetadata,
        arguments: list[t.Any],
        await_response: bool,
    ) -> t.Any:
        # Serialize the arguments
        assert len(arguments) == len(function_meta.parameters), arguments

        serialized_arguments = {
            param.name: self._serde.as_json(arg, as_type=param.type)
            for arg, param in zip(arguments, function_meta.parameters)
        }

        if self._argument_format == "dict":
            serialized_arguments = list(serialized_arguments.values())

        # Prepare the message to send
        message = {
            "jsonrpc": "2.0",
            "method": function_meta.name,
            "params": serialized_arguments,
        }

        # If no response is requested, just send the message - done!
        if not await_response:
            await self._send_message(self._json_dumps(message))
            return None

        # Create a unique id for the request.
        id = self._next_free_remote_id
        self._next_free_remote_id += 1
        message["id"] = id

        # Register a future for the result
        future: asyncio.Future[JsonDoc] = asyncio.get_running_loop().create_future()
        self._in_flight_requests[id] = future

        try:
            # Send a message to the other end
            await self._send_message(self._json_dumps(message))

            # Wait for a response
            response = await future

        # Make sure the future is removed from the in-flight list
        finally:
            del self._in_flight_requests[id]

        # Success?
        try:
            serialized_result = response["result"]
        except KeyError:
            pass
        else:
            try:
                return self._serde.from_json(
                    function_meta.return_type,
                    serialized_result,
                )
            except uniserde.SerdeError as err:
                raise RpcError(
                    f"Invalid server response. Expected a value of type `{function_meta.return_type!r}`, but got `{serialized_result!r}`",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=(serialized_result, function_meta.return_type, err),
                ) from None

        # Error?
        if "error" in response:
            # Get the error dictionary
            error = response["error"]

            if not isinstance(error, dict):
                raise RpcError(
                    "Server response has an `error` field, but it is not an object",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=response,
                )

            # Get the error message
            try:
                message = error["message"]
            except KeyError:
                raise RpcError(
                    "Server response has an `error` field, but it is missing the `message` field",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=response,
                )

            if not isinstance(message, str):
                raise RpcError(
                    "Server `message` in the response's error is not a string",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=response,
                )

            # Get the error code
            code = error.get("code")

            if code is not None and not isinstance(code, int):
                raise RpcError(
                    "Server `code` in the response's error is not an integer",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=response,
                )

            # Raise the error
            raise RpcError(
                message,
                error_code=code,
                error_data=error.get("data"),
                debug_object=response,
            )

        # Invalid response
        raise RpcError(
            "Server response has neither a `result` nor `error` field",
            error_code=STATUS_CODE_INVALID_REQUEST,
            debug_object=response,
        )

    @te.override
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
        while True:
            # Get a message
            #
            # If this crashes, it's reasonable for the channel to do the
            # same, as the connection has likely been closed/lost.
            # Continuously attempting to get a message again would likely
            # just spike the CPU for no benefit. Hence no error handling.
            message_str = await self._receive_message()

            # Parse the message
            try:
                message = self._json_loads(message_str)

            # Invalid JSON
            except json.JSONDecodeError as err:
                raise RpcError(
                    f"Received a message that was invalid JSON: {err}: `{message_str}`",
                    error_code=STATUS_CODE_PARSE_ERROR,
                    debug_object=message_str,
                )

            # Valid JSON, but not an object
            if not isinstance(message, dict):
                raise RpcError(
                    f"Received a message that was valid JSON, but not a JSON object: {message}",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=message,
                )

            # Is this a response?
            if "result" in message or "error" in message:
                self._handle_response_message(message)
                continue

            # Otherwise, this is a request. Get all relevant information
            # from the message
            try:
                version = message["jsonrpc"]
                method_name_json = message["method"]
                serialized_arguments = message["params"]
                id = message.get("id")
            except KeyError as err:
                raise InvalidRequestError(
                    f"The message is missing the `{err.args[0]}` field",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=message,
                )

            # Make sure the version is compatible
            if version != "2.0":
                raise InvalidRequestError(
                    f"Unsupported JSON-RPC version: {version}",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=message,
                )

            # Verify the types of remaining fields
            if not isinstance(method_name_json, str):
                raise InvalidRequestError(
                    f"The `method` field must be a string, not `{method_name_json}`",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=message,
                )

            if not isinstance(serialized_arguments, (list, dict)):
                raise InvalidRequestError(
                    f"The `params` field must be a JSON object, not `{serialized_arguments}`",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=message,
                )

            if id is not None and not isinstance(id, (str, int)):
                raise InvalidRequestError(
                    f"The `id` field must be strings or integers, not `{id}`",
                    error_code=STATUS_CODE_INVALID_REQUEST,
                    debug_object=message,
                )

            # Find the requested function
            try:
                function_meta, python_function = interface._local_methods_[
                    method_name_json
                ]
            except KeyError:
                raise NoSuchFunctionError(
                    f"There is no function named `{method_name_json}`",
                    error_code=STATUS_CODE_METHOD_NOT_FOUND,
                    debug_object=message,
                ) from None

            # Deserialize the parameters
            parsed_arguments = self._deserialize_parameters(
                function_meta,
                serialized_arguments,
            )

            # Done
            return (
                function_meta,
                python_function,
                parsed_arguments,
                functools.partial(
                    self._respond_to_successful_request,
                    function_meta,
                    id,
                ),
                functools.partial(
                    self._respond_to_failed_request,
                    id,
                ),
            )

    async def _respond_to_successful_request(
        self,
        function_meta: data_models.FunctionMetadata,
        message_id: int | str | None,
        result: t.Any,
    ) -> None:
        """
        Sends the result of a request back to the client. If `success` is
        `True`, `result_or_error` is the result of the request. If `success`
        is `False`, `result_or_error` is an exception that was raised.
        """

        # If no response was requested, we're done
        if message_id is None:
            return

        # Serialize the result
        try:
            serialized_result = self._serde.as_json(
                result, as_type=function_meta.return_type
            )
        except uniserde.SerdeError as err:
            raise RpcError(
                "Internal server error",
                error_code=STATUS_CODE_SERVER_ERROR,
                debug_object=(result, function_meta.return_type, err),
            ) from None

        # Respond
        await self._send_message(
            self._json_dumps(
                {
                    "jsonrpc": "2.0",
                    "result": serialized_result,
                    "id": message_id,
                }
            )
        )

    async def _respond_to_failed_request(
        self,
        message_id: int | str | None,
        error: Exception,
    ) -> None:
        """
        Sends the result of a failed request back to the client.
        """

        # If no response was requested, we're done
        if message_id is None:
            return

        # Come up with all the information needed for a response
        #
        # If the error isn't a RpcError, keep the error message generic as no
        # to leak potentially sensitive information
        if not isinstance(error, RpcError):
            message = "Internal server error"
            error_code = STATUS_CODE_INTERNAL_ERROR
        else:
            message = error.message

            if isinstance(error.error_code, int):
                error_code = error.error_code
            elif isinstance(error, InvalidRequestError):
                error_code = STATUS_CODE_INVALID_REQUEST
            elif isinstance(error, NoSuchFunctionError):
                error_code = STATUS_CODE_METHOD_NOT_FOUND
            elif isinstance(error, InvalidArgumentsError):
                error_code = STATUS_CODE_INVALID_PARAMS
            elif isinstance(error, FailedFunctionError):
                error_code = STATUS_CODE_INTERNAL_ERROR
            else:
                error_code = STATUS_CODE_SERVER_ERROR

        # Build the result
        result = {
            "jsonrpc": "2.0",
            "error": {
                "code": error_code,
                "message": message,
            },
            "id": message_id,
        }

        if isinstance(error, RpcError) and error.error_data is not None:
            result["error"]["data"] = error.error_data

        # Send it
        await self._send_message(self._json_dumps(result))

    def _handle_response_message(self, message: JsonDoc) -> None:
        # Pass the message to the appropriate future
        try:
            id = message["id"]
        except KeyError:
            raise InvalidRequestError(
                "Message is missing the `id` field",
                error_code=STATUS_CODE_INVALID_REQUEST,
                debug_object=message,
            ) from None

        # Make sure the id is a string or integer
        if not isinstance(id, (str, int)):
            raise InvalidRequestError(
                f"The `id` field must be a string or integer, not `{id}`",
                error_code=STATUS_CODE_INVALID_REQUEST,
                debug_object=message,
            )

        # Get the future corresponding to the id
        try:
            future = self._in_flight_requests[id]
        except KeyError:
            raise InvalidRequestError(
                f"Received a response to an unknown request with id `{id}`",
                error_code=STATUS_CODE_INVALID_REQUEST,
                debug_object=message,
            ) from None

        # Resolve the future
        future.set_result(message)

    def _deserialize_parameters(
        self,
        function_meta: data_models.FunctionMetadata,
        serialized_arguments: Jsonable,
    ) -> list[t.Any]:
        """
        Deserialize the parameters for the given method using `uniserde`. The
        result is an iterable of the passed parameters in the order they appear
        in the method signature.

        If any parameters are missing, cannot be parsed, or are superfluous, a
        `RpcError` is raised.

        WARNING: `params` may be modified in-place.
        """
        # The parameter may be either a list or a dictionary
        if not isinstance(serialized_arguments, (list, dict)):
            raise InvalidArgumentsError(
                f"Parameters must be an array or an object, not `{serialized_arguments}`",
                error_code=STATUS_CODE_INVALID_PARAMS,
                debug_object=serialized_arguments,
            )

        # Was the correct number of parameters received?
        if len(serialized_arguments) != len(function_meta.parameters):
            raise InvalidArgumentsError(
                f"Method `{function_meta.name}` expects {len(function_meta.parameters)} parameter(s), but received {len(serialized_arguments)}",
                error_code=STATUS_CODE_INVALID_PARAMS,
                debug_object=serialized_arguments,
            )

        # Turn the parameters into a flat list
        if isinstance(serialized_arguments, dict):
            serialized_argument_dict: dict[str, Jsonable] = serialized_arguments
            serialized_arguments = []

            for param in function_meta.parameters:
                try:
                    argument_json = serialized_argument_dict.pop(param.name)
                except KeyError:
                    raise InvalidArgumentsError(
                        f"Method `{function_meta.name}` is missing a value for the parameter `{param.name}`",
                        error_code=STATUS_CODE_INVALID_PARAMS,
                        debug_object=serialized_argument_dict,
                    ) from None

                serialized_arguments.append(argument_json)

            # Make sure there are no superfluous parameters
            if serialized_argument_dict:
                raise InvalidArgumentsError(
                    f"Method `{function_meta.name}` has received superfluous parameters: {', '.join(serialized_argument_dict.keys())}",
                    error_code=STATUS_CODE_INVALID_PARAMS,
                    debug_object=serialized_argument_dict,
                ) from None

        # Deserialize them
        assert len(serialized_arguments) == len(
            function_meta.parameters
        ), serialized_arguments
        result = []

        for param, argument in zip(function_meta.parameters, serialized_arguments):
            try:
                result.append(self._serde.from_json(param.type, argument))
            except uniserde.SerdeError as err:
                raise InvalidArgumentsError(
                    f"Invalid value for parameter `{param.name}` of method `{function_meta.name}`: {err}",
                    error_code=STATUS_CODE_INVALID_PARAMS,
                    debug_object=serialized_arguments,
                ) from None

        return result
