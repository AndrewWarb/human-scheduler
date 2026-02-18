"""Use case: create task."""

from __future__ import annotations

from human_sched.application.runtime import HumanTaskScheduler
from human_sched.domain.life_area import LifeArea
from human_sched.domain.task import Task
from human_sched.domain.urgency import UrgencyTier


class CreateTask:
    """Application use case for creating runnable tasks."""

    def __init__(self, scheduler: HumanTaskScheduler) -> None:
        self._scheduler = scheduler

    def execute(
        self,
        *,
        life_area: LifeArea | int | str,
        title: str,
        urgency_tier: UrgencyTier | str = UrgencyTier.NORMAL,
        notes: str = "",
        start_runnable: bool = True,
    ) -> Task:
        return self._scheduler.create_task(
            life_area=life_area,
            title=title,
            urgency_tier=urgency_tier,
            notes=notes,
            start_runnable=start_runnable,
        )
