"use client";

import { useState } from "react";
import type { AppSettings, LifeArea } from "@/lib/types";

interface TaskFormProps {
  settings: AppSettings | null;
  lifeAreas: LifeArea[];
  onSubmit: (body: {
    title: string;
    life_area_id: number;
    urgency_tier: string;
    description: string;
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
        description: (data.get("description") as string).trim(),
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
          {(settings?.urgency_tiers ?? []).map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <label className="field-label">
        Description
        <textarea
          name="description"
          rows={2}
          className="field-control"
        />
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
