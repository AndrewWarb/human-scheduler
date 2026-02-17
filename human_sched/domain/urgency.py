"""Urgency tiers mapped to XNU scheduler QoS buckets and priorities."""

from __future__ import annotations

from enum import Enum

from xnu_sched.constants import (
    BASEPRI_CONTROL,
    BASEPRI_DEFAULT,
    BASEPRI_FOREGROUND,
    BASEPRI_USER_INITIATED,
    BASEPRI_UTILITY,
    MAXPRI_THROTTLE,
    TH_MODE_FIXED,
    TH_MODE_TIMESHARE,
)


class UrgencyTier(str, Enum):
    """Human urgency tiers mapped to scheduler QoS semantics."""

    CRITICAL = "critical"
    ACTIVE_FOCUS = "active_focus"
    IMPORTANT = "important"
    NORMAL = "normal"
    MAINTENANCE = "maintenance"
    SOMEDAY = "someday"

    @property
    def sched_mode(self) -> int:
        if self is UrgencyTier.CRITICAL:
            return TH_MODE_FIXED
        return TH_MODE_TIMESHARE

    @property
    def base_priority(self) -> int:
        if self is UrgencyTier.CRITICAL:
            return BASEPRI_CONTROL
        if self is UrgencyTier.ACTIVE_FOCUS:
            return BASEPRI_FOREGROUND
        if self is UrgencyTier.IMPORTANT:
            return BASEPRI_USER_INITIATED
        if self is UrgencyTier.NORMAL:
            return BASEPRI_DEFAULT
        if self is UrgencyTier.MAINTENANCE:
            return BASEPRI_UTILITY
        return MAXPRI_THROTTLE

    @property
    def label(self) -> str:
        return {
            UrgencyTier.CRITICAL: "Critical",
            UrgencyTier.ACTIVE_FOCUS: "Active focus",
            UrgencyTier.IMPORTANT: "Important",
            UrgencyTier.NORMAL: "Normal",
            UrgencyTier.MAINTENANCE: "Maintenance",
            UrgencyTier.SOMEDAY: "Someday",
        }[self]

    @classmethod
    def from_value(cls, value: "UrgencyTier | str") -> "UrgencyTier":
        if isinstance(value, UrgencyTier):
            return value

        normalized = value.strip().lower()
        aliases = {
            "fixpri": cls.CRITICAL,
            "fg": cls.ACTIVE_FOCUS,
            "foreground": cls.ACTIVE_FOCUS,
            "in": cls.IMPORTANT,
            "user_initiated": cls.IMPORTANT,
            "df": cls.NORMAL,
            "default": cls.NORMAL,
            "ut": cls.MAINTENANCE,
            "utility": cls.MAINTENANCE,
            "bg": cls.SOMEDAY,
            "background": cls.SOMEDAY,
        }

        if normalized in aliases:
            return aliases[normalized]
        return cls(normalized)
