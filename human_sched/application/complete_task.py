"""Use case: complete task (terminate)."""

from __future__ import annotations

from human_sched.application.runtime import HumanTaskScheduler
from human_sched.domain.task import Task


class CompleteTask:
    """Application use case for permanently completing tasks."""

    def __init__(self, scheduler: HumanTaskScheduler) -> None:
        self._scheduler = scheduler

    def execute(self, task_id: int | None = None) -> Task | None:
        return self._scheduler.complete_task(task_id=task_id)
