"""
Workload generators for simulation scenarios.

Each workload profile defines a set of threads with specific behaviors
(CPU burst patterns, blocking patterns, QoS levels) that model real
macOS application behaviors.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from xnu_sched.constants import (
    TH_MODE_REALTIME,
    TH_MODE_FIXED,
    TH_MODE_TIMESHARE,
    TH_BUCKET_FIXPRI,
    TH_BUCKET_SHARE_FG,
    TH_BUCKET_SHARE_IN,
    TH_BUCKET_SHARE_DF,
    TH_BUCKET_SHARE_UT,
    TH_BUCKET_SHARE_BG,
    BASEPRI_FOREGROUND,
    BASEPRI_USER_INITIATED,
    BASEPRI_DEFAULT,
    BASEPRI_CONTROL,
    BASEPRI_UTILITY,
    MAXPRI_THROTTLE,
    BASEPRI_REALTIME,
)
from xnu_sched.thread import Thread, ThreadGroup
from xnu_sched.clutch import SchedClutch

if TYPE_CHECKING:
    pass


@dataclass
class BehaviorProfile:
    """Defines how a thread behaves over time."""

    # For timeshare/fixed threads
    avg_cpu_burst_us: int = 5000  # avg CPU burst before blocking
    cpu_burst_variance: float = 0.3  # variance as fraction of avg
    avg_block_duration_us: int = 50000  # avg time spent blocked
    block_variance: float = 0.3

    # For RT threads
    rt_period_us: int = 0
    rt_computation_us: int = 0
    rt_constraint_us: int = 0

    def sample_cpu_burst(self) -> int:
        """Sample a CPU burst duration."""
        lo = max(100, int(self.avg_cpu_burst_us * (1 - self.cpu_burst_variance)))
        hi = max(lo + 100, int(self.avg_cpu_burst_us * (1 + self.cpu_burst_variance)))
        return random.randint(lo, hi)

    def sample_block_duration(self) -> int:
        """Sample a blocking duration."""
        lo = max(100, int(self.avg_block_duration_us * (1 - self.block_variance)))
        hi = max(lo + 100, int(self.avg_block_duration_us * (1 + self.block_variance)))
        return random.randint(lo, hi)


@dataclass
class WorkloadProfile:
    """Describes a set of threads to create."""

    name: str
    thread_group_name: str
    num_threads: int = 1
    sched_mode: int = TH_MODE_TIMESHARE
    base_pri: int = BASEPRI_DEFAULT
    behavior: BehaviorProfile = field(default_factory=BehaviorProfile)


def create_workload(
    profile: WorkloadProfile,
) -> tuple[ThreadGroup, list[Thread], list[BehaviorProfile]]:
    """Create threads from a workload profile.

    Returns (thread_group, threads, behaviors) where behaviors[i] is the
    behavior profile for threads[i].
    """
    tg = ThreadGroup(profile.thread_group_name)
    SchedClutch(tg, num_clusters=1)

    threads = []
    behaviors = []
    for i in range(profile.num_threads):
        name = f"{profile.name}-{i}"
        thread = Thread(
            thread_group=tg,
            sched_mode=profile.sched_mode,
            base_pri=profile.base_pri,
            name=name,
            rt_period=profile.behavior.rt_period_us,
            rt_computation=profile.behavior.rt_computation_us,
            rt_constraint=profile.behavior.rt_constraint_us,
        )
        threads.append(thread)
        behaviors.append(profile.behavior)

    return tg, threads, behaviors


# ---------------------------------------------------------------------------
# Built-in scenario workloads
# ---------------------------------------------------------------------------

def interactive_app_workload() -> list[WorkloadProfile]:
    """Safari-like: short CPU bursts, long blocks, FG bucket."""
    return [
        WorkloadProfile(
            name="safari-main",
            thread_group_name="Safari",
            num_threads=2,
            base_pri=BASEPRI_FOREGROUND,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=2000,  # 2ms bursts
                avg_block_duration_us=100000,  # 100ms blocks (waiting for user)
            ),
        ),
        WorkloadProfile(
            name="safari-render",
            thread_group_name="Safari",
            num_threads=2,
            base_pri=BASEPRI_USER_INITIATED,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=5000,  # 5ms render bursts
                avg_block_duration_us=30000,  # 30ms between renders
            ),
        ),
    ]


def background_compile_workload() -> list[WorkloadProfile]:
    """Xcode-like: long CPU bursts, short blocks, DF/UT bucket."""
    return [
        WorkloadProfile(
            name="clang",
            thread_group_name="Xcode-Build",
            num_threads=4,
            base_pri=BASEPRI_DEFAULT,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=80000,  # 80ms CPU-heavy compilation
                avg_block_duration_us=5000,  # 5ms disk I/O
                cpu_burst_variance=0.4,
            ),
        ),
    ]


def media_playback_workload() -> list[WorkloadProfile]:
    """RT audio/video thread: periodic computation."""
    return [
        WorkloadProfile(
            name="audio-rt",
            thread_group_name="CoreAudio",
            num_threads=1,
            sched_mode=TH_MODE_REALTIME,
            base_pri=BASEPRI_REALTIME,
            behavior=BehaviorProfile(
                rt_period_us=33333,  # 30fps ~33ms period
                rt_computation_us=5000,  # 5ms computation
                rt_constraint_us=10000,  # 10ms constraint
            ),
        ),
    ]


def mixed_workload() -> list[WorkloadProfile]:
    """Mixed: interactive + compile + media competing."""
    profiles = []
    profiles.extend(interactive_app_workload())
    profiles.extend(background_compile_workload())
    profiles.extend(media_playback_workload())
    return profiles


def starvation_test_workload() -> list[WorkloadProfile]:
    """Heavy FG load with BG threads to verify BG gets CPU within WCEL."""
    return [
        WorkloadProfile(
            name="fg-heavy",
            thread_group_name="FG-App",
            num_threads=8,
            base_pri=BASEPRI_FOREGROUND,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=15000,  # 15ms bursts
                avg_block_duration_us=5000,  # 5ms blocks
            ),
        ),
        WorkloadProfile(
            name="bg-worker",
            thread_group_name="BG-Indexer",
            num_threads=2,
            base_pri=MAXPRI_THROTTLE,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=50000,  # 50ms CPU work
                avg_block_duration_us=10000,
            ),
        ),
    ]


def warp_demo_workload() -> list[WorkloadProfile]:
    """Demonstrate warp: bursty FG work arriving while lower QoS is running."""
    return [
        WorkloadProfile(
            name="fg-burst",
            thread_group_name="FG-Burst",
            num_threads=2,
            base_pri=BASEPRI_FOREGROUND,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=3000,  # 3ms quick bursts
                avg_block_duration_us=200000,  # 200ms between bursts
            ),
        ),
        WorkloadProfile(
            name="df-steady",
            thread_group_name="DF-Steady",
            num_threads=4,
            base_pri=BASEPRI_DEFAULT,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=20000,  # 20ms steady work
                avg_block_duration_us=10000,
            ),
        ),
        WorkloadProfile(
            name="bg-batch",
            thread_group_name="BG-Batch",
            num_threads=2,
            base_pri=MAXPRI_THROTTLE,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=100000,  # 100ms batch work
                avg_block_duration_us=5000,
            ),
        ),
    ]


def desktop_day_workload() -> list[WorkloadProfile]:
    """Everyday laptop mix: interactive apps + background services."""
    return [
        WorkloadProfile(
            name="browser-ui",
            thread_group_name="Browser",
            num_threads=3,
            base_pri=BASEPRI_FOREGROUND,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=2500,
                avg_block_duration_us=120000,
            ),
        ),
        WorkloadProfile(
            name="chat-ui",
            thread_group_name="ChatApp",
            num_threads=2,
            base_pri=BASEPRI_USER_INITIATED,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=3000,
                avg_block_duration_us=70000,
            ),
        ),
        WorkloadProfile(
            name="ide-index",
            thread_group_name="IDE",
            num_threads=3,
            base_pri=BASEPRI_DEFAULT,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=25000,
                avg_block_duration_us=15000,
                cpu_burst_variance=0.35,
            ),
        ),
        WorkloadProfile(
            name="photo-bg",
            thread_group_name="PhotoLibrary",
            num_threads=2,
            base_pri=MAXPRI_THROTTLE,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=60000,
                avg_block_duration_us=12000,
            ),
        ),
    ]


def rt_studio_workload() -> list[WorkloadProfile]:
    """Media studio: multiple RT streams plus non-RT app activity."""
    return [
        WorkloadProfile(
            name="audio-engine",
            thread_group_name="DAW",
            num_threads=1,
            sched_mode=TH_MODE_REALTIME,
            base_pri=BASEPRI_REALTIME,
            behavior=BehaviorProfile(
                rt_period_us=10000,
                rt_computation_us=2000,
                rt_constraint_us=3000,
            ),
        ),
        WorkloadProfile(
            name="video-capture",
            thread_group_name="Capture",
            num_threads=1,
            sched_mode=TH_MODE_REALTIME,
            base_pri=BASEPRI_REALTIME,
            behavior=BehaviorProfile(
                rt_period_us=33333,
                rt_computation_us=7000,
                rt_constraint_us=12000,
            ),
        ),
        WorkloadProfile(
            name="daw-ui",
            thread_group_name="DAW",
            num_threads=2,
            base_pri=BASEPRI_USER_INITIATED,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=3500,
                avg_block_duration_us=25000,
            ),
        ),
        WorkloadProfile(
            name="export-bg",
            thread_group_name="Exporter",
            num_threads=2,
            base_pri=BASEPRI_UTILITY,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=50000,
                avg_block_duration_us=8000,
            ),
        ),
    ]


def fixed_priority_service_workload() -> list[WorkloadProfile]:
    """Show fixed-priority threads competing with timeshare buckets."""
    return [
        WorkloadProfile(
            name="windowserver-fix",
            thread_group_name="WindowServer",
            num_threads=1,
            sched_mode=TH_MODE_FIXED,
            base_pri=BASEPRI_CONTROL,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=4000,
                avg_block_duration_us=6000,
            ),
        ),
        WorkloadProfile(
            name="foreground-app",
            thread_group_name="Editor",
            num_threads=3,
            base_pri=BASEPRI_FOREGROUND,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=8000,
                avg_block_duration_us=15000,
            ),
        ),
        WorkloadProfile(
            name="utility-sync",
            thread_group_name="SyncAgent",
            num_threads=2,
            base_pri=BASEPRI_UTILITY,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=30000,
                avg_block_duration_us=12000,
            ),
        ),
    ]


def cpu_storm_workload() -> list[WorkloadProfile]:
    """CPU-saturated system with heavy contention in multiple QoS lanes."""
    return [
        WorkloadProfile(
            name="fg-hot",
            thread_group_name="Renderer",
            num_threads=6,
            base_pri=BASEPRI_FOREGROUND,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=120000,
                avg_block_duration_us=1000,
                cpu_burst_variance=0.2,
            ),
        ),
        WorkloadProfile(
            name="df-hot",
            thread_group_name="CompilerFarm",
            num_threads=8,
            base_pri=BASEPRI_DEFAULT,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=100000,
                avg_block_duration_us=2000,
                cpu_burst_variance=0.25,
            ),
        ),
        WorkloadProfile(
            name="ut-batch",
            thread_group_name="Analytics",
            num_threads=4,
            base_pri=BASEPRI_UTILITY,
            behavior=BehaviorProfile(
                avg_cpu_burst_us=150000,
                avg_block_duration_us=3000,
                cpu_burst_variance=0.25,
            ),
        ),
    ]


SCENARIOS: dict[str, callable] = {
    "interactive": interactive_app_workload,
    "compile": background_compile_workload,
    "media": media_playback_workload,
    "mixed": mixed_workload,
    "starvation": starvation_test_workload,
    "warp": warp_demo_workload,
    "desktop": desktop_day_workload,
    "rt_studio": rt_studio_workload,
    "fixed": fixed_priority_service_workload,
    "cpu_storm": cpu_storm_workload,
}
