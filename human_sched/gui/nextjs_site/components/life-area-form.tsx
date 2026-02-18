"use client";

import { useState } from "react";

interface LifeAreaFormProps {
  onSubmit: (body: { name: string; description: string }) => Promise<void>;
}

export function LifeAreaForm({ onSubmit }: LifeAreaFormProps) {
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");

    const form = e.currentTarget;
    const data = new FormData(form);

    try {
      await onSubmit({
        name: (data.get("name") as string).trim(),
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
        Name
        <input
          name="name"
          type="text"
          required
          className="field-control"
        />
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
        Create Life Area
      </button>
      {error && (
        <p className="min-h-[1.1em] text-[0.8rem] text-warning">{error}</p>
      )}
    </form>
  );
}
