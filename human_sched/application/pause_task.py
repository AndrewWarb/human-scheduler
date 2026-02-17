"""Use case: pause task (block)."""

from __future__ import annotations

from human_sched.application.runtime import HumanTaskScheduler
from human_sched.domain.task import Task


class PauseTask:
    """Application use case for pausing the current or specific task."""

    def __init__(self, scheduler: HumanTaskScheduler) -> None:
        self._scheduler = scheduler

    def execute(self, task_id: int | None = None) -> Task | None:
        return self._scheduler.pause_task(task_id=task_id)
