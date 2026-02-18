"use client";

export type TabId =
  | "dashboard"
  | "tasks"
  | "life-areas"
  | "activity"
  | "settings";

const TABS: { id: TabId; label: string; xnuLabel: string }[] = [
  { id: "dashboard", label: "Dashboard", xnuLabel: "dispatch + timeslice" },
  { id: "life-areas", label: "Life Areas", xnuLabel: "thread groups" },
  { id: "tasks", label: "Tasks", xnuLabel: "threads" },
  { id: "activity", label: "Activity", xnuLabel: "scheduler trace" },
  { id: "settings", label: "Settings", xnuLabel: "kernel diagnostics" },
];

interface TabNavProps {
  active: TabId;
  onChange: (tab: TabId) => void;
}

export function TabNav({ active, onChange }: TabNavProps) {
  return (
    <nav className="tab-nav" aria-label="Main">
      {TABS.map((tab) => {
        const isActive = tab.id === active;

        return (
          <button
            key={tab.id}
            className={`tab-pill ${isActive ? "tab-pill-active" : ""}`}
            onClick={() => onChange(tab.id)}
            aria-label={`Open ${tab.label}`}
          >
            <span className="tab-pill-main">{tab.label}</span>
            <sub className="tab-pill-sub">{tab.xnuLabel}</sub>
          </button>
        );
      })}
    </nav>
  );
}
