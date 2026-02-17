"""
Statistics collection and reporting for the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from xnu_sched.constants import BUCKET_NAMES, TH_BUCKET_SCHED_MAX

if TYPE_CHECKING:
    from xnu_sched.thread import Thread, ThreadGroup


@dataclass
class ThreadStats:
    """Per-thread statistics."""

    tid: int = 0
    name: str = ""
    thread_group: str = ""
    bucket: int = 0

    total_cpu_us: int = 0
    total_wait_us: int = 0
    total_block_us: int = 0
    context_switches: int = 0
    preemptions: int = 0

    # Scheduling latency tracking
    latencies: list[int] = field(default_factory=list)

    @property
    def avg_latency_us(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def max_latency_us(self) -> int:
        return max(self.latencies) if self.latencies else 0

    @property
    def p99_latency_us(self) -> int:
        if not self.latencies:
            return 0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.99)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]


@dataclass
class BucketStats:
    """Per-bucket aggregate statistics."""

    bucket: int = 0
    name: str = ""
    total_cpu_us: int = 0
    thread_count: int = 0
    total_latency_us: int = 0
    latency_samples: int = 0
    max_latency_us: int = 0
    starvation_events: int = 0  # times without CPU exceeding WCEL
    warp_activations: int = 0


class StatsCollector:
    """Collects and reports simulation statistics."""

    __slots__ = (
        "thread_stats",
        "bucket_stats",
        "total_context_switches",
        "total_preemptions",
        "simulation_duration",
        "processor_count",
        # Event counts
        "wakeup_count",
        "block_count",
        "quantum_expire_count",
        "tick_count",
        # Time tracking
        "_processor_busy",
    )

    def __init__(self, processor_count: int) -> None:
        self.thread_stats: dict[int, ThreadStats] = {}
        self.bucket_stats: dict[int, BucketStats] = {}
        self.total_context_switches: int = 0
        self.total_preemptions: int = 0
        self.simulation_duration: int = 0
        self.processor_count = processor_count
        self.wakeup_count: int = 0
        self.block_count: int = 0
        self.quantum_expire_count: int = 0
        self.tick_count: int = 0
        self._processor_busy: list[int] = [0] * processor_count

        for b in range(TH_BUCKET_SCHED_MAX):
            self.bucket_stats[b] = BucketStats(
                bucket=b, name=BUCKET_NAMES.get(b, "??")
            )

    def register_thread(self, thread: Thread) -> None:
        self.thread_stats[thread.tid] = ThreadStats(
            tid=thread.tid,
            name=thread.name,
            thread_group=thread.thread_group.name,
            bucket=thread.th_sched_bucket,
        )
        self.bucket_stats[thread.th_sched_bucket].thread_count += 1

    def record_dispatch(self, thread: Thread, timestamp: int) -> None:
        ts = self.thread_stats.get(thread.tid)
        if ts and thread.last_made_runnable_time > 0:
            latency = timestamp - thread.last_made_runnable_time
            ts.latencies.append(latency)
            bs = self.bucket_stats[thread.th_sched_bucket]
            bs.total_latency_us += latency
            bs.latency_samples += 1
            bs.max_latency_us = max(bs.max_latency_us, latency)

    def record_context_switch(self) -> None:
        self.total_context_switches += 1

    def record_preemption(self) -> None:
        self.total_preemptions += 1

    def finalize(self, threads: list[Thread], duration: int) -> None:
        """Collect final stats from thread objects."""
        self.simulation_duration = duration
        for thread in threads:
            ts = self.thread_stats.get(thread.tid)
            if ts:
                ts.total_cpu_us = thread.total_cpu_us
                ts.total_wait_us = thread.total_wait_us
                ts.context_switches = thread.context_switches
                ts.preemptions = thread.preemption_count
                self.bucket_stats[thread.th_sched_bucket].total_cpu_us += (
                    thread.total_cpu_us
                )

    def print_summary(self) -> None:
        """Print a formatted summary of simulation results."""
        total_cpu_capacity = self.simulation_duration * self.processor_count

        print("\n" + "=" * 80)
        print("XNU Clutch Scheduler Simulation Results")
        print("=" * 80)
        print(
            f"Duration: {self.simulation_duration / 1000:.1f}ms | "
            f"CPUs: {self.processor_count} | "
            f"Context Switches: {self.total_context_switches} | "
            f"Sched Ticks: {self.tick_count}"
        )
        print()

        # Per-bucket summary
        print("Per-Bucket Summary:")
        print(
            f"  {'Bucket':<8} {'Threads':>7} {'CPU(us)':>10} {'CPU%':>6} "
            f"{'AvgLat(us)':>11} {'MaxLat(us)':>11} {'P99Lat(us)':>11}"
        )
        print("  " + "-" * 72)
        for b in range(TH_BUCKET_SCHED_MAX):
            bs = self.bucket_stats[b]
            if bs.thread_count == 0:
                continue
            cpu_pct = (bs.total_cpu_us / total_cpu_capacity * 100) if total_cpu_capacity else 0
            avg_lat = (
                bs.total_latency_us / bs.latency_samples
                if bs.latency_samples
                else 0
            )

            # Compute p99 across all threads in this bucket
            all_lats = []
            for ts in self.thread_stats.values():
                if ts.bucket == b:
                    all_lats.extend(ts.latencies)
            p99 = 0
            if all_lats:
                sorted_lats = sorted(all_lats)
                p99 = sorted_lats[int(len(sorted_lats) * 0.99)]

            print(
                f"  {bs.name:<8} {bs.thread_count:>7} {bs.total_cpu_us:>10} "
                f"{cpu_pct:>5.1f}% {avg_lat:>11.0f} {bs.max_latency_us:>11} {p99:>11}"
            )

        print()

        # Per-thread detail
        print("Per-Thread Detail:")
        print(
            f"  {'Name':<20} {'TG':<12} {'Bucket':<6} {'CPU(us)':>10} "
            f"{'AvgLat':>8} {'MaxLat':>8} {'CSw':>5} {'Preempt':>7}"
        )
        print("  " + "-" * 82)
        for ts in sorted(self.thread_stats.values(), key=lambda x: -x.total_cpu_us):
            bucket_name = BUCKET_NAMES.get(ts.bucket, "??")
            print(
                f"  {ts.name:<20} {ts.thread_group:<12} {bucket_name:<6} "
                f"{ts.total_cpu_us:>10} {ts.avg_latency_us:>8.0f} "
                f"{ts.max_latency_us:>8} {ts.context_switches:>5} "
                f"{ts.preemptions:>7}"
            )

        print("=" * 80)
