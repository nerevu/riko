from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from riko.types._wrappers import (
        AsyncPipeWrapper,
        AsyncWrapperOutput,
        SyncPipeWrapper,
        SyncWrapperOutput,
    )

# dependencies
type SyncPipelineDependencies = Callable[..., list[str]]
type AsyncPipelineDependencies = Callable[..., Awaitable[list[str]]]
type PipelineDependencies = SyncPipelineDependencies | AsyncPipelineDependencies

# generated/executable steps
type SyncStepValue = SyncWrapperOutput | SyncPipeWrapper
type SyncStep = tuple[str, SyncStepValue]
type SyncSteps = dict[str, SyncStepValue]

type AsyncStepValue = AsyncWrapperOutput | AsyncPipeWrapper
type AsyncStep = tuple[str, AsyncStepValue]
type AsyncSteps = dict[str, AsyncStepValue]

type StepValue = SyncStepValue | AsyncStepValue
type Step = tuple[str, SyncStepValue | AsyncStepValue]
type Steps = dict[str, SyncStepValue | AsyncStepValue]

# generated Python input
type SyncPyInput = list[str | tuple[str, ...]]
type AsyncPyInput = Awaitable[list[str]]
type PyInput = SyncPyInput | AsyncPyInput
