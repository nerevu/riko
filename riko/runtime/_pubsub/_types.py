"""Pub/sub receiver and callback typing aliases."""

from collections.abc import Callable, Generator

from riko.types._streams import Record, StatefulItem

type Receiver = Generator[None, Record | StatefulItem, None]
type ReceiveFunc = Callable[[Record], Record | None]
