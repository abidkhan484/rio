"""
Re-implementation of task groups so they can be used in Python versions before
3.11

If the built-in `asyncio.TaskGroup` is available, it will be used, otherwise a
custom implementation is used to fill the gap.
"""

from __future__ import annotations

import asyncio
import typing as t


class BaseExceptionGroup(Exception):
    """
    Base class for exceptions that contain multiple exceptions.
    """

    def __init__(
        self,
        message: str,
        exceptions: t.Iterable[BaseException],
    ) -> None:
        """
        Initialize the exception with a message and a list of exceptions.
        """
        super().__init__(message)
        self.exceptions = list(exceptions)


class ExceptionGroup(BaseExceptionGroup):
    """
    An exception that contains multiple exceptions.
    """

    pass


class TaskGroup:
    """
    A context manager that manages a group of tasks.

    This is a re-implementation of `asyncio.TaskGroup` for Python versions
    before 3.11. See [the Python
    docs](https://docs.python.org/3/library/asyncio-task.html#task-groups)
    for how to use it.
    """

    def __init__(self) -> None:
        """
        Initialize the TaskGroup with default values.
        """
        # Set of tasks managed by the TaskGroup
        self._tasks: set[asyncio.Task] = set()

        # List of exceptions raised by the tasks
        self._exceptions: list[BaseException] = []

        # Flag indicating if the TaskGroup has been entered
        self._entered: bool = False

        # Flag indicating if the TaskGroup is exiting
        self._exiting: bool = False

    async def __aenter__(self) -> TaskGroup:
        """
        Enter the runtime context related to this object.
        """
        self._entered = True
        return self

    async def __aexit__(
        self,
        exc_type: t.Type[BaseException],
        exc_val: BaseException,
        exc_tb: t.Any,
    ) -> bool:
        """
        Exit the runtime context related to this object.
        """
        self._exiting = True

        # Cancel remaining tasks *before* waiting for them
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete, gathering exceptions
        await asyncio.gather(*self._tasks, return_exceptions=True)

        # Process the results of the tasks
        for task in self._tasks:
            if task.done():
                # Collect exceptions raised by the tasks
                try:
                    task.result()

                # CancelledError is expected and should be ignored
                except asyncio.CancelledError:
                    pass

                # You're coming with me!
                except Exception as e:
                    self._exceptions.append(e)

        # Handle exceptions raised during the context
        if exc_type is not None and exc_type is not asyncio.CancelledError:
            self._exceptions.append(exc_val)

        # Raise exceptions if any were collected
        if self._exceptions:
            # Some base exceptions are extra special
            for e in self._exceptions:
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise e

            # Raise an ExceptionGroup or BaseExceptionGroup
            if all(isinstance(e, Exception) for e in self._exceptions):
                raise ExceptionGroup(
                    "TaskGroup raised exceptions",
                    self._exceptions,
                )
            else:
                raise BaseExceptionGroup(
                    "TaskGroup raised exceptions",
                    self._exceptions,
                )
        return False

    def create_task(
        self,
        coro: t.Coroutine,
        *,
        name: t.Optional[str] = None,
    ) -> asyncio.Task | None:
        """
        Creates a new task and runs it in the `TaskGroup`.
        """
        # If shutting down, no more tasks can be added
        if self._exiting:
            raise RuntimeError("This TaskGroup is shutting down")

        # Create and schedule the task
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)

        # Remove task from the set when done
        task.add_done_callback(self._tasks.discard)

        # Done!
        return task
