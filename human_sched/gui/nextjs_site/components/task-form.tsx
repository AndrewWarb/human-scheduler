"use client";

import { useState } from "react";
import type { AppSettings, LifeArea } from "@/lib/types";

const XNU_URGENCY_LABELS: Record<
  string,
  { short: string; xnu: string; human: string }
> = {
  critical: {
    short: "FIXPRI",
    xnu: "TH_BUCKET_FIXPRI",
    human: "Fixed-priority",
  },
  active_focus: {
    short: "FG",
    xnu: "TH_BUCKET_SHARE_FG",
    human: "Foreground",
  },
  important: {
    short: "IN",
    xnu: "TH_BUCKET_SHARE_IN",
    human: "User-initiated",
  },
  normal: {
    short: "DF",
    xnu: "TH_BUCKET_SHARE_DF",
    human: "Default",
  },
  maintenance: {
    short: "UT",
    xnu: "TH_BUCKET_SHARE_UT",
    human: "Utility",
  },
  someday: {
    short: "BG",
    xnu: "TH_BUCKET_SHARE_BG",
    human: "Background",
  },
};

interface TaskFormProps {
  settings: AppSettings | null;
  lifeAreas: LifeArea[];
  onSubmit: (body: {
    title: string;
    life_area_id: number;
    urgency_tier: string;
  }) => Promise<void>;
}

export function TaskForm({ settings, lifeAreas, onSubmit }: TaskFormProps) {
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");

    const form = e.currentTarget;
    const data = new FormData(form);

    try {
      await onSubmit({
        title: (data.get("title") as string).trim(),
        life_area_id: Number(data.get("life_area_id")),
        urgency_tier: data.get("urgency_tier") as string,
      });
      form.reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-2">
      <label className="field-label">
        Title
        <input
          name="title"
          type="text"
          required
          className="field-control"
        />
      </label>
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
      <label className="field-label">
        Urgency
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
      <button
        type="submit"
        className="btn btn-primary"
      >
        Create Task
      </button>
      {error && (
        <p className="min-h-[1.1em] text-[0.8rem] text-warning">{error}</p>
      )}
    </form>
  );
}
