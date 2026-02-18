"use client";

import { useRef } from "react";
import type { AppSettings, LifeArea } from "@/lib/types";

interface TaskFiltersProps {
  settings: AppSettings | null;
  lifeAreas: LifeArea[];
  onApply: (filters: {
    life_area_id?: string;
    urgency?: string;
    state?: string;
  }) => void;
}

export function TaskFilters({
  settings,
  lifeAreas,
  onApply,
}: TaskFiltersProps) {
  const areaRef = useRef<HTMLSelectElement>(null);
  const urgencyRef = useRef<HTMLSelectElement>(null);
  const stateRef = useRef<HTMLSelectElement>(null);

  function handleApply() {
    onApply({
      life_area_id: areaRef.current?.value || undefined,
      urgency: urgencyRef.current?.value || undefined,
      state: stateRef.current?.value || undefined,
    });
  }

  return (
    <div className="grid gap-2">
      <label className="field-label">
        Life Area
        <select
          ref={areaRef}
          className="field-control"
        >
          <option value="">All</option>
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
          ref={urgencyRef}
          className="field-control"
        >
          <option value="">All</option>
          {(settings?.urgency_tiers ?? []).map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>
      <label className="field-label">
        State
        <select
          ref={stateRef}
          className="field-control"
        >
          <option value="">All</option>
          {(settings?.thread_states ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        onClick={handleApply}
        className="btn btn-ghost"
      >
        Apply Filters
      </button>
    </div>
  );
}
