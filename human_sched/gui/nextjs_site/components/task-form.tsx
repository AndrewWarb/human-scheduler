"use client";

import { useState } from "react";
import { XNU_URGENCY_LABELS } from "@/lib/types";
import type { AppSettings, LifeArea } from "@/lib/types";

interface TaskFormProps {
  settings: AppSettings | null;
  lifeAreas: LifeArea[];
  onSubmit: (body: {
    title: string;
    life_area_id: number;
    urgency_tier: string;
    active_window_start_local?: string | null;
    active_window_end_local?: string | null;
  }) => Promise<void>;
  fixedLifeAreaId?: number;
  compact?: boolean;
}

export function TaskForm({ settings, lifeAreas, onSubmit, fixedLifeAreaId, compact }: TaskFormProps) {
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");

    const form = e.currentTarget;
    const data = new FormData(form);
    const urgencyTier = data.get("urgency_tier") as string;
    const activeWindowStart = (data.get("active_window_start_local") as string).trim();
    const activeWindowEnd = (data.get("active_window_end_local") as string).trim();

    if ((activeWindowStart && !activeWindowEnd) || (!activeWindowStart && activeWindowEnd)) {
      setError("Set both active window start and end times, or leave both blank.");
      return;
    }
    if ((activeWindowStart || activeWindowEnd) && urgencyTier !== "critical") {
      setError("Active window times are only supported for Critical (FIXPRI) tasks.");
      return;
    }

    try {
      await onSubmit({
        title: (data.get("title") as string).trim(),
        life_area_id: fixedLifeAreaId ?? Number(data.get("life_area_id")),
        urgency_tier: urgencyTier,
        active_window_start_local: activeWindowStart || null,
        active_window_end_local: activeWindowEnd || null,
      });
      form.reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className={compact ? "grid gap-1.5" : "grid gap-2"}>
      <label className="field-label">
        {!compact && "Title"}
        <input
          name="title"
          type="text"
          required
          placeholder={compact ? "New task title…" : undefined}
          className="field-control"
        />
      </label>
      {fixedLifeAreaId === undefined && (
        <label className="field-label">
          Life Area
          <select
            name="life_area_id"
            required
            className="field-control"
          >
            {lifeAreas.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="field-label">
        {!compact && "Urgency"}
        <select
          name="urgency_tier"
          required
          className="field-control"
        >
          {(settings?.urgency_tiers ?? []).map((t) => {
            const xnu = XNU_URGENCY_LABELS[t.value];
            return (
              <option key={t.value} value={t.value}>
                {xnu
                  ? `${t.label} (${xnu.short} / ${xnu.xnu}) - ${xnu.human}`
                  : t.label}
              </option>
            );
          })}
        </select>
      </label>
      <div className="grid grid-cols-2 gap-2 max-[620px]:grid-cols-1">
        <label className="field-label">
          {!compact && "Active Start (optional)"}
          <input
            name="active_window_start_local"
            type="time"
            placeholder={compact ? "Start" : undefined}
            className="field-control"
          />
        </label>
        <label className="field-label">
          {!compact && "Active End (optional)"}
          <input
            name="active_window_end_local"
            type="time"
            placeholder={compact ? "End" : undefined}
            className="field-control"
          />
        </label>
      </div>
      <button
        type="submit"
        className={compact ? "btn btn-primary btn-sm" : "btn btn-primary"}
      >
        Create Task
      </button>
      {error && (
        <p className="min-h-[1.1em] text-[0.8rem] text-warning">{error}</p>
      )}
    </form>
  );
}
