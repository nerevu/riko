"""Provides central project policy, tunable runtime settings, and shared constants."""

from __future__ import annotations

from dataclasses import dataclass
from math import isnan
from multiprocessing import cpu_count
from os import environ
from types import MappingProxyType
from typing import TYPE_CHECKING

from ._logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping
    from logging import Logger

logger: Logger = get_logger(__name__)

LAYER_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "base": (),
    "types": ("base",),
    "coercion": ("types",),
    "bado": ("types",),
    "definitions": ("types",),
    "io": ("coercion", "bado", "definitions"),
    "parsing": ("io",),
    "rss": ("parsing",),
    "execution": ("bado", "definitions"),
    "runtime": ("execution", "parsing"),
    "modules": ("runtime", "rss"),
    "api": ("modules",),
    "cli": ("api",),
}

EXACT_LAYERS: dict[str, str] = {"riko": "api", "riko._package": "base"}

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
OTHER_PORT = "_OTHER"
OUTPUT_MODULE = "output"
SUBPIPE_TYPE = "pipe"
BUILTIN_PROVIDER = "riko"
SINK_NAMES: frozenset[str] = frozenset({OUTPUT_MODULE, "write"})
PIPE_ID_PREFIXES: tuple[str, ...] = ("pipe_", "pipe:")

DUPLICATE_BASENAMES: frozenset[str] = frozenset(
    {"_async.py", "_sync.py", "_logging.py", "modules.py"}
)

FOREVER_ITEM: Mapping[str, bool] = MappingProxyType({"forever": True})


def get_worker_cnt(length: int = 0, *, threads: bool = True) -> int:
    """
    Computes a worker pool size, capped at the core count (doubled for threads).

    Args:

        length: The number of items to spread across the pool, or zero when unknown.
        threads: Whether the pool uses threads rather than processes.

    Returns:

        The worker count.

    Examples:

        >>> from multiprocessing import cpu_count
        >>>
        >>> get_worker_cnt(1), get_worker_cnt() == 2 * get_worker_cnt(threads=False)
        (1, True)
        >>> get_worker_cnt(10_000) == get_worker_cnt(0) == 2 * cpu_count()
        True
        >>> get_worker_cnt(10_000, threads=False) == cpu_count()
        True

    """
    multiplier = 2 if threads else 1
    maximum = cpu_count() * multiplier
    return min(length, maximum) if length else maximum


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
    shipped_call_cache_size: int = 32
    parsed_date_cache_size: int = 1024
    benchmark_delay: float = 0.1


def _env_int(
    env: Mapping[str, str], key: str, default: int, *, minimum: int | None = None
) -> int:
    """
    Reads an integer ``RIKO_*`` override.

    A malformed value, or one below ``minimum``, logs a warning and keeps ``default``.
    """
    raw = env.get(key)

    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            logger.warning("ignoring %s=%r: expected an integer", key, raw)
            value = default

        if minimum is not None and value < minimum:
            logger.warning("ignoring %s=%r: expected at least %d", key, raw, minimum)
            value = default

    return value


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    """
    Reads a non-negative number ``RIKO_*`` override; ``inf`` means no bound.

    A malformed, negative, or NaN value logs a warning and keeps ``default``.
    """
    raw = env.get(key)

    if raw is None:
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            logger.warning("ignoring %s=%r: expected a number", key, raw)
            value = default

        if isnan(value) or value < 0:
            logger.warning("ignoring %s=%r: expected a non-negative number", key, raw)
            value = default

    return value


def _env_str(env: Mapping[str, str], key: str, default: str) -> str:
    """Reads a string ``RIKO_*`` override, falling back to the default when unset."""
    return env.get(key, default)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """
    Loads ``Settings`` from defaults overlaid with ``RIKO_*`` env vars.

    Args:

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
        encoding=_env_str(source, "RIKO_ENCODING", defaults.encoding),
        discovery_timeout=_env_int(
            source, "RIKO_DISCOVERY_TIMEOUT", defaults.discovery_timeout, minimum=1
        ),
        fetch_timeout=_env_float(source, "RIKO_FETCH_TIMEOUT", defaults.fetch_timeout),
        shutdown_timeout=_env_float(
            source, "RIKO_SHUTDOWN_TIMEOUT", defaults.shutdown_timeout
        ),
        exchange_api=_env_str(source, "RIKO_EXCHANGE_API", defaults.exchange_api),
        shipped_call_cache_size=_env_int(
            source,
            "RIKO_SHIPPED_CALL_CACHE_SIZE",
            defaults.shipped_call_cache_size,
            minimum=0,
        ),
        parsed_date_cache_size=_env_int(
            source,
            "RIKO_PARSED_DATE_CACHE_SIZE",
            defaults.parsed_date_cache_size,
            minimum=0,
        ),
        benchmark_delay=_env_float(
            source, "RIKO_BENCHMARK_DELAY", defaults.benchmark_delay
        ),
    )


settings = load_settings()

DEF_CONCURRENCY_LIMIT = settings.concurrency_limit
STREAMING_THRESHOLD = settings.streaming_threshold
ENCODING = settings.encoding
