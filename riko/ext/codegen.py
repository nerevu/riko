# vim: sw=4:ts=4:expandtab
"""
Generates module discovery names and ids from the runtime module catalog.

Generated name and id output is deterministic.

Examples:

    Basic usage::

        >>> from riko.ext.codegen import enum_member_name
        >>>
        >>> enum_member_name("strtransform")
        'STRTRANSFORM'
        >>> enum_member_name("3to2")
        '_3TO2'

"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from riko.base._config import BUILTIN_PROVIDER
from riko.base._strutils import get_codegen_note, ruff_format
from riko.modules._metadata import gen_module_catalog, get_module_category
from riko.types.modules import get_module_provider

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from riko.types.modules import ModuleCategory, ModuleClass

_HEADER = f"# {get_codegen_note('--names')}"

_NAMES_DOC = '''"""
Typed discovery enums for built-in modules.

Examples:
    Basic usage::

        >>> from riko import Sources
        >>>
        >>> Sources.FETCH.value
        'fetch'

"""'''

_IDS_DOC = '''"""Generated built-in module-id typing aliases and name set."""'''
_IMPORT = (
    "from riko.types._enums import ModuleName\n\n"
    '__all__ = ["Modules", "Sinks", "Sources", "Transforms"]'
)
_MEMBER_SPLIT = re.compile(r"[^0-9A-Za-z]+")

_CANONICAL: dict[ModuleCategory, ModuleClass] = {
    "source": "Sources",
    "transform": "Transforms",
    "sink": "Sinks",
}


# TODO: compare to pythonise
def enum_member_name(name: str, *, override: str | None = None) -> str:
    """Builds a valid enum member name for a module id."""
    source = override or name
    collapsed = _MEMBER_SPLIT.sub("_", source).strip("_").upper()
    return f"_{collapsed}" if collapsed[:1].isdigit() else collapsed


@dataclass(frozen=True, slots=True)
class NameEntry:
    """A module name and its generated enum metadata."""

    name: str
    category: ModuleCategory
    enum_name: str | None = None

    @property
    def provider(self) -> str:
        """The provider, or namespace, the module belongs to."""
        return get_module_provider(self.name)

    @property
    def is_builtin(self) -> bool:
        """Whether the module belongs to the built-in provider."""
        return self.provider == BUILTIN_PROVIDER

    @property
    def class_name(self) -> str:
        """The generated class holding the module: its category or its provider."""
        if self.is_builtin:
            class_name = _CANONICAL[self.category]
        else:
            class_name = enum_member_name(self.provider).capitalize()

        return class_name

    @property
    def member(self) -> str:
        """The enum member name inside the module's generated class."""
        if self.is_builtin:
            source = self.name
        else:
            source = self.name.removeprefix(f"{self.provider}.")

        return enum_member_name(source, override=self.enum_name)

    @property
    def alias(self) -> str:
        """The member name in the flat ``Modules`` class."""
        if self.is_builtin:
            alias = self.member
        else:
            alias = f"{enum_member_name(self.provider)}_{self.member}"

        return alias


def gen_catalog_entries() -> Iterator[NameEntry]:
    """Emits name entries from the runtime module catalog."""
    for md in sorted(gen_module_catalog(), key=lambda md: md.name):
        yield NameEntry(name=md.name, category=get_module_category(md))


def _group(entries: Iterable[NameEntry]) -> dict[str, list[NameEntry]]:
    groups: dict[str, list[NameEntry]] = defaultdict(list)
    [groups[entry.class_name].append(entry) for entry in entries]
    return groups


def _order_groups(*names: str) -> list[str]:
    canonical = tuple(_CANONICAL.values())
    extra = sorted(set(names).difference(canonical))
    return [*canonical, *extra]


def _get_members(*entries: NameEntry) -> dict[str, str]:
    resolved: dict[str, str] = {}

    for entry in sorted(entries, key=lambda e: e.name):
        member = entry.member

        if member in resolved:
            raise ValueError(
                f"module ids {resolved[member]!r} and {entry.name!r} both map to "
                f"enum member {member!r}; give one an explicit enum_name"
            )

        resolved[member] = entry.name

    return resolved


def _gen_class_blocks(groups: Mapping[str, Iterable[NameEntry]]) -> Iterator[str]:
    for class_name in _order_groups(*groups):
        members = _get_members(*groups.get(class_name, []))
        lines = [f'    {member} = "{mid}"' for member, mid in members.items()]
        body = lines or ["    pass"]
        yield "\n".join([f"class {class_name}(ModuleName):", *body])


def _gen_aliases(
    class_name: str, *entries: NameEntry
) -> Iterator[tuple[str, str, str]]:
    for entry in sorted(entries, key=lambda e: e.name):
        line = f"    {entry.alias} = {class_name}.{entry.member}"
        yield (entry.name, line, entry.alias)


def _generate_module_block(groups: Mapping[str, Iterable[NameEntry]]) -> str:
    resolved: dict[str, str] = {}
    aliases: list[tuple[str, str]] = []

    for class_name in _order_groups(*groups):
        entries = groups.get(class_name, [])

        for mid, line, alias in _gen_aliases(class_name, *entries):
            if alias in resolved:
                raise ValueError(
                    f"module ids {resolved[alias]!r} and {mid!r} both map to "
                    f"enum member {alias!r}; give one an explicit enum_name"
                )

            resolved[alias] = mid
            aliases.append((mid, line))

    body = [line for _mid, line in sorted(aliases)] or ["    pass"]
    return "\n".join(["class Modules:", *body])


def generate_module_names(*entries: NameEntry) -> str:
    """Generate the typed module-name definitions."""
    groups = _group(entries)
    classes = _gen_class_blocks(groups)
    module = _generate_module_block(groups)
    body = "\n\n\n".join([*classes, module])
    return ruff_format(f"{_HEADER}\n\n{_NAMES_DOC}\n\n{_IMPORT}\n\n\n{body}\n")


def _catalog_ids() -> tuple[list[str], list[str]]:
    catalog = sorted(gen_module_catalog(), key=lambda md: md.name)
    return [md.name for md in catalog], [md.name for md in catalog if md.loopable]


def _literal_alias(name: str, *ids: str) -> str:
    members = ", ".join(f'"{module_id}"' for module_id in ids)
    return f"{name} = Literal[{members}]"


def generate_module_ids() -> str:
    """Generate the module id ``Literal`` aliases and the built-in module-id set."""
    all_ids, loopable_ids = _catalog_ids()
    aliases = "\n\n".join(
        [
            _literal_alias("ModuleId", *all_ids),
            _literal_alias("LoopableModuleId", *loopable_ids),
        ]
    )
    names = "BUILTIN_MODULE_IDS: frozenset[str] = frozenset(get_args(ModuleId))"
    imports = "from typing import Literal, get_args"
    src = f"{_HEADER}\n\n{_IDS_DOC}\n\n{imports}\n\n{aliases}\n\n{names}\n"
    return ruff_format(src)


__all__ = [
    "NameEntry",
    "enum_member_name",
    "gen_catalog_entries",
    "generate_module_ids",
    "generate_module_names",
]
