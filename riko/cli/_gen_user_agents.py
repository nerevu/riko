# vim: sw=4:ts=4:expandtab
"""Generates the random user-agent pools from fake-useragent's bundled data."""

from __future__ import annotations

from collections import Counter
from importlib.metadata import version
from importlib.resources import files
from itertools import starmap
from json import loads
from typing import TYPE_CHECKING

from riko.base._config import LINE_LENGTH
from riko.base._guards import is_mapping
from riko.base._paths import USER_AGENTS_PATH
from riko.base._require_guards import require_instance, require_str
from riko.base._strutils import get_codegen_note, ruff_format, wrap_words
from riko.types._enums import UserAgent

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

_DISTRIBUTION = "fake-useragent"
_DATA_PACKAGE = "fake_useragent.data"
_DATA_FILE = "browsers.jsonl"
_DEVICES = (UserAgent.DESKTOP, UserAgent.MOBILE)
_SHARE_SCALE = 10**9
_INDENT = " " * 8
_WIDTH = LINE_LENGTH - len(_INDENT) - 4
USER_AGENT_COUNT = 20


def _gen_shares(text: str, device: str) -> Iterator[tuple[str, int]]:
    for line in filter(None, text.splitlines()):
        row: object = loads(line)

        if is_mapping(row) and row.get("type") == device:
            share = require_instance(float, row.get("percent"), "percent")
            agent = require_str(row.get("useragent"), "useragent")
            yield (agent, round(share * _SHARE_SCALE))


def get_top_agents(text: str, device: str, count: int = USER_AGENT_COUNT) -> list[str]:
    """
    Gets the most common distinct agents of one device type from fake-useragent's data.

    Args:

        text: The ``browsers.jsonl`` content, one JSON record per line.
        device: The record ``type`` to keep, such as ``"desktop"`` or ``"mobile"``.

    Kwargs:

        count: How many agents to keep.

    Returns:

        The agents ordered by total usage share across their records. Ties are ordered
        by first appearance.

    Examples:

        >>> text = "\\n".join([
        ...     '{"useragent": "b", "percent": 1.0, "type": "desktop"}',
        ...     '{"useragent": "c", "percent": 1.2, "type": "desktop"}',
        ...     '{"useragent": "a", "percent": 1.2, "type": "desktop"}',
        ...     '{"useragent": "m", "percent": 9.0, "type": "mobile"}',
        ...     '{"useragent": "b", "percent": 0.5, "type": "desktop"}',
        ... ])
        >>> get_top_agents(text, "desktop")
        ['b', 'c', 'a']
        >>> get_top_agents(text, "mobile")
        ['m']

    """
    shares = Counter[str]()

    for agent, share in _gen_shares(text, device):
        shares[agent] += share

    return [agent for agent, _ in shares.most_common(count)]


def _render(agent: str) -> str:
    pieces = wrap_words(agent, _WIDTH, lossless=True)
    joined = "\n".join(f"{_INDENT}{piece!r}" for piece in pieces)
    return f"    (\n{joined}\n    )," if len(pieces) > 1 else f"    {agent!r},"


def _render_pool(device: str, agents: Iterable[str]) -> str:
    entries = "\n".join(map(_render, agents))
    return f"{device.upper()}_USER_AGENTS: tuple[str, ...] = (\n{entries}\n)"


def generate_user_agents(
    pools: Mapping[UserAgent, Iterable[str]], source_version: str
) -> str:
    """
    Generates the source of the module that lists the random user-agent pools.

    Args:

        pools: The user agents of each device type, in order.
        source_version: The fake-useragent release the agents come from.

    Returns:

        The formatted module source, with one ``<DEVICE>_USER_AGENTS`` tuple per
        device type.

    Examples:

        >>> pools = {UserAgent.DESKTOP: ["riko/1.0"]}
        >>> source = generate_user_agents(pools, "2.2.0")
        >>> "fake-useragent 2.2.0" in source
        True
        >>> print(source.splitlines()[-1])
        DESKTOP_USER_AGENTS: tuple[str, ...] = ("riko/1.0",)

    """
    prog = f"fake-useragent {source_version}"
    header = [
        f"# {get_codegen_note('--user-agents')}",
        "",
        f'"""{prog}\'s most common user agents ordered by usage share."""',
    ]
    blocks = "\n\n".join(starmap(_render_pool, pools.items()))
    return ruff_format("\n".join([*header, blocks, ""]))


def load_user_agents() -> str:
    """
    Loads fake-useragent's bundled data and generates the user-agent module.

    Returns:

        The formatted module source.

    Raises:

        ModuleNotFoundError: If fake-useragent is not installed.

    """
    text = files(_DATA_PACKAGE).joinpath(_DATA_FILE).read_text()
    pools = {device: get_top_agents(text, device) for device in _DEVICES}
    return generate_user_agents(pools, version(_DISTRIBUTION))


def main() -> int:
    """Regenerates the random user-agent pools from fake-useragent's data."""
    return 0 if USER_AGENTS_PATH.write_text(load_user_agents()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
