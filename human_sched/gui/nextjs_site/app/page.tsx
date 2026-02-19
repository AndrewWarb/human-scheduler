"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { AppProvider, useApp } from "@/lib/app-context";
import { ConnectionPill } from "@/components/connection-pill";
import { CurrentRunBar } from "@/components/current-run-bar";
import { TabNav, type TabId } from "@/components/tab-nav";
import { DashboardView } from "@/components/views/dashboard-view";
import { TasksView } from "@/components/views/tasks-view";
import { LifeAreasView } from "@/components/views/life-areas-view";
import { ActivityView } from "@/components/views/activity-view";
import { SettingsView } from "@/components/views/settings-view";

function playSwitchChime() {
  const ctx = new AudioContext();
  const now = ctx.currentTime;

  for (const [freq, start] of [[600, 0], [900, 0.12]] as const) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "square";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.25, now + start);
    gain.gain.exponentialRampToValueAtTime(0.001, now + start + 0.18);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now + start);
    osc.stop(now + start + 0.18);
  }

  setTimeout(() => void ctx.close(), 500);
}

function AppShell() {
  const [activeTab, setActiveTab] = useState<TabId>("dashboard");
  const { state, sseStatus, startSimulation, stopSimulation, resetSimulation } = useApp();
  const prevTaskIdRef = useRef<number | null>(null);
  const [flashing, setFlashing] = useState(false);

  const handleAnimationEnd = useCallback(() => setFlashing(false), []);

  useEffect(() => {
    const dispatch = state.dispatch;
    if (!dispatch) return;

    const currentTaskId = dispatch.task.id;
    const prevTaskId = prevTaskIdRef.current;
    prevTaskIdRef.current = currentTaskId;

    if (prevTaskId !== null && currentTaskId !== prevTaskId) {
      playSwitchChime();
      setFlashing(true);
    }
  }, [state.dispatch]);

  return (
    <div className="app-shell animate-[fade-in_0.45s_ease]">
      {flashing && (
        <div
          className="switch-flash-overlay"
          onAnimationEnd={handleAnimationEnd}
          aria-hidden="true"
        />
      )}
      {/* Background shapes */}
      <div className="ambient-orb ambient-orb-right" aria-hidden="true" />
      <div className="ambient-orb ambient-orb-left" aria-hidden="true" />

      {/* Top bar */}
      <header className="app-header">
        <div>
          <p className="app-kicker">Human Scheduler • Live Console</p>
          <h1 className="app-title">Focus Control Panel</h1>
          <p className="app-subtitle">
            Start the simulation once, follow live recommendations, and track every state change in
            one quiet control surface.
          </p>
        </div>
        <ConnectionPill status={sseStatus} />
      </header>

      <section className="sim-launch" aria-label="Simulation controls">
        <button
          type="button"
          className={`sim-launch-btn${state.simulationRunning ? " sim-launch-btn-running" : ""}`}
          aria-label={state.simulationRunning ? "Stop simulation" : "Start simulation"}
          title={state.simulationRunning ? "Stop simulation" : "Start simulation"}
          onClick={() => void (state.simulationRunning ? stopSimulation() : startSimulation())}
        >
          {state.simulationRunning && <span className="sim-pulse-dot" />}
          {state.simulationRunning ? "Stop Simulation" : "Start Simulation"}
        </button>
        <button
          type="button"
          className="sim-launch-btn sim-launch-btn-secondary"
          aria-label="Reset simulation to 0"
          title="Reset simulation to 0"
          onClick={() => void resetSimulation()}
        >
          ↺
        </button>
      </section>

      <CurrentRunBar
        dispatch={state.dispatch}
        simulationRunning={state.simulationRunning}
      />

      <TabNav active={activeTab} onChange={setActiveTab} />

      <main>
        {activeTab === "dashboard" && <DashboardView />}
        {activeTab === "tasks" && <TasksView />}
        {activeTab === "life-areas" && <LifeAreasView />}
        {activeTab === "activity" && <ActivityView />}
        {activeTab === "settings" && <SettingsView />}
      </main>

      {/* Toast */}
      {state.toast && (
        <aside className="toast-panel animate-[fade-in_0.2s_ease]" aria-live="polite">
          {state.toast}
        </aside>
      )}
    </div>
  );
}

export default function Home() {
  return (
    <AppProvider>
      <AppShell />
    </AppProvider>
  );
}
