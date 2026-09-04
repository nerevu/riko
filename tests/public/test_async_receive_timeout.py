# vim: sw=4:ts=4:expandtab
"""Public contract tests for async receive idle timeouts."""

from collections.abc import Iterator

import pytest

from riko import async_sleep
from riko._pubsub import async_hub
from riko.bado._util import gather_results
from riko.collections import AsyncPipe
from riko.exceptions import ReceiveTimeoutError
from riko.types._streams import Item
from tests import skipif_issync

pytestmark = [skipif_issync, pytest.mark.anyio]


async def _publish_with_delays(
    name: str, items: list[Item], delay: float
) -> Iterator[Item]:
    for item in items:
        await async_sleep(delay)
        await async_hub.publish([name], item, timeout=1)

    await async_hub.complete([name])
    return iter(items)


@pytest.mark.timeout(1)
async def test_receive_times_out_without_publisher():
    name = "missing-publisher"
    receiver = AsyncPipe("receive", conf={"name": name, "max_wait": 0.05})

    with pytest.raises(ReceiveTimeoutError, match=name):
        await receiver

    assert name not in async_hub._slots


@pytest.mark.timeout(2)
async def test_receive_timeout_resets_after_each_item():
    name = "paced-publisher"
    items = [{"n": 1}, {"n": 2}, {"n": 3}]
    receiver = AsyncPipe("receive", conf={"name": name, "max_wait": 0.15})

    received, _ = await gather_results(
        [receiver, _publish_with_delays(name, items, delay=0.08)]
    )

    assert list(received) == items
    assert name not in async_hub._slots
