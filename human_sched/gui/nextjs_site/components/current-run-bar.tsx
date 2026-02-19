"use client";

import type { Dispatch } from "@/lib/types";
import { useApp } from "@/lib/app-context";
import { Countdown } from "./countdown";

interface CurrentRunBarProps {
  dispatch: Dispatch | null;
  simulationRunning: boolean;
}

export function CurrentRunBar({ dispatch, simulationRunning }: CurrentRunBarProps) {
  const { doTaskAction } = useApp();
  const title = dispatch?.task.title ?? "No active task";
  const dispatchMeta = dispatch
    ? `${dispatch.life_area.name} • ${dispatch.task.urgency_label} • ${dispatch.decision} • ${dispatch.focus_block_hours.toFixed(2)}h block`
    : "";
  const meta = dispatch
    ? simulationRunning
      ? dispatchMeta
      : `${dispatchMeta} • simulation paused`
    : simulationRunning
      ? "Simulation running. Waiting for runnable work."
      : "Start simulation to dispatch work automatically.";

  const taskId = dispatch?.task?.id ?? null;

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
        {taskId !== null && (
          <div className="flex gap-2 mt-2">
            <button
              className="btn btn-ghost"
              onClick={() => doTaskAction(taskId, "pause")}
            >
              Pause
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => doTaskAction(taskId, "complete")}
            >
              Complete
            </button>
          </div>
        )}
      </div>
      <Countdown
        endAt={dispatch?.focus_block_end_at}
        paused={!simulationRunning}
      />
    </section>
  );
}
