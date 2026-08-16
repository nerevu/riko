# vim: sw=4:ts=4:expandtab
"""
riko.cli.gen_names
~~~~~~~~~~~~~~~~~~

Provides functions for generating module names and ids from the runtime catalog.
"""

from riko.ext.codegen import (
    gen_catalog_entries,
    generate_module_ids,
    generate_module_names,
)
from riko.paths import PACKAGE_DIR

_NAMES = PACKAGE_DIR / "modules" / "_names.py"
_MODULE_IDS = PACKAGE_DIR / "types" / "_module_ids.py"


def main() -> int:
    """Generate module name and id typing files."""
    _NAMES.write_text(generate_module_names(*gen_catalog_entries()))
    _MODULE_IDS.write_text(generate_module_ids())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
