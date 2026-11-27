"""Provides central project policy, tunable runtime settings, and shared constants."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from math import inf, isnan
from multiprocessing import cpu_count
from os import environ
from types import MappingProxyType
from typing import TYPE_CHECKING

from ._logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping
    from logging import Logger

logger: Logger = get_logger(__name__)

type Limit = int | float

LAYER_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "base": (),
    "types": ("base",),
    "coercion": ("types",),
    "bado": ("types",),
    "definitions": ("types",),
    "io": ("bado", "coercion", "definitions"),
    "parsing": ("io",),
    "rss": ("parsing",),
    "execution": ("bado", "coercion", "definitions"),
    "runtime": ("execution", "parsing"),
    "modules": ("runtime", "rss"),
    "api": ("modules",),
    "cli": ("api",),
}

EXACT_LAYERS: dict[str, str] = {
    "riko": "api",
    "riko._package": "base",
    "riko.exceptions": "base",
}

PREFIX_LAYERS: dict[str, str] = {
    "riko.bado": "bado",
    "riko.base": "base",
    "riko.cli": "cli",
    "riko.coercion": "coercion",
    "riko.definitions": "definitions",
    "riko.ext": "modules",
    "riko.io": "io",
    "riko.modules": "modules",
    "riko.parsing": "parsing",
    "riko.rss": "rss",
    "riko.runtime": "runtime",
    "riko.execution": "execution",
    "riko.types": "types",
}

INPUT_PORT = "_INPUT"
OUTPUT_PORT = "_OUTPUT"
DEFAULT_OUTPUT = "default"
OTHER_PORT = "_OTHER"
OUTPUT_MODULE = "output"
SUBPIPE_TYPE = "pipe"
BUILTIN_PROVIDER = "riko"
LINE_LENGTH = 88
SINK_NAMES: frozenset[str] = frozenset({OUTPUT_MODULE, "write"})
PIPE_ID_PREFIXES: tuple[str, ...] = ("pipe_", "pipe:")
ASYNC_DOCTEST_MARKERS: tuple[str, ...] = ("async", "bado")

DUPLICATE_BASENAMES: frozenset[str] = frozenset(
    {"_async.py", "_sync.py", "_logging.py", "modules.py"}
)

FOREVER_ITEM: Mapping[str, bool] = MappingProxyType({"forever": True})


def get_worker_cnt(length: int = 0, *, threads: bool = True) -> int:
    """
    Computes a worker pool size, capped at the core count (doubled for threads).

    Kwargs:

        length: The number of items to spread across the pool, or zero when unknown.
        threads: Whether the pool uses threads rather than processes.

    Returns:

        The worker count.

    Examples:

        >>> from multiprocessing import cpu_count
        >>>
        >>> get_worker_cnt(1)
        1
        >>> get_worker_cnt() == 2 * get_worker_cnt(threads=False)
        True
        >>> get_worker_cnt(10_000) == get_worker_cnt(0) == 2 * cpu_count()
        True
        >>> get_worker_cnt(10_000, threads=False) == cpu_count()
        True

    """
    multiplier = 2 if threads else 1
    maximum = cpu_count() * multiplier
    return min(length, maximum) if length else maximum


def require_limit(value: object, what: str = "limit", *, minimum: int = 1) -> Limit:
    """
    Requires a whole-number limit of at least ``minimum``, or ``math.inf``.

    Args:

        value: The candidate limit.

    Kwargs:

        what: The name the error messages give the limit (default: "limit").
        minimum: The smallest whole number allowed (default: 1).

    Returns:

        The limit, unchanged.

    Raises:

        TypeError: If ``value`` is a bool, not a number, or a float other than
            ``math.inf``.

        ValueError: If ``value`` is an integer below ``minimum``.

    Examples:

        >>> from math import inf
        >>>
        >>> require_limit(4), require_limit(inf)
        (4, inf)
        >>> require_limit(0, "max_lag")
        Traceback (most recent call last):
        ...
        ValueError: max_lag must be at least 1, got 0
        >>> require_limit(2.5)
        Traceback (most recent call last):
        ...
        TypeError: limit must be an integer or math.inf, got 2.5

    """
    if isinstance(value, bool) or not (
        isinstance(value, int) or isinstance(value, float) and value == inf
    ):
        raise TypeError(f"{what} must be an integer or math.inf, got {value!r}")

    if isinstance(value, int) and value < minimum:
        raise ValueError(f"{what} must be at least {minimum}, got {value}")

    return value


def as_maxsize(bound: Limit) -> int | None:
    """
    Gets the ``lru_cache`` ``maxsize`` for a cache bound; ``inf`` means unbounded.

    Args:

        bound: A whole-number bound, or ``inf`` for no bound.

    Returns:

        The bound as an int, or ``None`` when it is infinite.

    Examples:

        >>> from math import inf
        >>>
        >>> as_maxsize(32)
        32
        >>> as_maxsize(inf)

    """
    return None if bound == inf else int(bound)


@dataclass(frozen=True, slots=True)
class Settings:
    """Operator-tunable runtime defaults, overridable via ``RIKO_*`` env vars."""

    concurrency_limit: int = 16
    node_threads: int = 40
    streaming_threshold: int = 1 * 1024 * 1024
    encoding: str = "utf-8"
    discovery_timeout: int = 10
    fetch_timeout: float = 30.0
    shutdown_timeout: float = 30.0
    exchange_api: str = "https://openexchangerates.org/api/latest.json"
    pickled_call_cache_size: Limit = 32
    parsed_date_cache_size: Limit = 1024
    strict_check_cache_size: Limit = 512
    return_kinds_cache_size: Limit = 256
    benchmark_delay: float = 0.1
    benchmark_workers: int = 0
    branch_buffer: Limit = 1024


def _warn_ignored(key: str, raw: object, expected: str) -> None:
    """Logs that the ``key`` override ``raw`` is ignored, saying what was expected."""
    logger.warning("ignoring %s=%r: %s", key, raw, expected)


def _env_int[D: int | None](
    env: Mapping[str, str], key: str, default: D, *, minimum: int | None = None
) -> int | D:
    """
    Reads an integer ``RIKO_*`` override.

    A malformed value or one below ``minimum`` logs a warning and keeps ``default``.
    """
    value = default

    if (raw := env.get(key)) is not None:
        try:
            parsed = int(raw)
        except ValueError:
            _warn_ignored(key, raw, "expected an integer")
        else:
            if minimum is not None and parsed < minimum:
                _warn_ignored(key, raw, f"expected at least {minimum}")
            else:
                value = parsed

    return value


def _env_bound(
    env: Mapping[str, str], key: str, default: Limit, *, minimum: int
) -> Limit:
    """
    Reads a whole-number bound ``RIKO_*`` override (``inf`` means no bound).

    A malformed, fractional, NaN, or negative value; or one below ``minimum``, logs a
    warning and keeps ``default``.
    """
    raw, value = env.get(key), default

    if raw is not None:
        try:
            try:
                parsed = int(raw)
            except ValueError:
                parsed = float(raw)

            value = require_limit(parsed, key, minimum=minimum)
        except (ValueError, TypeError) as error:
            _warn_ignored(key, raw, str(error))

    return value


def _env_float(
    env: Mapping[str, str], key: str, default: float, *, positive: bool = False
) -> float:
    """
    Reads a non-negative number ``RIKO_*`` override (``inf`` means no bound).

    A malformed, negative, or NaN value; or zero when ``positive`` is set, logs a
    warning and keeps ``default``.
    """
    raw, value, parsed = env.get(key), default, None

    if raw is not None:
        try:
            parsed = float(raw)
        except ValueError:
            _warn_ignored(key, raw, "expected a number")

        if parsed is None:
            pass
        elif isnan(parsed) or parsed < 0:
            _warn_ignored(key, raw, "expected a non-negative number")
        elif positive and parsed == 0:
            _warn_ignored(key, raw, "expected a positive number")
        else:
            value = parsed

    return value


def _env_encoding(env: Mapping[str, str], key: str, default: str) -> str:
    """
    Reads a text encoding ``RIKO_*`` override.

    An encoding Python does not know logs a warning and keeps ``default``.
    """
    raw, value = env.get(key), default

    if raw is not None:
        try:
            codecs.lookup(raw)
        except LookupError:
            _warn_ignored(key, raw, "unknown encoding")
        else:
            value = raw

    return value


def _env_str(env: Mapping[str, str], key: str, default: str) -> str:
    """Reads a string ``RIKO_*`` override, falling back to the default when unset."""
    return env.get(key, default)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """
    Loads ``Settings`` from defaults overlaid with ``RIKO_*`` env vars.

    Kwargs:

        env: The variables to read (default: the process environment).

    Returns:

        The settings, keeping the default for each malformed or out-of-range value.

    Examples:

        >>> load_settings({"RIKO_NODE_THREADS": "8"}).node_threads
        8

    """
    source = environ if env is None else env
    defaults = Settings()

    return Settings(
        concurrency_limit=_env_int(
            source, "RIKO_CONCURRENCY_LIMIT", defaults.concurrency_limit, minimum=1
        ),
        node_threads=_env_int(
            source, "RIKO_NODE_THREADS", defaults.node_threads, minimum=0
        ),
        streaming_threshold=_env_int(
            source, "RIKO_STREAMING_THRESHOLD", defaults.streaming_threshold, minimum=0
        ),
        encoding=_env_encoding(source, "RIKO_ENCODING", defaults.encoding),
        discovery_timeout=_env_int(
            source, "RIKO_DISCOVERY_TIMEOUT", defaults.discovery_timeout, minimum=1
        ),
        fetch_timeout=_env_float(
            source, "RIKO_FETCH_TIMEOUT", defaults.fetch_timeout, positive=True
        ),
        shutdown_timeout=_env_float(
            source, "RIKO_SHUTDOWN_TIMEOUT", defaults.shutdown_timeout
        ),
        exchange_api=_env_str(source, "RIKO_EXCHANGE_API", defaults.exchange_api),
        pickled_call_cache_size=_env_bound(
            source,
            "RIKO_PICKLED_CALL_CACHE_SIZE",
            defaults.pickled_call_cache_size,
            minimum=1,
        ),
        parsed_date_cache_size=_env_bound(
            source,
            "RIKO_PARSED_DATE_CACHE_SIZE",
            defaults.parsed_date_cache_size,
            minimum=1,
        ),
        strict_check_cache_size=_env_bound(
            source,
            "RIKO_STRICT_CHECK_CACHE_SIZE",
            defaults.strict_check_cache_size,
            minimum=1,
        ),
        return_kinds_cache_size=_env_bound(
            source,
            "RIKO_RETURN_KINDS_CACHE_SIZE",
            defaults.return_kinds_cache_size,
            minimum=1,
        ),
        benchmark_delay=_env_float(
            source, "RIKO_BENCHMARK_DELAY", defaults.benchmark_delay
        ),
        benchmark_workers=_env_int(
            source, "RIKO_BENCHMARK_WORKERS", defaults.benchmark_workers, minimum=0
        ),
        branch_buffer=_env_bound(
            source, "RIKO_BRANCH_BUFFER", defaults.branch_buffer, minimum=1
        ),
    )


settings = load_settings()

DEF_CONCURRENCY_LIMIT = settings.concurrency_limit
STREAMING_THRESHOLD = settings.streaming_threshold
ENCODING = settings.encoding
