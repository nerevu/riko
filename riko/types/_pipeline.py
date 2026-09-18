"""Compiled pipeline step and dependency typing contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._wrappers import (
        AsyncPipeWrapper,
        AsyncSplitterWrapperOutput,
        AsyncWrapperOutput,
        SyncPipeWrapper,
        SyncSplitterWrapperOutput,
        SyncWrapperOutput,
    )


# dependencies
type SyncPipelineDependencies = Callable[..., list[str]]
type AsyncPipelineDependencies = Callable[..., AsyncIterator[str]]
type PipelineDependencies = SyncPipelineDependencies | AsyncPipelineDependencies

# generated/executable steps
type SyncStepOutput = SyncWrapperOutput | SyncSplitterWrapperOutput
type SyncStepValue = SyncStepOutput | SyncPipeWrapper
type SyncStep = tuple[str, SyncStepValue]
type SyncSteps = dict[str, SyncStepValue]

type AsyncStepOutput = AsyncWrapperOutput | AsyncSplitterWrapperOutput
type AsyncStepValue = AsyncStepOutput | AsyncPipeWrapper
type AsyncStep = tuple[str, AsyncStepValue]
type AsyncSteps = dict[str, AsyncStepValue]

type StepValue = SyncStepValue | AsyncStepValue
type Step = tuple[str, SyncStepValue | AsyncStepValue]
type Steps = dict[str, SyncStepValue | AsyncStepValue]

# generated Python input
type SyncPyInput = list[str | tuple[str, ...]]
type AsyncPyInput = Awaitable[SyncPyInput]
type PyInput = SyncPyInput | AsyncPyInput
