"use client";

import type { Task } from "@/lib/types";

interface TaskActionsProps {
  task: Task;
  onAction: (taskId: number, action: "pause" | "resume" | "complete") => void;
}

export function TaskActions({ task, onAction }: TaskActionsProps) {
  const actions: { label: string; action: "pause" | "resume" | "complete" }[] =
    [];

  if (task.state === "running" || task.state === "runnable") {
    actions.push({ label: "Pause", action: "pause" });
  }
  if (task.state === "waiting") {
    actions.push({ label: "Resume", action: "resume" });
  }
  if (task.state !== "terminated") {
    actions.push({ label: "Complete", action: "complete" });
  }

  if (actions.length === 0) {
    return <span className="text-muted">No actions available</span>;
  }

  return (
    <div className="flex gap-2 flex-wrap">
      {actions.map(({ label, action }) => (
        <button
          key={action}
          className="btn btn-ghost"
          onClick={(e) => {
            e.stopPropagation();
            onAction(task.id, action);
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
