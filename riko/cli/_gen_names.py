# vim: sw=4:ts=4:expandtab
"""Provides functions for generating module names and ids from the runtime catalog."""

from riko.base._paths import MODULE_IDS_PATH, MODULE_NAMES_PATH
from riko.ext.codegen import (
    gen_catalog_entries,
    generate_module_ids,
    generate_module_names,
)


def main() -> int:
    """Generate module name and id typing files."""
    MODULE_NAMES_PATH.write_text(generate_module_names(*gen_catalog_entries()))
    MODULE_IDS_PATH.write_text(generate_module_ids())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
