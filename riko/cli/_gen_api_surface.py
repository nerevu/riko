# vim: sw=4:ts=4:expandtab
"""Generates the API-surface reference from its contract declarations."""

from __future__ import annotations

from riko.base import _api_surface
from riko.base._paths import API_SURFACE_PATH
from riko.base._strutils import get_codegen_note

from ._gen_blocks import build_block_pattern, build_marker_pattern, generate_blocks

_NOTE = get_codegen_note("--api")
_PREFIX = "api-surface:"
_UNIONS = frozenset(
    {"stable-union", "extension-union", "stable-disjoint", "bado-namespace"}
)
_GROUPS = frozenset(
    name.lower().replace("_", "-")
    for name, value in vars(_api_surface).items()
    if name.isupper() and isinstance(value, frozenset)
)

API_SURFACE_BLOCK = build_block_pattern(_UNIONS | _GROUPS, prefix=_PREFIX)
API_SURFACE_MARKERS = build_marker_pattern(_PREFIX)


def _render_block(key: str) -> str:
    if key == "stable-union":
        expr = "BADO | IO_ | EXPORT | COMPILE | MODULES | OTHER | ROOT_EXCEPTIONS"
        lines = [f">>> STABLE == {expr}", "True"]
    elif key == "extension-union":
        lines = [">>> EXTENSION == EXT_MODULES | EXT_TARGETS | EXT_WORKFLOWS", "True"]
    elif key == "stable-disjoint":
        lines = [">>> STABLE.isdisjoint(EXTENSION)", "True"]
    elif key == "bado-namespace":
        lines = [
            ">>> sorted(BADO)",
            repr(sorted(_api_surface.BADO)),
            ">>> BADO == set(riko.bado.__all__)",
            "True",
        ]
    else:
        name = key.upper().replace("-", "_")
        lines = [f">>> sorted({name})", repr(sorted(getattr(_api_surface, name)))]

    body = "\n".join(lines)
    return f"```python\n{body}\n```\n"


def generate_api_surface(text: str) -> str:
    """Render the API-surface document from the contract declaration."""
    return generate_blocks(
        text, API_SURFACE_BLOCK, _render_block, _NOTE, prefix=_PREFIX
    )


def main() -> int:
    """Regenerate the API-surface reference document from the contract."""
    API_SURFACE_PATH.write_text(generate_api_surface(API_SURFACE_PATH.read_text()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
