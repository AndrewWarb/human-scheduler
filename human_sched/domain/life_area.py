"""LifeArea domain entity wrapping a scheduler ThreadGroup."""

from __future__ import annotations

from dataclasses import dataclass, field

from xnu_sched.constants import BUCKET_NAMES
from xnu_sched.thread import ThreadGroup


@dataclass(slots=True)
class LifeArea:
    """Human life area/project mapped to a scheduler ThreadGroup."""

    name: str
    thread_group: ThreadGroup
    task_ids: set[int] = field(default_factory=set)

    @property
    def life_area_id(self) -> int:
        return self.thread_group.tg_id

    def interactivity_scores(self) -> dict[str, int]:
        """Expose bucket-group interactivity as read-only human insight."""
        clutch = self.thread_group.sched_clutch
        if clutch is None:
            return {}

        scores: dict[str, int] = {}
        for bucket, group in enumerate(clutch.sc_clutch_groups):
            bucket_name = BUCKET_NAMES.get(bucket, str(bucket))
            scores[bucket_name] = group.scbg_interactivity_score
        return scores
