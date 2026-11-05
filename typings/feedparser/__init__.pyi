from typing import Literal, Protocol, overload

from riko.types._rss import ParserRSSEntry

class _Readable(Protocol):
    def read(self, size: int = ..., /) -> str | bytes: ...

class FeedParserDict(dict[str, object]):
    @overload
    def __getitem__(
        self, key: Literal["entries", "items"], /
    ) -> list[ParserRSSEntry]: ...
    @overload
    def __getitem__(self, key: str, /) -> object: ...
    def __getattr__(self, name: str) -> object: ...

def parse(
    url_file_stream_or_string: str | bytes | _Readable,
    etag: str | None = None,
    modified: str | None = None,
    agent: str | None = None,
    referrer: str | None = None,
    handlers: list[object] | None = None,
    request_headers: dict[str, str] | None = None,
    response_headers: dict[str, str] | None = None,
    resolve_relative_uris: bool | None = None,
    sanitize_html: bool | None = None,
) -> FeedParserDict: ...
