import heapq
import time
from collections.abc import MutableMapping
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Tuple, TypeVar, Union

__all__ = [
    "TimerDict",
    "timedelta",
]


K = TypeVar("K")
V = TypeVar("V")


class TimerDict(MutableMapping[K, V]):
    """
    A dictionary-like class, which drops items after a set amount of time.
    """

    def __init__(self, default_duration: timedelta):
        assert isinstance(default_duration, timedelta), default_duration

        # For how long to keep the entries in the dict, if no duration is given
        # when adding a value.
        self.default_duration = default_duration

        # All entries stored in the dict
        #
        # When purging old values it is important to make sure no newer value
        # was added with longer duration. Thus each value also has a timestamp
        # set, which is checked before removing anything.
        self._entries: Dict[K, Tuple[float, V]] = {}

        # A queue of timestamps, used to quickly find the oldest entries
        self._timestamp_queue: List[Tuple[float, K]] = []

    def put(
        self,
        key: K,
        value: V,
        duration: Union[None, datetime, timedelta] = None,
    ) -> None:
        """
        Add a value to the dictionary, with explicit duration.

        Same as `__setitem__`, but allows to set the duration explicitly. If no
        duration is given, the dictionary's default duration is used. If the
        dictionary already contains a value for the given key, it is replaced
        and its duration is set to the new value.
        """
        # Wipe old entries
        self._purge_outdated()

        # Convert the duration to a timestamp
        if duration is None:
            timestamp = time.time() + self.default_duration.total_seconds()
        elif isinstance(duration, timedelta):
            timestamp = time.time() + duration.total_seconds()
        else:
            assert isinstance(duration, datetime), duration
            timestamp = duration.timestamp()

        self._entries[key] = (timestamp, value)
        heapq.heappush(self._timestamp_queue, (timestamp, key))

    def __getitem__(self, key: K) -> V:
        # Wipe old entries
        self._purge_outdated()

        # Try to get the value, raising a KeyError if it doesn't exist
        _, value = self._entries[key]
        return value

    def __setitem__(self, key: K, value: V) -> None:
        self.put(key, value)

    def __delitem__(self, key: K) -> None:
        del self._entries[key]

    def __iter__(self) -> Iterable[K]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def _purge_outdated(self) -> None:
        now = time.time()

        while self._timestamp_queue:
            # Get the lowest timestamp from the queue
            queue_timestamp, key = self._timestamp_queue[0]

            # It's not outdated yet, end the loop
            if queue_timestamp > now:
                break

            heapq.heappop(self._timestamp_queue)

            # Make sure the dict value hasn't been overwritten with a longer
            # lasting one in the meantime
            try:
                dict_timestamp, _ = self._entries[key]
            except KeyError:
                pass
            else:
                if dict_timestamp < now:
                    del self._entries[key]
