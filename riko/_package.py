from importlib import metadata
from importlib.metadata import PackageMetadata

# https://github.com/astral-sh/uv/issues/7533#issuecomment-2472804995
_meta: PackageMetadata = metadata.metadata("riko")
__version__ = metadata.version("riko")

PACKAGE_INFO = {
    "__version__": __version__,
    "__title__": _meta["Name"],
    "__package_name__": _meta["Name"],
    "__description__": _meta.get("Summary") or _meta.get("Description", ""),
    "__license__": _meta.get("License-Expression") or _meta.get("License", ""),
    "__author__": _meta.get("Author", ""),
    "__email__": _meta.get("Author-email", ""),
}
