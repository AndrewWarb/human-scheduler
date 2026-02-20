export type UrgencyTier =
  | "critical"
  | "active_focus"
  | "important"
  | "normal"
  | "maintenance"
  | "someday";

export const XNU_URGENCY_LABELS: Partial<
  Record<string, { short: string; xnu: string; human: string }>
> = {
  critical:     { short: "FIXPRI", xnu: "TH_BUCKET_FIXPRI",    human: "Fixed-priority" },
  active_focus: { short: "FG",     xnu: "TH_BUCKET_SHARE_FG",  human: "Foreground" },
  important:    { short: "IN",     xnu: "TH_BUCKET_SHARE_IN",  human: "User-initiated" },
  normal:       { short: "DF",     xnu: "TH_BUCKET_SHARE_DF",  human: "Default" },
  maintenance:  { short: "UT",     xnu: "TH_BUCKET_SHARE_UT",  human: "Utility" },
  someday:      { short: "BG",     xnu: "TH_BUCKET_SHARE_BG",  human: "Background" },
};

export interface Task {
  id: number;
  title: string;
  life_area_id: number;
  life_area_name: string;
  urgency_tier: UrgencyTier;
  urgency_label: string;
  state: string;
  active_window_start_local: string | null;
  active_window_end_local: string | null;
  notes: string;
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

export interface SchedulerThread {
  task_id: number;
  title: string;
  life_area: string;
  urgency_tier: string;
  urgency_label: string;
  state: string;
  sched_bucket: string;
  base_pri: number;
  sched_pri: number;
  cpu_usage: number;
  cpu_usage_hours: number;
  total_cpu_us: number;
  context_switches: number;
  quantum_base_us: number;
  quantum_remaining_us: number;
  quantum_base_hours: number;
  quantum_remaining_hours: number;
  is_active: boolean;
  run_queue_rank: number | null;
}

export interface SchedulerLifeArea {
  id: number;
  name: string;
  task_count: number;
  interactivity_scores: Record<string, number>;
}

export interface SchedulerWarpBudget {
  bucket: string;
  remaining_us: number;
  total_us: number;
  remaining_hours: number;
  total_hours: number;
  is_active: boolean;
}

export interface SchedulerEdfDeadline {
  bucket: string;
  deadline_us: number;
  deadline_remaining_us: number;
  deadline_remaining_hours: number;
  deadline_at: string | null;
  is_active: boolean;
}

export interface SchedulerState {
  now_us: number;
  now_hours: number;
  tick: number;
  active_task_id: number | null;
  quantum_remaining_us: number;
  quantum_total_us: number;
  quantum_remaining_hours: number;
  quantum_total_hours: number;
  warp_budget_bucket: string | null;
  warp_budget_remaining_us: number;
  warp_budget_total_us: number;
  warp_budget_remaining_hours: number;
  warp_budget_total_hours: number;
  warp_budgets: SchedulerWarpBudget[];
  edf_deadline_bucket: string | null;
  edf_deadline_us: number;
  edf_deadline_remaining_us: number;
  edf_deadline_remaining_hours: number;
  edf_deadline_at: string | null;
  edf_deadlines: SchedulerEdfDeadline[];
  threads: SchedulerThread[];
  life_areas: SchedulerLifeArea[];
  recent_trace: string[];
  recent_switches: string[];
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
