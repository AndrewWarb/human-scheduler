"use client";

import { useApp } from "@/lib/app-context";
import { Card } from "../card";
import { Pill } from "../pill";

export function DashboardView() {
  const { state, doWhatNext, doTaskAction, refreshAll } = useApp();
  const dispatch = state.dispatch;

  function handlePauseCurrent() {
    const taskId = dispatch?.task?.id;
    if (!taskId) return;
    doTaskAction(taskId, "pause");
  }

  function handleCompleteCurrent() {
    const taskId = dispatch?.task?.id;
    if (!taskId) return;
    doTaskAction(taskId, "complete");
  }

  return (
    <div className="animate-[fade-in_0.25s_ease]">
      <div className="grid grid-cols-2 gap-3.5 max-[920px]:grid-cols-1">
        <Card hero>
          <p className="section-eyebrow">Primary Action</p>
          <h3 className="text-[1.08rem]">What should I do now?</h3>
          <p className="text-muted">
            This action is atomic: select + dispatch in one scheduler operation.
          </p>
          <button
            className="btn btn-primary text-base px-4 py-3"
            onClick={doWhatNext}
          >
            What Next
          </button>
          <div className="text-[0.83rem] text-muted">
            {dispatch
              ? `${dispatch.decision.toUpperCase()}: ${dispatch.task.title}`
              : "No recommendation yet."}
          </div>
        </Card>

        <Card>
          <p className="section-eyebrow">Quick Actions</p>
          <h3 className="text-[1.08rem]">Running Task Controls</h3>
          <div className="flex gap-2 flex-wrap">
            <button
              className="btn btn-ghost"
              onClick={handlePauseCurrent}
            >
              Pause
            </button>
            <button
              className="btn btn-ghost"
              onClick={handleCompleteCurrent}
            >
              Complete
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => refreshAll()}
            >
              Refresh
            </button>
          </div>
          <p className="text-muted">
            Select a task with What Next first.
          </p>
        </Card>
      </div>

      <Card className="mt-3.5">
        <p className="section-eyebrow">Current Recommendation</p>
        <h3 className="text-[1.08rem]">
          {dispatch?.task.title ?? "None"}
        </h3>
        {dispatch?.reason && (
          <p className="font-mono text-[0.84rem] text-mono-ink">
            {dispatch.reason}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Pill>
            Life Area: {dispatch?.life_area.name ?? "--"}
          </Pill>
          <Pill>
            Urgency: {dispatch?.task.urgency_label ?? "--"}
          </Pill>
          <Pill>
            Decision: {dispatch?.decision ?? "--"}
          </Pill>
          <Pill>
            Focus Block:{" "}
            {dispatch ? `${dispatch.focus_block_hours.toFixed(2)}h` : "--"}
          </Pill>
        </div>
      </Card>
    </div>
  );
}
