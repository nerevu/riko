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
    USER_AGENTS_PATH,
)

from ._gen_api_surface import main as gen_api_surface_main
from ._gen_config import main as gen_config_main
from ._gen_names import main as gen_names_main
from ._gen_planning import PLANNING_DOCS
from ._gen_planning import main as gen_planning_main
from ._gen_tier_index import TIERS
from ._gen_tier_index import main as gen_tier_index_main
from ._gen_user_agents import main as gen_user_agents_main
from ._gen_verbs import VERB_DOCS
from ._gen_verbs import main as gen_verbs_main

if TYPE_CHECKING:
    from riko.types._wrappers import Func

_CODEGEN: dict[str, tuple[Func[int], str, str, str]] = {
    "config": (
        gen_config_main,
        f"wrote configuration file to {CONFIG_PATH}",
        "Error updating configuration file!",
        "Regenerate configuration types",
    ),
    "names": (
        gen_names_main,
        f"regenerated module names to {MODULE_NAMES_PATH} and {MODULE_IDS_PATH}",
        "Error regenerating module names!",
        "Regenerate module-name catalogs",
    ),
    "api": (
        gen_api_surface_main,
        f"regenerated the API-surface document at {API_SURFACE_PATH}",
        "Error regenerating the API-surface document!",
        "Regenerate the API-surface document",
    ),
    "tests": (
        gen_tier_index_main,
        f"regenerated the {', '.join(TIERS)} test indexes",
        "Error regenerating the test indexes!",
        "Regenerate the test tier indexes",
    ),
    "verbs": (
        gen_verbs_main,
        f"regenerated the verb tables in {', '.join(map(str, VERB_DOCS))}",
        "Error regenerating the verb tables!",
        "Regenerate the function-name verb tables",
    ),
    "user-agents": (
        gen_user_agents_main,
        f"regenerated the random user-agent pools at {USER_AGENTS_PATH}",
        "Error regenerating the random user-agent pools!",
        "Regenerate the random user-agent pools",
    ),
    "planning": (
        gen_planning_main,
        f"regenerated the planning blocks in {', '.join(map(str, PLANNING_DOCS))}",
        "Error regenerating the planning blocks!",
        "Regenerate the planning tables and dependency graph",
    ),
}


@click.command(
    name="codegen",
    params=[
        click.Option([f"--{name}"], help=help_, is_flag=True)
        for name, (*_, help_) in _CODEGEN.items()
    ],
)
@click.option("--all", "all_", help="Run every generator", is_flag=True)
def _codegen_command(all_: bool = False, **selectors: bool) -> None:
    """Regenerate generated project artifacts."""
    names = (name for name in _CODEGEN if selectors[name.replace("-", "_")])
    selected = tuple(_CODEGEN) if all_ else tuple(names)
    selected = selected or ("config",)

    for name in selected:
        runner, summary, error, _ = _CODEGEN[name]

        if runner():
            raise RuntimeError(error)

        print(f"Successfully {summary}.")


CODEGEN_COMMAND = _codegen_command
