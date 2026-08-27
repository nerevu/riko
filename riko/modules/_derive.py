# vim: sw=4:ts=4:expandtab
"""
riko.modules._derive
~~~~~~~~~~~~~~~~~~~~~

Provides functions for deriving module subtypes and loop behavior.
"""

from typing import cast

from riko.cast import BasicCastType
from riko.modules._inference import gen_operator_return_kinds
from riko.types.general import ModuleParser
from riko.types.modules import (
    ModuleSubtype,
    ModuleSubtypes,
    ModuleType,
    OperatorReturnKind,
)


# Keep this module independent of riko.ext. It is imported while riko.modules is still
# initializing.
def _derive_operator_subtypes(
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


def derive_loopable(name: str, module_type: ModuleType | str) -> bool:
    return module_type == "processor" and name != "input"


def derive_subtypes(
    pipe: ModuleParser,
    module_type: ModuleType | str,
    ftype: BasicCastType | None = None,
    **kwargs: object,
) -> tuple[ModuleSubtype | None, ModuleSubtypes]:
    if module_type == "processor":
        none_ftype = ftype == BasicCastType.NONE
        subtype: ModuleSubtype | None = "source" if none_ftype else "transformer"
        result = subtype, cast(ModuleSubtypes, {subtype})
    elif module_type == "splitter":
        result = "splitter", cast(ModuleSubtypes, {"splitter"})
    else:
        result = _derive_operator_subtypes(pipe)

    return result
