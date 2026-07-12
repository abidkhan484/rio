import asyncio
import threading
import typing as t

# Try to import the built-in TaskGroup from asyncio, falling back to the bundled
# backport if it's not available.
try:
    from asyncio import (
        BaseExceptionGroup as BaseExceptionGroup,  # type: ignore (Handled below)
    )
    from asyncio import (
        ExceptionGroup as ExceptionGroup,  # type: ignore (Handled below)
    )
    from asyncio import (
        TaskGroup as TaskGroup,  # type: ignore (Handled below)
    )
except ImportError:
    from ._task_group import (
        BaseExceptionGroup as BaseExceptionGroup,
    )
    from ._task_group import (
        ExceptionGroup as ExceptionGroup,
    )
    from ._task_group import (
        TaskGroup as TaskGroup,
    )

T = t.TypeVar("T")

T = t.TypeVar("T")
IN = t.TypeVar("IN")
OUT = t.TypeVar("OUT")


async def collect(
    values: t.AsyncIterable[IN],
    *,
    limit: int | None = None,
) -> list[IN]:
    """
    Collects the values from an asynchronous iterable into a list.

    If `limit` is set, the result will contain at most the first `limit` values.

    ## Parameters

    `values`: The asynchronous iterable to collect values from.

    `limit`: The maximum number of values to collect. If `None`, all values will
        be collected.
    """
    result: list[IN] = []

    async for value in values:
        result.append(value)

        if len(result) == limit:
            break

    return result


async def amap(
    func: t.Callable[[IN], t.Awaitable[OUT]],
    values: t.Iterable[IN],
    *,
    concurrency: int = 10,
) -> t.AsyncIterable[OUT]:
    """
    Asynchronously maps `func` over `values`, with at most `concurrency` items
    being processed simultaneously.

    ## Parameters

    `func`: The function to apply to each value.

    `values`: The values to apply the function to.

    `concurrency`: The maximum number of items to process simultaneously.
    """
    # TODO: Support async iterables for the input

    # Processes a single value. Returns both the index and the result.
    async def process_single(index: int, value: IN) -> tuple[int, OUT]:
        result = await func(value)
        return index, result

    # Yield values as they become available - however, make sure to raise asap
    # if any task fails
    to_do: list[tuple[int, IN]] = list(enumerate(values))
    in_flight: set[asyncio.Task[tuple[int, OUT]]] = set()

    n_already_yielded: int = 0
    not_yet_yielded: dict[int, OUT] = {}

    while True:
        # Spawn tasks until the limit is reached
        while len(in_flight) < concurrency:
            try:
                index, value = to_do.pop(0)
            except IndexError:
                break

            in_flight.add(
                asyncio.create_task(
                    process_single(
                        index,
                        value,
                    )
                )
            )

        # Done?
        if not in_flight and not to_do:
            break

        # Wait for any task to complete
        done, in_flight = await asyncio.wait(
            in_flight,
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Add any completed tasks to the results
        for task in done:
            # Pass-through exceptions
            try:
                index, result = task.result()
            except Exception:
                for task in in_flight:
                    task.cancel()

                raise

            # Store the result
            assert index >= n_already_yielded, (
                index,
                n_already_yielded,
                not_yet_yielded,
            )
            not_yet_yielded[index] = result

        # Yield any results that are now available
        while True:
            try:
                value = not_yet_yielded.pop(n_already_yielded)
            except KeyError:
                break
            else:
                n_already_yielded += 1
                yield value


async def iterator_to_thread(
    sync_iterable: t.Iterable[T],
    *,
    batch_size: int,
) -> t.AsyncIterable[T]:
    """
    Given a potentially slow, synchronous iterator, returns an equivalent
    asynchronous iterator.

    The synchronous iterator will be run in a separate thread, and the results
    retrieved asynchronously. To decrease overhead, values from the synchronous
    iterator are fetched in batches. This means that values won't be yielded
    until `batch_size` values have been collected, or the iterator is exhausted.
    If this behavior isn't desirable in your application, set `batch_size` to
    `1`.

    Exceptions from the synchronous iterator will be propagated.
    """
    assert batch_size > 0, "Batch size must be positive"

    mainloop = asyncio.get_event_loop()
    results: asyncio.Queue[
        tuple[t.Literal["values"], list[T]]
        | tuple[t.Literal["error"], Exception]
        | tuple[t.Literal["done"]]
    ] = asyncio.Queue()
    stop_requested = False

    # The worker function continuously fills the queue with results. It is
    # limited by the buffer size.
    def worker():
        sync_iterator = iter(sync_iterable)
        batch: list[T] = []

        while True:
            # Try to get some values from the iterator
            try:
                batch.append(next(sync_iterator))

            # Done?
            except StopIteration:
                mainloop.call_soon_threadsafe(results.put_nowait, ("values", batch))
                mainloop.call_soon_threadsafe(results.put_nowait, ("done",))
                return

            # Handle errors
            except Exception as e:
                mainloop.call_soon_threadsafe(results.put_nowait, ("values", batch))
                mainloop.call_soon_threadsafe(results.put_nowait, ("error", e))
                return

            # If the batch is full, pass it on
            if len(batch) >= batch_size:
                mainloop.call_soon_threadsafe(results.put_nowait, ("values", batch))
                batch = []

            # If the stop was requested, pass on the remaining values
            if stop_requested:
                mainloop.call_soon_threadsafe(results.put_nowait, ("values", batch))
                mainloop.call_soon_threadsafe(results.put_nowait, ("done",))
                return

    worker_thread = threading.Thread(target=worker, daemon=True)

    # The remainder of the function has to be wrapped to ensure the thread is
    # stopped if anything goes wrong.
    try:
        worker_thread.start()

        while True:
            # Wait for the next result
            result = await results.get()

            # Yield the values
            if result[0] == "values":
                for value in result[1]:
                    yield value

            # Handle errors
            elif result[0] == "error":
                raise result[1]

            # Done
            elif result[0] == "done":
                return

            # Invalid
            else:
                assert False, f"Received invalid result `{result!r}`"

    finally:
        stop_requested = True


async def multitask(*coroutines: t.Awaitable[t.Any]) -> None:
    """
    **This function is deprecated. Use task groups instead.**

    Run multiple coroutines concurrently. When either completes, all others are
    canceled as well. If any coroutine raises an exception, they also all stop,
    and the exception is re-raised.

    This effectively allows you to run multiple streams of code at once,
    without having to worry about some of them living on when they're supposed
    to finish.

    If no coroutines are provided, the function returns immediately.

    Warning: While most exceptions are propagated, `asyncio.CancelledError` is
        not. That's because this exception is raised under normal circumstances
        simply when this function shuts down a coroutine.

    ## Raises

    `BaseException`: Any exceptions raised by the coroutines.
    """
    # Special case: If no coroutines are provided, the function is finished.
    # Avoid all of the overhead below, especially since some of the functions
    # probably aren't too happy about empty sets.
    if not coroutines:
        return

    # Create a task for each coroutine
    tasks = {asyncio.create_task(coro) for coro in coroutines}  # type: ignore

    # Run them all
    try:
        await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

    # Make sure all tasks are canceled prior to returning
    finally:
        # Cancel any pending tasks
        for task in tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to be canceled
        exception_to_raise: BaseException | None = None

        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                # CancelledErrors are to be expected. They don't signal that
                # something has gone wrong, but simply that the task was
                # canceled, likely by this very function.
                pass
            except BaseException as err:
                exception_to_raise = err

        # Propagate any exceptions
        if exception_to_raise is not None:
            raise exception_to_raise


async def to_daemon_thread(
    func: t.Callable[..., T],
    *args: t.Any,
    **kwargs: t.Any,
) -> T:
    """
    Like `asyncio.to_thread`, but the thread is a daemon. This means that the
    thread will be automatically stopped when no other non-daemon threads are
    running.
    """
    loop = asyncio.get_running_loop()
    future = asyncio.Future()

    # Create a function to run in the thread. It will release the future once
    # done.
    def run() -> None:
        try:
            result = func(*args, **kwargs)
            loop.call_soon_threadsafe(future.set_result, result)
        except Exception as e:
            loop.call_soon_threadsafe(future.set_exception, e)

    # Get busy
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    # Wait for the result
    return await future
