"""Seed scenarios for fast GUI demos and manual testing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScenarioTask:
    title: str
    urgency_tier: str
    description: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ScenarioLifeArea:
    name: str
    description: str
    tasks: tuple[ScenarioTask, ...]


@dataclass(frozen=True, slots=True)
class ScenarioDefinition:
    key: str
    label: str
    description: str
    life_areas: tuple[ScenarioLifeArea, ...]


class ScenarioFacade(Protocol):
    def create_life_area(self, *, name: str, description: str = "") -> dict:
        ...

    def create_task(
        self,
        *,
        life_area_id: int,
        title: str,
        urgency_tier: str,
        description: str = "",
        notes: str = "",
    ) -> dict:
        ...

    def publish_info(self, message: str, *, related_task_id: int | None = None) -> None:
        ...


_SCENARIOS: dict[str, ScenarioDefinition] = {
    "empty": ScenarioDefinition(
        key="empty",
        label="Empty",
        description="Start from scratch with no life areas or tasks.",
        life_areas=(),
    ),
    "workday_blend": ScenarioDefinition(
        key="workday_blend",
        label="Workday Blend",
        description="Balanced work, health, and home tasks with mixed urgency.",
        life_areas=(
            ScenarioLifeArea(
                name="Work",
                description="Primary professional commitments.",
                tasks=(
                    ScenarioTask("Ship payroll export fix", "critical", "Deadline today."),
                    ScenarioTask("Write onboarding guide", "important"),
                    ScenarioTask("Refactor metrics endpoint", "normal"),
                ),
            ),
            ScenarioLifeArea(
                name="Health",
                description="Physical and mental maintenance.",
                tasks=(
                    ScenarioTask("40-minute run", "normal"),
                    ScenarioTask("Schedule annual checkup", "maintenance"),
                ),
            ),
            ScenarioLifeArea(
                name="Home",
                description="Household operations.",
                tasks=(
                    ScenarioTask("Pay electricity bill", "important"),
                    ScenarioTask("Declutter office shelf", "maintenance"),
                ),
            ),
        ),
    ),
    "exam_crunch": ScenarioDefinition(
        key="exam_crunch",
        label="Exam Crunch",
        description="Student workload where one urgent lane dominates temporarily.",
        life_areas=(
            ScenarioLifeArea(
                name="University",
                description="Coursework and exam prep.",
                tasks=(
                    ScenarioTask("Finalize algorithms cheat sheet", "critical"),
                    ScenarioTask("Practice distributed systems mock exam", "active_focus"),
                    ScenarioTask("Review lecture notes", "important"),
                ),
            ),
            ScenarioLifeArea(
                name="Admin",
                description="Required but lower urgency obligations.",
                tasks=(
                    ScenarioTask("Submit reimbursement form", "normal"),
                    ScenarioTask("Archive old receipts", "someday"),
                ),
            ),
        ),
    ),
    "home_reset": ScenarioDefinition(
        key="home_reset",
        label="Home Reset",
        description="Personal-life heavy set with maintenance and backlog tasks.",
        life_areas=(
            ScenarioLifeArea(
                name="Household",
                description="Shared home responsibilities.",
                tasks=(
                    ScenarioTask("Book plumber for leak", "critical"),
                    ScenarioTask("Weekly grocery run", "normal"),
                    ScenarioTask("Sort garage bins", "maintenance"),
                ),
            ),
            ScenarioLifeArea(
                name="Finance",
                description="Budgeting and admin.",
                tasks=(
                    ScenarioTask("Reconcile credit card charges", "important"),
                    ScenarioTask("Research new savings account", "someday"),
                ),
            ),
            ScenarioLifeArea(
                name="Hobbies",
                description="Longer-term personal growth.",
                tasks=(
                    ScenarioTask("Practice guitar scales", "maintenance"),
                    ScenarioTask("Sketch weekend trip ideas", "someday"),
                ),
            ),
        ),
    ),
}


def available_seed_scenarios() -> list[dict[str, str]]:
    """Return lightweight scenario metadata for settings UI."""

    return [
        {
            "key": scenario.key,
            "label": scenario.label,
            "description": scenario.description,
        }
        for scenario in _SCENARIOS.values()
    ]


def apply_seed_scenario(facade: ScenarioFacade, scenario_name: str) -> str:
    """Populate scheduler state from a named scenario and return the key used."""

    key = (scenario_name or "empty").strip().lower()
    if key not in _SCENARIOS:
        raise KeyError(f"Unknown GUI scenario: {scenario_name!r}")

    scenario = _SCENARIOS[key]
    if not scenario.life_areas:
        facade.publish_info("Started with an empty scenario.")
        return key

    for area in scenario.life_areas:
        area_dto = facade.create_life_area(name=area.name, description=area.description)
        area_id = int(area_dto["id"])

        for task in area.tasks:
            facade.create_task(
                life_area_id=area_id,
                title=task.title,
                urgency_tier=task.urgency_tier,
                description=task.description,
                notes=task.notes,
            )

    facade.publish_info(f"Loaded scenario '{scenario.label}'.")
    return key
