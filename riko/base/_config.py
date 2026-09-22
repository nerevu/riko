"""Provides central project policy and operator-tunable runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from logging import getLogger
from os import environ
from typing import TYPE_CHECKING

from ._paths import ROOT_DIR

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = getLogger("riko")

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

EXACT_LAYERS: dict[str, str] = {
    "riko": "api",
    "riko._package": "base",
    "riko.runtime._resources": "execution",
    "riko.runtime.context": "execution",
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
    "riko.types": "types",
}

INPUT_PORT = "_INPUT"
OUTPUT_PORT = "_OUTPUT"
OTHER_PORT = "_OTHER"
OUTPUT_MODULE = "output"

SINK_NAMES: frozenset[str] = frozenset({OUTPUT_MODULE, "write"})

SUBPIPE_TYPE = "pipe"

PIPELINE_DIRS = (
    (ROOT_DIR / "tests" / "pipelines", ROOT_DIR / "tests" / "pypipelines"),
    (ROOT_DIR / "examples" / "pipelines", ROOT_DIR / "examples" / "pypipelines"),
)


@dataclass(frozen=True, slots=True)
class Settings:
    """Operator-tunable runtime defaults, overridable via ``RIKO_*`` env vars."""

    connection_count: int = 16
    streaming_threshold: int = 1 * 1024 * 1024
    encoding: str = "utf-8"
    discovery_timeout: int = 10
    exchange_api: str = "https://openexchangerates.org/api/latest.json"


def _env_int(env: Mapping[str, str], key: str, default: int) -> int:
    """Reads an integer ``RIKO_*`` override, warning and falling back when malformed."""
    raw = env.get(key)

    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            logger.warning("ignoring %s=%r: expected an integer", key, raw)
            value = default

    return value


def _env_str(env: Mapping[str, str], key: str, default: str) -> str:
    """Reads a string ``RIKO_*`` override, falling back to the default when unset."""
    return env.get(key, default)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Builds ``Settings`` from defaults overlaid with ``RIKO_*`` env vars."""
    source = environ if env is None else env
    defaults = Settings()
    return Settings(
        connection_count=_env_int(
            source, "RIKO_CONNECTION_COUNT", defaults.connection_count
        ),
        streaming_threshold=_env_int(
            source, "RIKO_STREAMING_THRESHOLD", defaults.streaming_threshold
        ),
        encoding=_env_str(source, "RIKO_ENCODING", defaults.encoding),
        discovery_timeout=_env_int(
            source, "RIKO_DISCOVERY_TIMEOUT", defaults.discovery_timeout
        ),
        exchange_api=_env_str(source, "RIKO_EXCHANGE_API", defaults.exchange_api),
    )


settings = load_settings()
