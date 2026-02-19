"use client";

import type { Dispatch } from "@/lib/types";
import { Countdown } from "./countdown";

interface CurrentRunBarProps {
  dispatch: Dispatch | null;
  simulationRunning: boolean;
}

export function CurrentRunBar({ dispatch, simulationRunning }: CurrentRunBarProps) {
  const title = dispatch?.task.title ?? "No active task";
  const dispatchMeta = dispatch
    ? `${dispatch.life_area.name} • ${dispatch.task.urgency_label} • ${dispatch.decision}`
    : "";
  const meta = dispatch
    ? simulationRunning
      ? dispatchMeta
      : `${dispatchMeta} • simulation paused`
    : simulationRunning
      ? "Simulation running. Waiting for runnable work."
      : "Start simulation to dispatch work automatically.";

  return (
    <section className="current-run-bar">
      <div>
        <p className="section-eyebrow text-run-eyebrow">Currently Running</p>
        <h2>{title}</h2>
        <p className="current-run-meta">{meta}</p>
        {dispatch?.reason && (
          <p className="current-run-reason">
            Reason: {dispatch.reason}
          </p>
        )}
      </div>
      <Countdown
        endAt={dispatch?.focus_block_end_at}
        paused={!simulationRunning}
      />
    </section>
  );
}
