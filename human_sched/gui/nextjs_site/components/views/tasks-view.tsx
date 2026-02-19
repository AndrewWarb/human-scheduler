"use client";

import { useEffect, useState } from "react";
import { useApp } from "@/lib/app-context";
import { Card } from "../card";
import { Pill } from "../pill";
import { TaskActions } from "../task-actions";
import { TaskForm } from "../task-form";
import { XNU_URGENCY_LABELS } from "@/lib/types";
import type { Task } from "@/lib/types";

function formatTimestamp(iso: string | null): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function TaskItem({
  task,
  isActive,
  onAction,
  onUpdateWindow,
}: {
  task: Task;
  isActive: boolean;
  onAction: (id: number, action: "pause" | "resume" | "complete" | "delete") => void;
  onUpdateWindow: (
    taskId: number,
    body: {
      active_window_start_local?: string | null;
      active_window_end_local?: string | null;
    },
  ) => Promise<void>;
}) {
  const [windowStart, setWindowStart] = useState(task.active_window_start_local ?? "");
  const [windowEnd, setWindowEnd] = useState(task.active_window_end_local ?? "");
  const [windowError, setWindowError] = useState("");
  const [windowPending, setWindowPending] = useState(false);

  useEffect(() => {
    setWindowStart(task.active_window_start_local ?? "");
    setWindowEnd(task.active_window_end_local ?? "");
    setWindowError("");
  }, [task.id, task.active_window_start_local, task.active_window_end_local]);

  async function saveWindow() {
    if ((windowStart && !windowEnd) || (!windowStart && windowEnd)) {
      setWindowError("Set both start and end, or leave both empty.");
      return;
    }

    setWindowPending(true);
    setWindowError("");
    try {
      await onUpdateWindow(task.id, {
        active_window_start_local: windowStart || null,
        active_window_end_local: windowEnd || null,
      });
    } catch (err) {
      setWindowError(err instanceof Error ? err.message : String(err));
    } finally {
      setWindowPending(false);
    }
  }

  async function clearWindow() {
    setWindowPending(true);
    setWindowError("");
    try {
      await onUpdateWindow(task.id, {
        active_window_start_local: null,
        active_window_end_local: null,
      });
      setWindowStart("");
      setWindowEnd("");
    } catch (err) {
      setWindowError(err instanceof Error ? err.message : String(err));
    } finally {
      setWindowPending(false);
    }
  }

  return (
    <article className={`surface-item task-item-compact ${isActive ? "surface-item-active" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[1rem]">{task.title}</h3>
        <button
          type="button"
          className="icon-btn icon-btn-danger"
          aria-label={`Delete task ${task.title}`}
          title="Delete task"
          onClick={() => {
            if (!window.confirm(`Delete task "${task.title}"?`)) return;
            onAction(task.id, "delete");
          }}
        >
          ×
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Pill>ID: {task.id}</Pill>
        <Pill>
          {task.urgency_label}
          {XNU_URGENCY_LABELS[task.urgency_tier]
            ? ` (${XNU_URGENCY_LABELS[task.urgency_tier].short} / ${XNU_URGENCY_LABELS[task.urgency_tier].human})`
            : ""}
        </Pill>
        <Pill>State: {task.state}</Pill>
        {task.active_window_start_local && task.active_window_end_local && (
          <Pill>
            Window: {task.active_window_start_local}-{task.active_window_end_local}
          </Pill>
        )}
      </div>
      <p className="font-mono text-[0.8rem] text-mono-ink">
        Created: {formatTimestamp(task.created_at)}
      </p>
      {task.urgency_tier === "critical" && (
        <div className="grid gap-1">
          <p className="text-[0.72rem] uppercase tracking-[0.12em] text-muted">
            FIXPRI active window
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            <input
              type="time"
              className="field-control max-w-[8rem] py-[0.32rem] px-[0.45rem] text-[0.8rem]"
              value={windowStart}
              onChange={(e) => setWindowStart(e.target.value)}
              disabled={windowPending}
              aria-label={`Window start for ${task.title}`}
            />
            <span className="text-muted">to</span>
            <input
              type="time"
              className="field-control max-w-[8rem] py-[0.32rem] px-[0.45rem] text-[0.8rem]"
              value={windowEnd}
              onChange={(e) => setWindowEnd(e.target.value)}
              disabled={windowPending}
              aria-label={`Window end for ${task.title}`}
            />
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                void saveWindow();
              }}
              disabled={windowPending}
            >
              Save
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                void clearWindow();
              }}
              disabled={windowPending}
            >
              Clear
            </button>
          </div>
          {windowError && (
            <p className="min-h-[1.1em] text-[0.78rem] text-warning">{windowError}</p>
          )}
        </div>
      )}
      <TaskActions task={task} onAction={onAction} />
    </article>
  );
}

export function TasksView() {
  const { state, doTaskAction, doCreateTask, doUpdateTaskWindow } = useApp();

  const tasksByLifeArea = new Map<number, Task[]>();
  for (const area of state.lifeAreas) {
    tasksByLifeArea.set(area.id, []);
  }

  const orphanTasks: Task[] = [];
  for (const task of state.tasks) {
    const bucket = tasksByLifeArea.get(task.life_area_id);
    if (bucket) {
      bucket.push(task);
    } else {
      orphanTasks.push(task);
    }
  }

  return (
    <div className="animate-[fade-in_0.25s_ease]">
      <div className="grid grid-cols-1 gap-3.5">
        <Card className="tasks-create-card">
          <p className="section-eyebrow">Create Task</p>
          <TaskForm
            settings={state.settings}
            lifeAreas={state.lifeAreas}
            onSubmit={doCreateTask}
          />
        </Card>
      </div>

      <div className="grid grid-cols-2 max-[1080px]:grid-cols-1 gap-3.5 mt-3.5 items-start">
        {state.lifeAreas.length === 0 ? (
          <Card className="tasks-area-card">
            <p className="section-eyebrow">Tasks</p>
            <div className="text-muted italic">
              Create a life area first, then add tasks.
            </div>
          </Card>
        ) : (
          state.lifeAreas.map((area) => {
            const areaTasks = tasksByLifeArea.get(area.id) ?? [];

            return (
              <Card key={area.id} className="tasks-area-card">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="section-eyebrow">Life Area</p>
                    <h3 className="text-[1.08rem]">{area.name}</h3>
                  </div>
                  <Pill>Tasks: {areaTasks.length}</Pill>
                </div>

                <div className="grid gap-2.5">
                  {areaTasks.length === 0 ? (
                    <div className="text-muted italic">
                      No tasks in this life area.
                    </div>
                  ) : (
                    areaTasks.map((task) => (
                      <TaskItem
                        key={task.id}
                        task={task}
                        isActive={state.dispatch?.task.id === task.id}
                        onAction={doTaskAction}
                        onUpdateWindow={doUpdateTaskWindow}
                      />
                    ))
                  )}
                </div>
              </Card>
            );
          })
        )}

        {orphanTasks.length > 0 && (
          <Card className="tasks-area-card">
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="section-eyebrow">Unassigned</p>
                <h3 className="text-[1.08rem]">Orphaned Tasks</h3>
              </div>
              <Pill>Tasks: {orphanTasks.length}</Pill>
            </div>
            <div className="grid gap-2.5">
              {orphanTasks.map((task) => (
                <TaskItem
                  key={task.id}
                  task={task}
                  isActive={state.dispatch?.task.id === task.id}
                  onAction={doTaskAction}
                  onUpdateWindow={doUpdateTaskWindow}
                />
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
