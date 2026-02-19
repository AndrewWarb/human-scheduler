"""Time-scale adapter: wall-clock <-> scheduler microseconds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


DEFAULT_TIME_SCALE_HOURS_PER_US = 0.00025
DEFAULT_MAX_CATCHUP_TICKS = 4


@dataclass(frozen=True)
class TimeScaleConfig:
    """Configuration for mapping scheduler time to human wall-clock time."""

    hours_per_us: float = DEFAULT_TIME_SCALE_HOURS_PER_US
    max_catchup_ticks: int = DEFAULT_MAX_CATCHUP_TICKS


class TimeScaleAdapter:
    """Converts between scheduler microseconds and wall-clock time."""

    __slots__ = ("_config", "_wall_epoch", "_now_provider")

    def __init__(
        self,
        config: TimeScaleConfig,
        wall_epoch: datetime | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        if config.hours_per_us <= 0:
            raise ValueError("hours_per_us must be > 0")

        epoch = wall_epoch or datetime.now(timezone.utc)
        if epoch.tzinfo is None:
            epoch = epoch.replace(tzinfo=timezone.utc)

        self._config = config
        self._wall_epoch = epoch
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    @property
    def config(self) -> TimeScaleConfig:
        return self._config

    @property
    def wall_epoch(self) -> datetime:
        return self._wall_epoch

    def now_wallclock(self) -> datetime:
        now = self._now_provider()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now

    def hours_to_us(self, hours: float) -> int:
        if hours < 0:
            raise ValueError("hours must be >= 0")
        return int(round(hours / self._config.hours_per_us))

    def us_to_hours(self, microseconds: int) -> float:
        return microseconds * self._config.hours_per_us

    def scheduler_us_for_wall(self, wall_time: datetime) -> int:
        if wall_time.tzinfo is None:
            wall_time = wall_time.replace(tzinfo=timezone.utc)
        delta = wall_time - self._wall_epoch
        hours = delta.total_seconds() / 3600.0
        if hours <= 0:
            return 0
        return self.hours_to_us(hours)

    def now_scheduler_us(self) -> int:
        return self.scheduler_us_for_wall(self.now_wallclock())

    def scheduler_us_to_wall(self, scheduler_us: int) -> datetime:
        if scheduler_us < 0:
            raise ValueError("scheduler_us must be >= 0")
        hours = self.us_to_hours(scheduler_us)
        return self._wall_epoch + timedelta(hours=hours)

    def __getstate__(self) -> dict:
        return {"_config": self._config, "_wall_epoch": self._wall_epoch}

    def __setstate__(self, state: dict) -> None:
        self._config = state["_config"]
        self._wall_epoch = state["_wall_epoch"]
        self._now_provider = lambda: datetime.now(timezone.utc)


def load_time_scale_config(env_file: str = ".env") -> TimeScaleConfig:
    """Load time-scale configuration from env file, with safe fallbacks."""

    env = _parse_env_file(env_file)

    hours_per_us = _env_float(
        env,
        key="TIME_SCALE_HOURS_PER_US",
        default=DEFAULT_TIME_SCALE_HOURS_PER_US,
        minimum=1e-12,
    )
    max_catchup_ticks = _env_int(
        env,
        key="MAX_CATCHUP_TICKS",
        default=DEFAULT_MAX_CATCHUP_TICKS,
        minimum=0,
    )

    return TimeScaleConfig(
        hours_per_us=hours_per_us,
        max_catchup_ticks=max_catchup_ticks,
    )


def _parse_env_file(path: str) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}

    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[7:].strip()
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def _env_float(env: dict[str, str], key: str, default: float, minimum: float) -> float:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value


def _env_int(env: dict[str, str], key: str, default: int, minimum: int) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return default
    return value
