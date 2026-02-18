"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
} from "react";
import type {
  AdapterMeta,
  AppSettings,
  Diagnostics,
  Dispatch,
  LifeArea,
  SchedulerEvent,
  Task,
} from "./types";
import {
  fetchMeta,
  fetchSettings,
  fetchDiagnostics,
  fetchLifeAreas,
  fetchTasks,
  fetchDispatch,
  fetchEvents,
  whatNext as apiWhatNext,
  resetSimulation as apiResetSimulation,
  taskAction as apiTaskAction,
  createTask as apiCreateTask,
  createLifeArea as apiCreateLifeArea,
  deleteLifeArea as apiDeleteLifeArea,
  renameLifeArea as apiRenameLifeArea,
} from "./api";
import { useEventStream, type ConnectionStatus } from "./use-event-stream";

interface AppState {
  meta: AdapterMeta | null;
  settings: AppSettings | null;
  diagnostics: Diagnostics | null;
  lifeAreas: LifeArea[];
  tasks: Task[];
  events: SchedulerEvent[];
  dispatch: Dispatch | null;
  simulationRunning: boolean;
  selectedTaskId: number | null;
  toast: string;
}

type Action =
  | { type: "SET_META"; payload: AdapterMeta }
  | { type: "SET_SETTINGS"; payload: AppSettings }
  | { type: "SET_DIAGNOSTICS"; payload: Diagnostics }
  | { type: "SET_LIFE_AREAS"; payload: LifeArea[] }
  | { type: "SET_TASKS"; payload: Task[] }
  | { type: "SET_EVENTS"; payload: SchedulerEvent[] }
  | { type: "PUSH_EVENT"; payload: SchedulerEvent }
  | { type: "SET_DISPATCH"; payload: Dispatch | null }
  | { type: "SET_SIMULATION_RUNNING"; payload: boolean }
  | { type: "SET_SELECTED_TASK"; payload: number | null }
  | { type: "SHOW_TOAST"; payload: string };

const INITIAL_STATE: AppState = {
  meta: null,
  settings: null,
  diagnostics: null,
  lifeAreas: [],
  tasks: [],
  events: [],
  dispatch: null,
  simulationRunning: false,
  selectedTaskId: null,
  toast: "",
};

const MAX_EVENTS = 200;

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "SET_META":
      return { ...state, meta: action.payload };
    case "SET_SETTINGS":
      return { ...state, settings: action.payload };
    case "SET_DIAGNOSTICS":
      return { ...state, diagnostics: action.payload };
    case "SET_LIFE_AREAS":
      return { ...state, lifeAreas: action.payload };
    case "SET_TASKS":
      return { ...state, tasks: action.payload };
    case "SET_EVENTS":
      return { ...state, events: action.payload };
    case "PUSH_EVENT": {
      const events = [...state.events, action.payload];
      return { ...state, events: events.slice(-MAX_EVENTS) };
    }
    case "SET_DISPATCH":
      return { ...state, dispatch: action.payload };
    case "SET_SIMULATION_RUNNING":
      return { ...state, simulationRunning: action.payload };
    case "SET_SELECTED_TASK":
      return { ...state, selectedTaskId: action.payload };
    case "SHOW_TOAST":
      return { ...state, toast: action.payload };
  }
}

interface AppContextValue {
  state: AppState;
  sseStatus: ConnectionStatus;
  refreshAll: () => Promise<void>;
  refreshTasks: (filters?: {
    life_area_id?: string;
    urgency?: string;
    state?: string;
  }) => Promise<void>;
  startSimulation: () => Promise<void>;
  stopSimulation: () => void;
  resetSimulation: () => Promise<void>;
  doTaskAction: (
    taskId: number,
    action: "pause" | "resume" | "complete",
  ) => Promise<void>;
  doCreateTask: (body: {
    title: string;
    life_area_id: number;
    urgency_tier: string;
    description: string;
  }) => Promise<void>;
  doCreateLifeArea: (body: {
    name: string;
  }) => Promise<void>;
  doDeleteLifeArea: (lifeAreaId: number) => Promise<void>;
  doRenameLifeArea: (lifeAreaId: number, name: string) => Promise<void>;
  selectTask: (id: number | null) => void;
  showToast: (msg: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autoDispatchInFlightRef = useRef(false);
  const autoDispatchCooldownUntilRef = useRef(0);

  const showToast = useCallback((msg: string) => {
    dispatch({ type: "SHOW_TOAST", payload: msg });
    setTimeout(() => dispatch({ type: "SHOW_TOAST", payload: "" }), 2200);
  }, []);

  const refreshAll = useCallback(async () => {
    const [meta, settings, areas, tasksRes, dispatchRes, eventsRes, diag] =
      await Promise.all([
        fetchMeta().catch(() => null),
        fetchSettings().catch(() => null),
        fetchLifeAreas().catch(() => null),
        fetchTasks().catch(() => null),
        fetchDispatch().catch(() => null),
        fetchEvents().catch(() => null),
        fetchDiagnostics().catch(() => null),
      ]);

    if (meta) dispatch({ type: "SET_META", payload: meta });
    if (settings) dispatch({ type: "SET_SETTINGS", payload: settings });
    if (areas) dispatch({ type: "SET_LIFE_AREAS", payload: areas.items ?? [] });
    if (tasksRes)
      dispatch({ type: "SET_TASKS", payload: tasksRes.items ?? [] });
    if (dispatchRes)
      dispatch({ type: "SET_DISPATCH", payload: dispatchRes.dispatch });
    if (eventsRes)
      dispatch({ type: "SET_EVENTS", payload: eventsRes.items ?? [] });
    if (diag) dispatch({ type: "SET_DIAGNOSTICS", payload: diag });
  }, []);

  const refreshTasks = useCallback(
    async (filters?: {
      life_area_id?: string;
      urgency?: string;
      state?: string;
    }) => {
      const res = await fetchTasks(filters).catch(() => null);
      if (res) dispatch({ type: "SET_TASKS", payload: res.items ?? [] });
    },
    [],
  );

  const doWhatNext = useCallback(async () => {
    try {
      const res = await apiWhatNext();
      dispatch({ type: "SET_DISPATCH", payload: res.dispatch });

      if (res.dispatch) {
        showToast(
          `${res.dispatch.decision.toUpperCase()}: ${res.dispatch.task.title}`,
        );
      } else {
        showToast("No runnable tasks. Create or resume one.");
      }

      const [tasksRes, diag] = await Promise.all([
        fetchTasks().catch(() => null),
        fetchDiagnostics().catch(() => null),
      ]);
      if (tasksRes)
        dispatch({ type: "SET_TASKS", payload: tasksRes.items ?? [] });
      if (diag) dispatch({ type: "SET_DIAGNOSTICS", payload: diag });
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e));
    }
  }, [showToast]);

  const startSimulation = useCallback(async () => {
    if (state.simulationRunning) {
      showToast("Simulation is already running.");
      return;
    }
    dispatch({ type: "SET_SIMULATION_RUNNING", payload: true });
    if (state.dispatch !== null) {
      showToast("Simulation resumed.");
      return;
    }
    await doWhatNext();
  }, [state.simulationRunning, state.dispatch, doWhatNext, showToast]);

  const stopSimulation = useCallback(() => {
    if (!state.simulationRunning) {
      showToast("Simulation is already stopped.");
      return;
    }
    dispatch({ type: "SET_SIMULATION_RUNNING", payload: false });
    showToast("Simulation stopped. Automatic recommendations paused.");
  }, [state.simulationRunning, showToast]);

  const resetSimulation = useCallback(async () => {
    try {
      const result = await apiResetSimulation();
      dispatch({ type: "SET_SIMULATION_RUNNING", payload: false });
      dispatch({ type: "SET_DISPATCH", payload: null });
      dispatch({ type: "SET_SELECTED_TASK", payload: null });
      await refreshAll();

      const count = result.reset_task_count ?? 0;
      const taskWord = count === 1 ? "task" : "tasks";
      showToast(`Simulation reset to 0 (${count} ${taskWord} re-queued).`);
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e));
    }
  }, [refreshAll, showToast]);

  const doTaskAction = useCallback(
    async (taskId: number, action: "pause" | "resume" | "complete") => {
      try {
        await apiTaskAction(taskId, action);
        showToast(`Task ${action}d.`);

        const [tasksRes, dispatchRes, diag] = await Promise.all([
          fetchTasks().catch(() => null),
          fetchDispatch().catch(() => null),
          fetchDiagnostics().catch(() => null),
        ]);
        if (tasksRes)
          dispatch({ type: "SET_TASKS", payload: tasksRes.items ?? [] });
        if (dispatchRes)
          dispatch({ type: "SET_DISPATCH", payload: dispatchRes.dispatch });
        if (diag) dispatch({ type: "SET_DIAGNOSTICS", payload: diag });
      } catch (e) {
        showToast(e instanceof Error ? e.message : String(e));
      }
    },
    [showToast],
  );

  const doCreateTask = useCallback(
    async (body: {
      title: string;
      life_area_id: number;
      urgency_tier: string;
      description: string;
    }) => {
      await apiCreateTask(body);
      showToast("Task created.");
      await refreshAll();
    },
    [showToast, refreshAll],
  );

  const doCreateLifeArea = useCallback(
    async (body: { name: string }) => {
      await apiCreateLifeArea({ name: body.name });
      showToast("Life area created.");
      await refreshAll();
    },
    [showToast, refreshAll],
  );

  const doDeleteLifeArea = useCallback(
    async (lifeAreaId: number) => {
      try {
        const result = await apiDeleteLifeArea(lifeAreaId);
        const deletedCount = result.deleted_task_count ?? 0;
        const taskWord = deletedCount === 1 ? "task" : "tasks";
        showToast(`Life area deleted (${deletedCount} ${taskWord} removed).`);
        await refreshAll();
      } catch (e) {
        showToast(e instanceof Error ? e.message : String(e));
      }
    },
    [showToast, refreshAll],
  );

  const doRenameLifeArea = useCallback(
    async (lifeAreaId: number, name: string) => {
      try {
        await apiRenameLifeArea(lifeAreaId, name);
        showToast("Life area renamed.");
        await refreshAll();
      } catch (e) {
        showToast(e instanceof Error ? e.message : String(e));
      }
    },
    [showToast, refreshAll],
  );

  const selectTask = useCallback((id: number | null) => {
    dispatch({ type: "SET_SELECTED_TASK", payload: id });
  }, []);

  // Boot: fetch everything on mount
  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  // Auto-dispatch while simulation is running when work is runnable but CPU is idle.
  useEffect(() => {
    if (!state.simulationRunning || state.dispatch !== null) return;
    if (!state.tasks.some((task) => task.state === "runnable")) return;

    const now = Date.now();
    if (autoDispatchInFlightRef.current || now < autoDispatchCooldownUntilRef.current) {
      return;
    }

    autoDispatchInFlightRef.current = true;
    void doWhatNext().finally(() => {
      autoDispatchInFlightRef.current = false;
      autoDispatchCooldownUntilRef.current = Date.now() + 1000;
    });
  }, [state.simulationRunning, state.dispatch, state.tasks, doWhatNext]);

  // Auto-refresh diagnostics every 5s
  useEffect(() => {
    const id = setInterval(() => {
      fetchDiagnostics()
        .then((d) => dispatch({ type: "SET_DIAGNOSTICS", payload: d }))
        .catch(() => {});
    }, 5000);
    return () => clearInterval(id);
  }, []);

  // SSE event handler with debounced refresh
  const handleSseEvent = useCallback(
    (event: SchedulerEvent) => {
      dispatch({ type: "PUSH_EVENT", payload: event });

      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = setTimeout(async () => {
        const [tasksRes, dispatchRes, diag] = await Promise.all([
          fetchTasks().catch(() => null),
          fetchDispatch().catch(() => null),
          fetchDiagnostics().catch(() => null),
        ]);
        if (tasksRes)
          dispatch({ type: "SET_TASKS", payload: tasksRes.items ?? [] });
        if (dispatchRes)
          dispatch({ type: "SET_DISPATCH", payload: dispatchRes.dispatch });
        if (diag) dispatch({ type: "SET_DIAGNOSTICS", payload: diag });
        refreshTimerRef.current = null;
      }, 180);
    },
    [],
  );

  const lastEventId =
    state.events.length > 0
      ? state.events[state.events.length - 1].event_id
      : null;

  const sseStatus = useEventStream(lastEventId, handleSseEvent);

  const value: AppContextValue = {
    state,
    sseStatus,
    refreshAll,
    refreshTasks,
    startSimulation,
    stopSimulation,
    resetSimulation,
    doTaskAction,
    doCreateTask,
    doCreateLifeArea,
    doDeleteLifeArea,
    doRenameLifeArea,
    selectTask,
    showToast,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
