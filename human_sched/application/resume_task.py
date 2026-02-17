"""Use case: resume task (wakeup)."""

from __future__ import annotations

from human_sched.application.runtime import HumanTaskScheduler
from human_sched.domain.task import Task


class ResumeTask:
    """Application use case for waking a paused task."""

    def __init__(self, scheduler: HumanTaskScheduler) -> None:
        self._scheduler = scheduler

    def execute(self, task_id: int) -> Task:
        return self._scheduler.resume_task(task_id=task_id)
