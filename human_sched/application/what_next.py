"""Use case: atomic 'what next?' selection + dispatch."""

from __future__ import annotations

from human_sched.application.runtime import Dispatch, HumanTaskScheduler


class WhatNext:
    """Application use case returning the currently dispatched task recommendation."""

    def __init__(self, scheduler: HumanTaskScheduler) -> None:
        self._scheduler = scheduler

    def execute(self) -> Dispatch | None:
        return self._scheduler.what_next()
