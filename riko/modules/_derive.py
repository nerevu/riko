# vim: sw=4:ts=4:expandtab
"""Provides functions for deriving module subtypes and loop behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.types._enums import BasicCastType
from riko.types.modules import (
    ModuleSubtype,
    ModuleSubtypes,
    ModuleType,
    OperatorReturnKind,
)

from ._inference import gen_operator_return_kinds

if TYPE_CHECKING:
    from riko.types._wrappers import ModuleParser


# Keep this module independent of riko.ext. It is imported while riko.modules is still
# initializing.
def _get_operator_subtypes(
    pipe: ModuleParser,
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    subtype: ModuleSubtype | None = None
    subtypes: ModuleSubtypes = set()

    for kind in gen_operator_return_kinds(pipe):
        if kind == OperatorReturnKind.NONSTREAM:
            subtype = subtype or "aggregator"
            subtypes.add(subtype)
        elif kind == OperatorReturnKind.STREAM:
            subtype = subtype or "composer"
            subtypes.add("composer")

        # An operator may support both return forms.
        if subtype and subtypes == {"aggregator", "composer"}:
            break

    if not subtypes:
        qualified_name = f"{pipe.__module__}.{pipe.__name__}"
        msg = f"{qualified_name} no supported subtypes found"
        raise TypeError(msg)

    return subtype, subtypes


def is_loopable(name: str, module_type: ModuleType | str) -> bool:
    return module_type == "processor" and name != "input"


def get_module_subtypes(
    pipe: ModuleParser,
    module_type: ModuleType | str,
    ftype: BasicCastType | None = None,
    **kwargs: object,
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    if module_type == "processor":
        none_ftype = ftype == BasicCastType.NONE
        subtype = "source" if none_ftype else "transformer"
        result: tuple[ModuleSubtype | None, ModuleSubtypes] = subtype, {subtype}
    elif module_type == "splitter":
        result = "splitter", {"splitter"}
    else:
        result = _get_operator_subtypes(pipe)

    return result
