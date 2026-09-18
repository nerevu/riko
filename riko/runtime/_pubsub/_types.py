"""Pub/sub receiver and callback typing aliases."""

from collections.abc import Callable, Generator

from riko.types._streams import Item, StatefulItem

type Receiver = Generator[None, Item | StatefulItem, None]
type ReceiveFunc = Callable[[Item], Item | None]
