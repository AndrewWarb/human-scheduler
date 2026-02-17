"""Use case: create life area."""

from __future__ import annotations

from human_sched.application.runtime import HumanTaskScheduler
from human_sched.domain.life_area import LifeArea


class CreateLifeArea:
    """Application use case for creating a life area."""

    def __init__(self, scheduler: HumanTaskScheduler) -> None:
        self._scheduler = scheduler

    def execute(self, name: str, description: str = "") -> LifeArea:
        return self._scheduler.create_life_area(name=name, description=description)
