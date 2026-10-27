from collections.abc import Iterable, Mapping
from io import StringIO

def records2csv(
    records: Iterable[Mapping[str, object]],
    encoding: str = ...,
    bom: bool = False,
    skip_header: bool = False,
) -> StringIO: ...
def records2geojson(
    records: Iterable[Mapping[str, object]], **kwargs: object
) -> StringIO: ...
