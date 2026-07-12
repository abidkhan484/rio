"""
Utilities for setting up Python's weirdo logging system. Including logging to
MongoDB if you feel crazy.
"""

from __future__ import annotations

import atexit
import dataclasses
import logging
import logging.handlers
import queue
import socket
import threading
import time
import typing as t
import weakref
from datetime import datetime, timezone
from pathlib import Path

from . import async_utils

try:
    import pymongo.collection
    import uniserde
    from uniserde import BsonDoc, ObjectId
except ImportError:
    if t.TYPE_CHECKING:
        import pymongo.collection
        import uniserde
        from uniserde import BsonDoc, ObjectId
else:
    bson_serde = uniserde.BsonSerde.new_camel_case()


__all__ = [
    "LogLevel",
    "LOG_LEVEL_NAMES",
    "LOG_LEVEL_ANNOUNCEMENT",
    "Environment",
    "levels_greater_than_or_equal",
    "MongoDbLogger",
    "setup_logging",
]


T = t.TypeVar("T")


LogLevel: t.TypeAlias = t.Literal[
    "debug",
    "info",
    "announcement",
    "warning",
    "error",
    "critical",
]
LOG_LEVEL_NAMES = t.get_args(LogLevel)  # In ascending order!

# Add the announcement level to the logging module
LOG_LEVEL_ANNOUNCEMENT = (logging.INFO + logging.WARNING) // 2
logging.addLevelName(LOG_LEVEL_ANNOUNCEMENT, "ANNOUNCEMENT")

Environment: t.TypeAlias = t.Literal["development", "production"]


# Keep track of all living persistence loggers, so they can be flushed at exit
_ALL_MONGODB_LOGGERS: weakref.WeakSet[MongoDbLogger] = weakref.WeakSet()


@atexit.register
def _flush_all_persistence_loggers() -> None:
    for logger in _ALL_MONGODB_LOGGERS:
        logger.flush_sync()


def _log_level_to_python(level: LogLevel) -> int:
    return logging.getLevelName(level.upper())


def _log_level_from_python(level: int) -> LogLevel:
    result = logging.getLevelName(level).lower()
    assert result in LOG_LEVEL_NAMES, f"Unknown log level: {result}"
    return result  # type: ignore


def levels_greater_than_or_equal(level: LogLevel) -> set[LogLevel]:
    """
    Returns a set containing all log levels which are at least as severe as the
    given one.

    ## Raises

    `ValueError`: if the given level is not a valid log level.
    """
    for ii, name in enumerate(LOG_LEVEL_NAMES):
        if name == level:
            return set(LOG_LEVEL_NAMES[ii:])

    raise ValueError(f"Unknown log level: {level}")


@dataclasses.dataclass
class LogEntry:
    """
    Represents a single log entry in the database.
    """

    # Unique identifier for the log entry
    id: ObjectId

    # When this log entry was created
    timestamp: datetime

    # Whether this log entry was created in development or production
    environment: Environment

    # Which machine created this log entry
    host: str

    # The app that created this log entry
    app: str

    # The severity of this log entry
    level: LogLevel

    # A human-readable message. This is the main content of the log entry
    message: str

    # Arbitrary additional data
    payload: dict[str, t.Any]


class MongoDbLogger(logging.StreamHandler):
    """
    Logger, which stores its entries in a MongoDB database.

    Database access is asynchronous, and likely on another server. `await`ing
    every log operation would be incredibly slow. Instead, this logger only
    synchronously queues log entries, and then later asynchronously copies them
    to the database.
    """

    def __init__(
        self,
        collection: pymongo.collection.Collection,
        *,
        environment: Environment,
        app: str,
        host: str | None = None,
    ):
        super().__init__()

        self._sync_collection = collection

        self._host = socket.gethostname() if host is None else host
        self._environment: Environment = environment
        self._app = app

        self._last_log_writeback_time_monotonic = time.monotonic()
        self._pending_log_entries: queue.Queue[LogEntry] = queue.Queue()

        self._writeback_thread = threading.Thread(
            target=self._writeback_worker, daemon=True
        )
        self._writeback_thread.start()

        # Log entries are plentiful. Make sure there's an index
        collection.create_index([("timestamp", 1)])

        # Keep track of all living persistence loggers
        _ALL_MONGODB_LOGGERS.add(self)

    def __del__(self) -> None:
        self.flush_sync()

    def create_log_entries_sync(self, entries: t.Iterable[LogEntry]) -> None:
        """
        Batch creates new log entries in the database.

        The entries need to have unique ids among all entries in the database.
        This is not checked for performance reasons.
        """
        # MongoDB doesn't like empty inserts
        entry_data = [bson_serde.as_bson(entry) for entry in entries]

        if not entry_data:
            return

        # Insert the entries
        self._sync_collection.insert_many(entry_data)

    def flush_sync(self) -> None:
        """
        Copies any not yet stored log entries into the database.
        """
        # Move the log entries into a local variable
        in_flight_entries = []

        while True:
            try:
                in_flight_entries.append(self._pending_log_entries.get_nowait())
            except queue.Empty:
                break

        # Try to push the entries into the database
        try:
            self.create_log_entries_sync(in_flight_entries)

        # If the operation fails, put the entries back into the queue so they
        # can be retried later
        except Exception:
            for entry in in_flight_entries:
                self._pending_log_entries.put(entry)

            raise

    def _writeback_worker(self) -> None:
        # Keep copying entries forever. There is no need to return because the
        # thread is daemonized.
        #
        # TODO: What if the logger is deleted? This isn't currently supported.
        CYCLE_TIME = 10

        while True:
            # Wait some time before writing back. This batches log entries
            # together.
            now = time.monotonic()
            sleep_time = CYCLE_TIME - (now - self._last_log_writeback_time_monotonic)

            if sleep_time > 0:
                time.sleep(sleep_time)

            # Copy the pending log entries into the database
            try:
                self.flush_sync()
            except Exception as e:
                logging.error(f"Error writing back log entries: {e}")

                # Wait a bit before retrying
                time.sleep(20)

            # Housekeeping
            self._last_log_writeback_time_monotonic = time.monotonic()

    def queue_log(
        self,
        level: LogLevel,
        message: str,
        *,
        payload: dict[str, t.Any] | None = None,
    ) -> None:
        """
        Creates a log entry and queues it for storage to the database. The entry
        will be created later, or once `flush` is called.
        """
        self._pending_log_entries.put(
            LogEntry(
                id=ObjectId(),
                timestamp=datetime.now(timezone.utc),
                environment=self._environment,
                host=self._host,
                app=self._app,
                level=level,
                message=message,
                payload={} if payload is None else payload,
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        """
        For compatibility with python's logging module.
        """

        self.queue_log(
            level=_log_level_from_python(record.levelno),
            message=record.message,
        )

    def find_log_entries(
        self,
        *,
        environment: Environment | None = None,
        levels: t.Iterable[LogLevel] | None = None,
        newer_than: datetime | None = None,
        older_than: datetime | None = None,
        limit: int | None = None,
    ) -> t.AsyncIterable[LogEntry]:
        """
        Returns an async iterator over all log entries in the database matching
        the given filters.

        The entries are sorted by timestamp, with the most recent entries first.
        """
        # Build the query
        query: BsonDoc = {}

        if environment is not None:
            query["environment"] = bson_serde.as_bson(environment)

        if levels is not None:
            query["level"] = {"$in": [bson_serde.as_bson(level) for level in levels]}

        if newer_than is not None:
            query["timestamp"] = {"$gt": newer_than}

        if older_than is not None:
            query["timestamp"] = {"$lt": older_than}

        # Yield all matches
        def sync_iterator() -> t.Iterator[LogEntry]:
            cursor = self._sync_collection.find(query).sort([("timestamp", -1)])

            if limit is not None:
                cursor = cursor.limit(limit)

            for doc in cursor:
                yield bson_serde.from_bson(LogEntry, doc)

        return async_utils.iterator_to_thread(sync_iterator(), batch_size=50)

    def watch_log_entries(
        self,
        *,
        environment: Environment | None = None,
        levels: t.Iterable[LogLevel] | None = None,
    ) -> t.AsyncIterable[LogEntry]:
        """
        Returns an async iterator over all new log entries in the database
        matching the given filters.

        The iterator will block until new log entries are available.
        """
        # Build the filter pipeline
        query: BsonDoc = {"operationType": "insert"}

        if environment is not None:
            query["fullDocument.environment"] = bson_serde.as_bson(environment)

        if levels is not None:
            query["fullDocument.level"] = {
                "$in": [bson_serde.as_bson(level) for level in levels]
            }

        pipeline = [
            {
                "$match": query,
            }
        ]

        # Watch for changes
        def sync_iterator() -> t.Iterator[LogEntry]:
            for change in self._sync_collection.watch(pipeline=pipeline):
                yield bson_serde.from_bson(
                    LogEntry,
                    change["fullDocument"],
                )

        return async_utils.iterator_to_thread(sync_iterator(), batch_size=1)


def reset_logging() -> None:
    """
    Resets the logging system to its initial state. This removes all handlers
    from the root logger and resets its level to `WARNING`.
    """

    # Get the root logger
    root_logger = logging.getLogger()

    # Remove all existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Reset the root logger level
    root_logger.setLevel(logging.WARNING)


@t.overload
def setup_logging(
    *,
    info_log_path: Path | None = None,
    debug_log_path: Path | None = None,
    stdout_log_level: LogLevel = "info",
) -> MongoDbLogger: ...


@t.overload
def setup_logging(
    *,
    info_log_path: Path | None = None,
    debug_log_path: Path | None = None,
    database_collection: pymongo.collection.Collection,
    database_app: str,
    database_environment: Environment,
    database_host: str | None = None,
    stdout_log_level: LogLevel = "info",
    database_log_level: LogLevel = "debug",
) -> MongoDbLogger: ...


def setup_logging(
    *,
    info_log_path: Path | None = None,
    debug_log_path: Path | None = None,
    database_collection: pymongo.collection.Collection | None = None,
    database_app: str | None = None,
    database_environment: Environment | None = None,
    database_host: str | None = None,
    stdout_log_level: LogLevel = "info",
    database_log_level: LogLevel = "debug",
) -> MongoDbLogger | None:
    """
    Creates a nice logging setup. Any previously registered handlers are
    removed, which means it is safe to call this function multiple times without
    creating duplicate log entries.

    - INFO logs to `info_log_path`, keeping logs indefinitely
    - Configurable logs to `stdout`, INFO by default
    - DEBUG logs to `debug_log_path`, keeping a limited number of days
    - DEBUG logs into the database, if a collection is provided

    Returns the database logger, if one was created.

    ## Parameters

    `info_log_path`: Path to the info log file

    `debug_log_path`: Path to the debug log file

    `database_collection`: The MongoDB collection to store logs in

    `database_app`: The running app's name. This will be added to logged
        entries in the database

    `database_environment`: The environment that will appear in the database
        log entries. This will allow you to distinguish between development and
        production logs.

    `database_host`: Override for the machine's name that will appear in the
        database log entries. If not provided, the machine's hostname will be
        used.

    `stdout_log_level`: The minimum log level to display on stdout

    `database_log_level`: The minimum log level to store in the database
    """

    # Make sure not to add multiple handlers if the function is called multiple
    # times.
    reset_logging()

    # Configure the root logger and prepare some values
    root_logger = logging.getLogger("")
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")

    # Info -> file
    if info_log_path is not None:
        info_log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.handlers.TimedRotatingFileHandler(
            info_log_path,
            encoding="utf-8",
            when="midnight",
            utc=True,
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Stdout (configurable)
    handler = logging.StreamHandler()
    handler.setLevel(_log_level_to_python(stdout_log_level))
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Debug -> file
    if debug_log_path is not None:
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = logging.handlers.TimedRotatingFileHandler(
            debug_log_path,
            encoding="utf-8",
            when="midnight",
            utc=True,
            backupCount=7,
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Database
    if database_collection is None:
        pers_logger = None
    else:
        assert (
            database_environment is not None
        ), "Must provide an environment when logging to a database"

        assert (
            database_app is not None
        ), "Must provide an app name when logging to a database"

        pers_logger = MongoDbLogger(
            database_collection,
            host=database_host,
            environment=database_environment,
            app=database_app,
        )

        pers_logger.setLevel(_log_level_to_python(database_log_level))
        root_logger.addHandler(pers_logger)

    return pers_logger
