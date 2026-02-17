#!/usr/bin/env python3
"""
Randomized long-run parity stress runner for the scheduler simulator.

This script runs:
1) parity_harness.py once (unless --skip-harness), then
2) many randomized scenario runs with reproducible seeds/durations/CPU counts.
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from simulator.workload import SCENARIOS


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class StressCase:
    index: int
    scenario: str
    cpus: int
    duration_ms: int
    seed: int


def _parse_scenarios(raw: str | None) -> list[str]:
    if raw is None:
        return sorted(SCENARIOS.keys())

    names = [name.strip() for name in raw.split(",") if name.strip()]
    invalid = [name for name in names if name not in SCENARIOS]
    if invalid:
        raise ValueError(
            f"Unknown scenario(s): {', '.join(invalid)}; valid: {', '.join(sorted(SCENARIOS.keys()))}"
        )
    if not names:
        raise ValueError("No scenarios selected")
    return names


def _build_cases(
    total_cases: int,
    scenarios: list[str],
    cpus_min: int,
    cpus_max: int,
    duration_min_ms: int,
    duration_max_ms: int,
    master_seed: int,
) -> list[StressCase]:
    rng = random.Random(master_seed)
    picked: list[StressCase] = []

    if total_cases >= len(scenarios):
        for scenario in scenarios:
            picked.append(
                StressCase(
                    index=0,
                    scenario=scenario,
                    cpus=rng.randint(cpus_min, cpus_max),
                    duration_ms=rng.randint(duration_min_ms, duration_max_ms),
                    seed=rng.randint(0, (1 << 31) - 1),
                )
            )

    while len(picked) < total_cases:
        picked.append(
            StressCase(
                index=0,
                scenario=rng.choice(scenarios),
                cpus=rng.randint(cpus_min, cpus_max),
                duration_ms=rng.randint(duration_min_ms, duration_max_ms),
                seed=rng.randint(0, (1 << 31) - 1),
            )
        )

    rng.shuffle(picked)
    cases: list[StressCase] = []
    for idx, case in enumerate(picked, start=1):
        cases.append(
            StressCase(
                index=idx,
                scenario=case.scenario,
                cpus=case.cpus,
                duration_ms=case.duration_ms,
                seed=case.seed,
            )
        )
    return cases


def _run_command(args: list[str], timeout_sec: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )


def _run_case(case: StressCase, timeout_sec: int) -> None:
    cmd = [
        sys.executable,
        "main.py",
        case.scenario,
        "--cpus",
        str(case.cpus),
        "--duration",
        str(case.duration_ms),
        "--no-stats",
        "--seed",
        str(case.seed),
    ]
    result = _run_command(cmd, timeout_sec=timeout_sec)
    if result.returncode != 0:
        raise RuntimeError(
            "\n".join(
                [
                    f"Stress case {case.index} failed.",
                    f"Command: {' '.join(cmd)}",
                    f"Exit code: {result.returncode}",
                    "----- stdout -----",
                    result.stdout.rstrip(),
                    "----- stderr -----",
                    result.stderr.rstrip(),
                ]
            )
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run randomized long-run parity stress checks."
    )
    parser.add_argument(
        "--cases",
        type=int,
        default=80,
        help="Number of randomized simulation runs (default: 80)",
    )
    parser.add_argument(
        "--master-seed",
        type=int,
        default=1,
        help="Master RNG seed for reproducible case generation (default: 1)",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=30,
        help="Per-case subprocess timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--cpus-min",
        type=int,
        default=1,
        help="Minimum CPUs per random run (default: 1)",
    )
    parser.add_argument(
        "--cpus-max",
        type=int,
        default=8,
        help="Maximum CPUs per random run (default: 8)",
    )
    parser.add_argument(
        "--duration-min-ms",
        type=int,
        default=50,
        help="Minimum random duration in milliseconds (default: 50)",
    )
    parser.add_argument(
        "--duration-max-ms",
        type=int,
        default=3000,
        help="Maximum random duration in milliseconds (default: 3000)",
    )
    parser.add_argument(
        "--scenarios",
        type=str,
        default=None,
        help=(
            "Comma-separated scenarios to include (default: all). "
            f"Available: {', '.join(sorted(SCENARIOS.keys()))}"
        ),
    )
    parser.add_argument(
        "--skip-harness",
        action="store_true",
        help="Skip parity_harness.py pre-check",
    )
    args = parser.parse_args()

    if args.cases <= 0:
        raise ValueError("--cases must be > 0")
    if args.cpus_min <= 0 or args.cpus_max <= 0 or args.cpus_min > args.cpus_max:
        raise ValueError("invalid CPU range")
    if (
        args.duration_min_ms <= 0
        or args.duration_max_ms <= 0
        or args.duration_min_ms > args.duration_max_ms
    ):
        raise ValueError("invalid duration range")

    scenarios = _parse_scenarios(args.scenarios)
    cases = _build_cases(
        total_cases=args.cases,
        scenarios=scenarios,
        cpus_min=args.cpus_min,
        cpus_max=args.cpus_max,
        duration_min_ms=args.duration_min_ms,
        duration_max_ms=args.duration_max_ms,
        master_seed=args.master_seed,
    )

    print(
        "Stress config: "
        f"cases={args.cases}, master_seed={args.master_seed}, "
        f"cpus=[{args.cpus_min},{args.cpus_max}], "
        f"duration_ms=[{args.duration_min_ms},{args.duration_max_ms}], "
        f"scenarios={','.join(scenarios)}"
    )

    start = time.monotonic()

    if not args.skip_harness:
        print("[0] parity_harness.py")
        result = _run_command([sys.executable, "parity_harness.py"], timeout_sec=args.timeout_sec)
        if result.returncode != 0:
            print(result.stdout.rstrip())
            print(result.stderr.rstrip(), file=sys.stderr)
            return result.returncode

    scenario_counts: dict[str, int] = {name: 0 for name in scenarios}
    for case in cases:
        scenario_counts[case.scenario] += 1
        print(
            f"[{case.index}/{len(cases)}] "
            f"{case.scenario} cpus={case.cpus} duration_ms={case.duration_ms} seed={case.seed}"
        )
        _run_case(case, timeout_sec=args.timeout_sec)

    elapsed = time.monotonic() - start
    counts_str = ", ".join(f"{name}={scenario_counts[name]}" for name in sorted(scenario_counts))
    print(f"Stress parity passed: {len(cases)} randomized runs in {elapsed:.2f}s")
    print(f"Scenario coverage: {counts_str}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
