#!/usr/bin/env python3
"""
XNU Clutch Scheduler - Discrete-Event Simulation

A faithful Python simulation of the XNU kernel's Clutch scheduler,
modeling the full 3-level hierarchy plus RT thread scheduling on a
single cluster.

Usage:
  python main.py [scenario] [options]

Scenarios:
  interactive  - Safari-like: short CPU bursts, long blocks
  compile      - Xcode-like: long CPU bursts, short blocks
  media        - RT audio/video thread: periodic computation
  mixed        - All of the above competing (default)
  starvation   - Heavy FG load with BG threads
  warp         - Demonstrate warp mechanism
  desktop      - Everyday desktop app mix
  rt_studio    - Multiple RT media streams + app activity
  fixed        - Fixed-priority service vs timeshare threads
  cpu_storm    - CPU-saturated contention across QoS lanes

Options:
  --env-file PATH Path to env defaults file (default: .env)
  --cpus N       Number of processors (default: 4)
  --duration MS  Simulation duration in milliseconds (default: 1000)
  --trace / --no-trace
                 Print per-event trace
  --switches / --no-switches
                 Print processor run-target switch timeline
  --stats / --no-stats
                 Print summary statistics
  --seed N       Random seed for reproducibility

Env keys in .env:
  SCENARIO, CPUS, DURATION_MS, TRACE, SWITCHES, STATS, SEED
"""

from __future__ import annotations

import argparse
from pathlib import Path
import random
import sys

from simulator.engine import SimulationEngine
from simulator.workload import (
    SCENARIOS,
    create_workload,
)

DEFAULT_ENV_FILE = ".env"
TRUE_VALUES = {"1", "true", "yes", "on", "y"}
FALSE_VALUES = {"0", "false", "no", "off", "n"}


def _warn_env(msg: str) -> None:
    print(f"Warning: {msg}", file=sys.stderr)


def _load_env_file(path: str) -> dict[str, str]:
    """Load simple KEY=VALUE settings from an env file."""
    env_path = Path(path)
    if not env_path.exists():
        return {}

    env: dict[str, str] = {}
    for lineno, line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[7:].strip()
        if "=" not in text:
            _warn_env(f"Ignoring invalid env line {lineno} in {path!r}: {line!r}")
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            _warn_env(f"Ignoring empty key on env line {lineno} in {path!r}")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key] = value
    return env


def _env_int(env: dict[str, str], key: str, default: int, minimum: int = 1) -> int:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        _warn_env(f"{key} must be an integer, got {raw!r}. Using {default}.")
        return default
    if value < minimum:
        _warn_env(f"{key} must be >= {minimum}, got {value}. Using {default}.")
        return default
    return value


def _env_opt_int(env: dict[str, str], key: str, default: int | None) -> int | None:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        _warn_env(f"{key} must be an integer, got {raw!r}. Using {default}.")
        return default


def _env_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    _warn_env(
        f"{key} must be one of {sorted(TRUE_VALUES | FALSE_VALUES)}, got {raw!r}. "
        f"Using {default}."
    )
    return default


def _defaults_from_env(env: dict[str, str]) -> dict[str, object]:
    scenario = env.get("SCENARIO", "mixed")
    if scenario not in SCENARIOS:
        _warn_env(f"SCENARIO={scenario!r} is unknown. Using 'mixed'.")
        scenario = "mixed"

    return {
        "scenario": scenario,
        "cpus": _env_int(env, "CPUS", default=4),
        "duration": _env_int(env, "DURATION_MS", default=1000),
        "trace": _env_bool(env, "TRACE", default=False),
        "switches": _env_bool(env, "SWITCHES", default=True),
        "stats": _env_bool(env, "STATS", default=True),
        "seed": _env_opt_int(env, "SEED", default=None),
    }


def run_scenario(
    scenario_name: str,
    num_cpus: int = 4,
    duration_ms: int = 1000,
    trace: bool = False,
    seed: int | None = None,
) -> SimulationEngine:
    """Set up and run a simulation scenario."""
    if seed is not None:
        random.seed(seed)

    duration_us = duration_ms * 1000

    # Create engine
    engine = SimulationEngine(num_cpus=num_cpus, trace=trace)

    # Get workload profiles
    if scenario_name not in SCENARIOS:
        print(f"Unknown scenario: {scenario_name}")
        print(f"Available: {', '.join(SCENARIOS.keys())}")
        sys.exit(1)

    profiles = SCENARIOS[scenario_name]()

    # Track which thread groups we've already created, to share the same TG
    tg_cache: dict[str, tuple] = {}

    for profile in profiles:
        if profile.thread_group_name in tg_cache:
            # Reuse existing thread group
            existing_tg, _, _ = tg_cache[profile.thread_group_name]
            # Create threads under existing TG
            from xnu_sched.thread import Thread
            threads = []
            behaviors = []
            for i in range(profile.num_threads):
                name = f"{profile.name}-{i}"
                thread = Thread(
                    thread_group=existing_tg,
                    sched_mode=profile.sched_mode,
                    base_pri=profile.base_pri,
                    name=name,
                    rt_period=profile.behavior.rt_period_us,
                    rt_computation=profile.behavior.rt_computation_us,
                    rt_constraint=profile.behavior.rt_constraint_us,
                )
                threads.append(thread)
                behaviors.append(profile.behavior)
        else:
            tg, threads, behaviors = create_workload(profile)
            tg_cache[profile.thread_group_name] = (tg, threads, behaviors)

        # Stagger start times slightly to avoid thundering herd
        for i, (thread, behavior) in enumerate(zip(threads, behaviors)):
            start_time = i * 100  # 100us stagger
            engine.add_thread(thread, behavior, start_time=start_time)

    # Run simulation
    print(f"Running '{scenario_name}' scenario: {num_cpus} CPUs, {duration_ms}ms")
    print(f"Threads: {len(engine.scheduler.all_threads)}")
    engine.run(duration_us)

    return engine


def main() -> None:
    argv = sys.argv[1:]

    # Parse env-file first so we can use it for argument defaults.
    env_parser = argparse.ArgumentParser(add_help=False)
    env_parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    env_args, _ = env_parser.parse_known_args(argv)
    env = _load_env_file(env_args.env_file)
    defaults = _defaults_from_env(env)

    parser = argparse.ArgumentParser(
        description="XNU Clutch Scheduler Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--env-file",
        default=env_args.env_file,
        help=f"Path to env defaults file (default: {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        default=defaults["scenario"],
        choices=list(SCENARIOS.keys()),
        help=f"Simulation scenario (default: {defaults['scenario']})",
    )
    parser.add_argument(
        "--cpus",
        type=int,
        default=defaults["cpus"],
        help=f"Number of processors (default: {defaults['cpus']})",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=defaults["duration"],
        help=f"Simulation duration in ms (default: {defaults['duration']})",
    )
    parser.add_argument(
        "--trace",
        action=argparse.BooleanOptionalAction,
        default=defaults["trace"],
        help=f"Print per-event trace (default: {'on' if defaults['trace'] else 'off'})",
    )
    parser.add_argument(
        "--switches",
        action=argparse.BooleanOptionalAction,
        default=defaults["switches"],
        help=(
            "Print processor run-target switch timeline "
            f"(default: {'on' if defaults['switches'] else 'off'})"
        ),
    )
    parser.add_argument(
        "--stats",
        action=argparse.BooleanOptionalAction,
        default=defaults["stats"],
        help=f"Print summary statistics (default: {'on' if defaults['stats'] else 'off'})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=defaults["seed"],
        help=f"Random seed for reproducibility (default: {defaults['seed']})",
    )

    args = parser.parse_args(argv)

    engine = run_scenario(
        scenario_name=args.scenario,
        num_cpus=args.cpus,
        duration_ms=args.duration,
        trace=args.trace,
        seed=args.seed,
    )

    # Print trace if requested
    if args.trace:
        print("\n--- Event Trace ---")
        for line in engine.scheduler.trace_log[-200:]:
            print(line)
        if len(engine.scheduler.trace_log) > 200:
            print(f"... ({len(engine.scheduler.trace_log) - 200} more events)")

    if args.switches:
        print("\n--- Processor Switch Timeline ---")
        for line in engine.scheduler.processor_switch_log:
            print(line)

    # Print stats
    if args.stats:
        engine.stats.print_summary()


if __name__ == "__main__":
    main()
