from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._wrappers import (
        AsyncPipeItems,
        AsyncPipeParser,
        ParserOutput,
        Pipeline,
        SyncPipeParser,
    )

# dependencies
type SyncPipelineDependencies = Callable[..., list[str]]
type AsyncPipelineDependencies = Callable[..., Awaitable[list[str]]]
type PipelineDependencies = SyncPipelineDependencies | AsyncPipelineDependencies

# generated/executable steps
type SyncStep = tuple[str, ParserOutput | SyncPipeParser]
type SyncSteps = dict[str, ParserOutput | SyncPipeParser]

type AsyncStep = tuple[str, AsyncPipeItems | AsyncPipeParser]
type AsyncSteps = dict[str, AsyncPipeItems | AsyncPipeParser]

type StepValue = ParserOutput | Pipeline | AsyncPipeItems
type Step = tuple[str, StepValue]
type Steps = dict[str, StepValue]

# generated Python input
type SyncPyInput = list[str | tuple[str, ...]]
type AsyncPyInput = Awaitable[list[str]]
type PyInput = SyncPyInput | AsyncPyInput
