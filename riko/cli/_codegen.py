# vim: sw=4:ts=4:expandtab

"""Code-generation command composition for the manage CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from riko.base._paths import (
    API_SURFACE_PATH,
    CONFIG_PATH,
    MODULE_IDS_PATH,
    MODULE_NAMES_PATH,
)

from ._gen_api_surface import main as gen_api_surface_main
from ._gen_config import main as gen_config_main
from ._gen_names import main as gen_names_main
from ._gen_tier_index import TIERS
from ._gen_tier_index import main as gen_tier_index_main
from ._gen_verbs import VERB_DOCS
from ._gen_verbs import main as gen_verbs_main

if TYPE_CHECKING:
    from collections.abc import Callable

_CODEGEN: dict[str, tuple[Callable[[], int], str, str]] = {
    "config": (
        gen_config_main,
        f"wrote configuration file to {CONFIG_PATH}",
        "Error updating configuration file!",
    ),
    "names": (
        gen_names_main,
        f"regenerated module names to {MODULE_NAMES_PATH} and {MODULE_IDS_PATH}",
        "Error regenerating module names!",
    ),
    "api": (
        gen_api_surface_main,
        f"regenerated the API-surface document at {API_SURFACE_PATH}",
        "Error regenerating the API-surface document!",
    ),
    "tests": (
        gen_tier_index_main,
        f"regenerated the {', '.join(TIERS)} test indexes",
        "Error regenerating the test indexes!",
    ),
    "verbs": (
        gen_verbs_main,
        f"regenerated the verb tables in {', '.join(map(str, VERB_DOCS))}",
        "Error regenerating the verb tables!",
    ),
}


@click.command(name="codegen")
@click.option("--config", help="Regenerate configuration types", is_flag=True)
@click.option("--names", help="Regenerate module-name catalogs", is_flag=True)
@click.option("--api", help="Regenerate the API-surface document", is_flag=True)
@click.option("--tests", help="Regenerate the test tier indexes", is_flag=True)
@click.option("--verbs", help="Regenerate the function-name verb tables", is_flag=True)
@click.option("--all", "all_", help="Run every generator", is_flag=True)
def _codegen_command(
    config: bool = False,
    names: bool = False,
    api: bool = False,
    tests: bool = False,
    verbs: bool = False,
    all_: bool = False,
) -> None:
    """Regenerate generated project artifacts."""
    pairs = (
        ("config", config),
        ("names", names),
        ("api", api),
        ("tests", tests),
        ("verbs", verbs),
    )
    selected = (
        tuple(_CODEGEN) if all_ else tuple(name for name, enabled in pairs if enabled)
    )
    selected = selected or ("config",)

    for name in selected:
        runner, summary, error = _CODEGEN[name]

        if runner():
            raise RuntimeError(error)

        print(f"Successfully {summary}.")


CODEGEN_COMMAND = _codegen_command
