"use client";

export type TabId =
  | "dashboard"
  | "tasks"
  | "life-areas"
  | "activity"
  | "settings";

const TABS: { id: TabId; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "life-areas", label: "Life Areas" },
  { id: "tasks", label: "Tasks" },
  { id: "activity", label: "Activity" },
  { id: "settings", label: "Settings" },
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
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}
