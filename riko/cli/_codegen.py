# vim: sw=4:ts=4:expandtab

"""Code-generation command composition for the manage CLI."""

from collections.abc import Callable

import click
from click import Choice

from .gen_api_surface import _DOC as API_SURFACE_PATH
from .gen_api_surface import main as gen_api_surface_main
from .gen_config import _CONFIGS as CONFIG_PATH
from .gen_config import main as gen_config_main
from .gen_names import _MODULE_IDS as MODULE_IDS_PATH
from .gen_names import _NAMES as NAMES_PATH
from .gen_names import main as gen_names_main
from .gen_pipelines import main as gen_pipelines_main

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
@click.option(
    "-m",
    "--mode",
    help="Which file to generate",
    type=Choice(list(_CODEGEN), case_sensitive=False),
    default="config",
)
def _codegen_command(mode: str = "config") -> None:
    """Regenerate config, module-name, or compiled-pipe files."""
    runner, summary, error = _CODEGEN[mode]

    if runner():
        raise RuntimeError(error)

    print(f"Successfully {summary()}.")


CODEGEN_COMMAND = _codegen_command
