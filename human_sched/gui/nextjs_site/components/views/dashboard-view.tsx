"use client";

import { useApp } from "@/lib/app-context";

export function DashboardView() {
  const { state } = useApp();

  return (
    <div className="animate-[fade-in_0.25s_ease]">
      <p className="text-muted text-center py-8">
        {state.dispatch
          ? "Task details and controls are shown in the run bar above."
          : state.simulationRunning
            ? "Simulation running. Waiting for runnable work."
            : "Start the simulation to begin scheduling."}
      </p>
    </div>
  );
}
