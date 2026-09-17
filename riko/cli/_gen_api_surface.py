# vim: sw=4:ts=4:expandtab
"""Generate the API-surface reference from the private contract declaration."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from riko.base import _api_surface
from riko.base._paths import ROOT_DIR

if TYPE_CHECKING:
    from collections.abc import Iterable

_DOC = ROOT_DIR / "_docs" / "API_SURFACE.md"
_BLOCK = re.compile(
    r"(?P<begin><!-- api-surface:(?P<key>[a-z-]+) -->\n).*?"
    r"(?P<end>\n<!-- /api-surface:(?P=key) -->)",
    re.DOTALL,
)


def _fence(*lines: str) -> str:
    body = "\n".join(lines)
    return f"```python\n{body}\n```"


def _sorted_repr(names: Iterable[str]) -> str:
    return repr(sorted(names))


def _render_block(key: str) -> str:
    if key == "stable-union":
        expr = "BADO | IO_ | COLLECTIONS | COMPILE | MODULES | OTHER | ROOT_EXCEPTIONS"
        lines = [f">>> STABLE == {expr}", "True"]
    elif key == "stable-disjoint":
        lines = [">>> STABLE.isdisjoint(EXTENSION)", "True"]
    elif key == "bado-namespace":
        lines = [
            ">>> sorted(BADO)",
            _sorted_repr(_api_surface.BADO),
            ">>> BADO == set(riko.bado.__all__)",
            "True",
        ]
    else:
        name = key.upper().replace("-", "_")
        lines = [f">>> sorted({name})", _sorted_repr(getattr(_api_surface, name))]

    return _fence(*lines)


def _replace(match: re.Match[str]) -> str:
    return f"{match['begin']}{_render_block(match['key'])}{match['end']}"


def generate_api_surface(text: str) -> str:
    """Render the API-surface document from the contract declaration."""
    return _BLOCK.sub(_replace, text)


def main() -> int:
    """Regenerate the API-surface reference document from the contract."""
    _DOC.write_text(generate_api_surface(_DOC.read_text()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
