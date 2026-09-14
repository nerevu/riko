# vim: sw=4:ts=4:expandtab

"""Code-generation command composition for the manage CLI."""

from collections.abc import Callable

import click

from ._gen_api_surface import _DOC as API_SURFACE_PATH
from ._gen_api_surface import main as gen_api_surface_main
from ._gen_config import _CONFIGS as CONFIG_PATH
from ._gen_config import main as gen_config_main
from ._gen_names import _MODULE_IDS as MODULE_IDS_PATH
from ._gen_names import _NAMES as NAMES_PATH
from ._gen_names import main as gen_names_main
from ._gen_pipelines import main as gen_pipelines_main

_CODEGEN: dict[str, tuple[Callable[[], int], Callable[[], str], str]] = {
    "config": (
        gen_config_main,
        lambda: f"wrote configuration file to {CONFIG_PATH}",
        "Error updating configuration file!",
    ),
    "names": (
        gen_names_main,
        lambda: f"regenerated module names to {NAMES_PATH} and {MODULE_IDS_PATH}",
        "Error regenerating module names!",
    ),
    "pipes": (
        gen_pipelines_main,
        lambda: "regenerated compiled pipe modules from their JSON definitions",
        "Error regenerating compiled pipe modules!",
    ),
    "api": (
        gen_api_surface_main,
        lambda: f"regenerated the API-surface document at {API_SURFACE_PATH}",
        "Error regenerating the API-surface document!",
    ),
}


@click.command(name="codegen")
@click.option("--config", help="Regenerate configuration types", is_flag=True)
@click.option("--names", help="Regenerate module-name catalogs", is_flag=True)
@click.option("--pipes", help="Regenerate compiled pipeline fixtures", is_flag=True)
@click.option("--api", help="Regenerate the API-surface document", is_flag=True)
@click.option("--all", "all_", help="Run every generator", is_flag=True)
def _codegen_command(
    config: bool = False,
    names: bool = False,
    pipes: bool = False,
    api: bool = False,
    all_: bool = False,
) -> None:
    """Regenerate generated project artifacts."""
    selected = (
        tuple(_CODEGEN)
        if all_
        else tuple(
            name
            for name, enabled in (
                ("config", config),
                ("names", names),
                ("pipes", pipes),
                ("api", api),
            )
            if enabled
        )
    )
    selected = selected or ("config",)

    for name in selected:
        runner, summary, error = _CODEGEN[name]

        if runner():
            raise RuntimeError(error)

        print(f"Successfully {summary()}.")


CODEGEN_COMMAND = _codegen_command
