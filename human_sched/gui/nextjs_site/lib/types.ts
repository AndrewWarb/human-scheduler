export type UrgencyTier =
  | "critical"
  | "active_focus"
  | "important"
  | "normal"
  | "maintenance"
  | "someday";

export interface Task {
  id: number;
  title: string;
  life_area_id: number;
  life_area_name: string;
  urgency_tier: UrgencyTier;
  urgency_label: string;
  state: string;
  notes: string;
  due_at: string | null;
  created_at: string;
}

export interface LifeArea {
  id: number;
  name: string;
  task_count: number;
  interactivity_scores: Record<string, number>;
}

export interface Dispatch {
  task: Task;
  life_area: LifeArea;
  urgency_tier: UrgencyTier;
  focus_block_hours: number;
  focus_block_end_at: string;
  reason: string;
  decision: "start" | "switch" | "continuation";
  dispatched_at: string;
}

export interface SchedulerEvent {
  event_id: number;
  event_type: string;
  message: string;
  timestamp: string;
  related_task_id: number | null;
  source: string;
}

export interface UrgencyTierOption {
  value: string;
  label: string;
}

export interface SeedScenario {
  name: string;
  description: string;
}

export interface AppSettings {
  urgency_tiers: UrgencyTierOption[];
  seed_scenarios: SeedScenario[];
  thread_states: string[];
}

export interface AdapterMeta {
  adapter: {
    name: string;
    version: string;
    capabilities: string[];
  };
  contract_version: string;
  base_url: string;
}

export interface Diagnostics {
  adapter_name: string;
  adapter_version: string;
  contract_version: string;
  scheduler_connection_status: string;
  scheduler_base_url: string;
  event_stream_status: string;
  event_stream_active_clients: number;
  last_event_timestamp: string | null;
  event_lag_ms: number | null;
  last_successful_command_time: string | null;
  last_command_error: string | null;
  dropped_event_count: number;
  event_stream_dropped_clients: number;
  event_stream_retried_writes: number;
  last_event_stream_error?: string | null;
}
