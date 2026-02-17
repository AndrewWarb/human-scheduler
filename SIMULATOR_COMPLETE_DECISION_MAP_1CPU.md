# Complete Simulator Decision Map (Single CPU)

This is the full decision map for the same simulator when only one CPU exists (`--cpus 1`).

## 1) End-to-End Control Flow (CLI -> Engine -> Scheduler, 1 CPU)

```mermaid
flowchart TD
    A["main.py parses args (cpus=1)"] --> B["run_scenario(...)"]
    B --> C["Build workload profiles for scenario"]
    C --> D["Create/reuse ThreadGroup + Thread objects"]
    D --> E["engine.add_thread(thread, behavior, start_time)"]
    E --> F{"thread.is_realtime?"}
    F -->|yes| G["Schedule RT_PERIOD_START event"]
    F -->|no| H["Schedule THREAD_WAKEUP event"]

    G --> I["engine.run(duration_us)"]
    H --> I

    I --> J["Queue SIMULATION_END"]
    J --> K["Queue periodic SCHED_TICK events"]
    K --> L["Event loop: pop next event by time/priority"]
    L --> M{"event type"}

    M --> N["THREAD_WAKEUP handler"]
    M --> O["THREAD_BLOCK handler"]
    M --> P["QUANTUM_EXPIRE handler"]
    M --> Q["SCHED_TICK handler"]
    M --> R["RT_PERIOD_START handler"]

    N --> S["Scheduler thread_wakeup / thread_setrun"]
    O --> T["Scheduler thread_block + CPU0 dispatch/idle decision"]
    P --> U["Scheduler thread_quantum_expire + switch decision on CPU0"]
    Q --> V["Scheduler sched_tick maintenance"]
    R --> W["Set RT deadline + wake if waiting + schedule RT block/next period"]

    S --> X["Possible preemption handling on CPU0"]
    T --> X
    U --> X
    W --> X
    X --> L

    L --> Y{"SIMULATION_END reached?"}
    Y -->|no| L
    Y -->|yes| Z["Finalize CPU accounting + print stats/trace"]
```

**Element Notes**
- `main.py parses args (cpus=1)`: Reads scenario/options with a single logical CPU.
- `run_scenario(...)`: Instantiates engine/scheduler and workload objects.
- `engine.add_thread(...)`: Registers thread and initial event (wake or RT period start).
- `THREAD_WAKEUP` / `THREAD_BLOCK` / `QUANTUM_EXPIRE` / `SCHED_TICK` / `RT_PERIOD_START`: Core event types.
- `Possible preemption handling on CPU0`: Scheduler requested an immediate reschedule on the only CPU.
- `Finalize CPU accounting + print stats/trace`: Closes runtime accounting, then reports output.

## 2) Event Engine Decision Logic (1 CPU)

```mermaid
flowchart TD
    A["Pop event from heap"] --> B{"timestamp > duration?"}
    B -->|yes| END1["Stop loop"]
    B -->|no| C{"event == SIMULATION_END?"}
    C -->|yes| END2["Set clock and stop loop"]
    C -->|no| D["clock = event.timestamp"]

    D --> E{"handler"}

    E -->|THREAD_WAKEUP| F{"thread exists and not TERMINATED?"}
    F -->|no| A
    F -->|yes| F1["stats.wakeup_count++"] --> F2["preempt_proc = scheduler.thread_wakeup(...)"]
    F2 --> F3{"preempt_proc returned?"}
    F3 -->|yes| PRE["handle_preemption(CPU0)"]
    F3 -->|no| A

    E -->|THREAD_BLOCK| G{"thread exists and RUNNING?"}
    G -->|no| A
    G -->|yes| G1["stats.block_count++"] --> G2["proc = CPU running this thread (CPU0)"]
    G2 --> G3{"proc found?"}
    G3 -->|no| A
    G3 -->|yes| G4["new = scheduler.thread_block(...)"]
    G4 --> G5{"new selected?"}
    G5 -->|yes| G6["record dispatch/context switch; schedule quantum expire"]
    G5 -->|no| G7["try_dispatch_idle(CPU0)"]
    G6 --> G8["schedule next wakeup from behavior (non-RT)"] --> A
    G7 --> G8

    E -->|QUANTUM_EXPIRE| H{"CPU0 has active_thread and tid matches event?"}
    H -->|no| A
    H -->|yes| H1["stats.quantum_expire_count++"] --> H2["new = scheduler.thread_quantum_expire(...)"]
    H2 --> H3{"switched to different thread?"}
    H3 -->|yes| H4["record dispatch/context switch; schedule new quantum; schedule old block"]
    H3 -->|no| H5["if active thread remains, schedule its next quantum"]
    H4 --> A
    H5 --> A

    E -->|SCHED_TICK| I["stats.tick_count++; scheduler.sched_tick(...)"] --> A

    E -->|RT_PERIOD_START| J{"thread exists and not TERMINATED and behavior exists?"}
    J -->|no| A
    J -->|yes| J1["thread.rt_deadline = now + rt_constraint"]
    J1 --> J2{"thread is WAITING?"}
    J2 -->|yes| J3["thread_setrun(PREEMPT|TAILQ)"]
    J2 -->|no| J4["skip wake enqueue"]
    J3 --> J5{"preempt proc returned?"}
    J5 -->|yes| PRE
    J5 -->|no| J4
    J4 --> J6["schedule THREAD_BLOCK at now + rt_computation"]
    J6 --> J7{"rt_period > 0?"}
    J7 -->|yes| J8["schedule next RT_PERIOD_START"]
    J7 -->|no| A
    J8 --> A
```

**Element Notes**
- `Pop event from heap`: Takes the next timestamp/priority-ordered event.
- `preempt_proc = scheduler.thread_wakeup(...)`: Wakeup enqueues thread and may request preemption.
- `handle_preemption(CPU0)`: Performs select-then-dispatch on the only CPU.
- `new = scheduler.thread_block(...)`: Marks running thread waiting and tries replacement.
- `new = scheduler.thread_quantum_expire(...)`: Handles timeslice expiry and next-thread choice.
- `RT_PERIOD_START`: Periodic RT activation; sets deadline and may enqueue RT thread.
- `schedule ...`: Adds future events back into the queue.

## 3) `thread_setrun` + Preemption Check (1 CPU)

```mermaid
flowchart TD
    A["thread_setrun(thread, ts, options)"] --> B["state=RUNNABLE; last_made_runnable_time=ts"]
    B --> C{"thread.is_timeshare?"}
    C -->|yes| C1["_timeshare_setrun_update(thread)"]
    C -->|no| D
    C1 --> D{"thread.is_realtime?"}
    D -->|yes| E["_rt_thread_setrun"]
    D -->|no| F{"thread.bound_processor set?"}
    F -->|yes| G["_bound_thread_setrun (target is CPU0)"]
    F -->|no| H["_clutch_thread_setrun"]

    E --> I["RTQueue enqueue; set rt_deadline if none"]
    G --> J["Insert into bound runq for CPU0"]
    H --> K["Insert into clutch bucket queues and update counts"]

    I --> L["_check_preemption(new_thread, options)"]
    J --> L
    K --> L

    L --> M{"CPU0 idle?"}
    M -->|yes| RETIDLE["return CPU0 (dispatch immediately)"]
    M -->|no| N{"new thread is RT?"}

    N -->|yes| N1{"running thread non-RT OR lower-RT-pri OR later deadline?"}
    N1 -->|yes| RETPRE["return CPU0 to preempt current thread"]
    N1 -->|no| NONE["return None"]

    N -->|no| P{"preempt allowed and new.sched_pri > running.sched_pri?"}
    P -->|yes| RETPRE
    P -->|no| P2{"explicit preempt and equal-pri non-RT case?"}
    P2 -->|yes| RETPRE
    P2 -->|no| NONE
```

**Element Notes**
- `thread_setrun(...)`: Canonical path for marking a thread RUNNABLE and enqueueing it.
- `_timeshare_setrun_update`: Ages usage and recomputes dynamic priority.
- `_rt_thread_setrun`: Inserts runnable RT thread into RT queue.
- `_bound_thread_setrun`: Enqueues thread into CPU0-bound runqueue.
- `_clutch_thread_setrun`: Enqueues thread into unbound Clutch hierarchy.
- `_check_preemption(...)`: Decides whether CPU0 should switch immediately.
- `return CPU0` vs `return None`: Trigger immediate reschedule now or keep current execution.

## 4) `thread_select` Decision Tree (1 CPU core "who runs next")

```mermaid
flowchart TD
    A["thread_select(CPU0, timestamp, prev_thread?)"] --> B["rt_thread = rt_runq.peek()"]
    B --> C{"prev_thread is RT?"}
    C -->|yes| D{"_rt_prev_thread_can_continue?"}
    D -->|yes| RETP["return prev_thread, chose_prev=True"]
    D -->|no| E{"rt_thread exists?"}
    E -->|yes| RETRT["return rt_runq.dequeue(), chose_prev=False"]
    E -->|no| RETPRT["return prev_thread fallback"]

    C -->|no| F{"rt_thread exists?"}
    F -->|yes| RETRT
    F -->|no| G["bound_pri = best bound thread sched_pri or NOPRI"]
    G --> H["clutch_pri = clutch_root.scr_priority (adjusted with prev)"]
    H --> I{"clutch_pri > bound_pri?"}

    I -->|yes| J{"clutch runnable count == 0?"}
    J -->|yes| J1{"prev exists?"}
    J1 -->|yes| RETPREV["return prev_thread"]
    J1 -->|no| RETNONE["return None"]
    J -->|no| K["clutch_root.hierarchy_thread_highest(...)"]
    K --> K1{"thread found?"}
    K1 -->|yes & chose_prev| RETP
    K1 -->|yes & not chose_prev| RETCL["remove from runq; return clutch thread"]
    K1 -->|no| RETNONE

    I -->|no| L{"bound runq empty or prev bound wins tie?"}
    L -->|yes| L1{"prev exists?"}
    L1 -->|yes| RETPREV
    L1 -->|no| RETNONE
    L -->|no| RETB["pop and return bound thread"]

    RETP --> END["selected thread result for CPU0"]
    RETRT --> END
    RETPRT --> END
    RETPREV --> END
    RETCL --> END
    RETB --> END
    RETNONE --> END
```

**Element Notes**
- `prev_thread`: Current CPU0 thread, still eligible to keep running.
- `rt_runq.peek()/dequeue()`: RT candidates are considered before non-RT.
- `bound_pri`: Best priority among CPU0-bound runnable threads.
- `clutch_pri`: Best priority from unbound Clutch hierarchy.
- `chose_prev=True`: Keep current thread running intentionally.
- `remove from runq`: Dequeue selected runnable thread before dispatch.
- `return None`: No runnable candidate; CPU0 idles.

## 5) Clutch Hierarchy Decision Flow (non-RT unbound path, 1 CPU)

```mermaid
flowchart TD
    A["hierarchy_thread_highest(ts, prev_thread, first_timeslice)"] --> B["derive prev_bucket from prev_thread"]
    B --> C["highest_root_bucket(ts, prev_bucket, prev_thread)"]
    C --> D{"root bucket selected?"}
    D -->|no| RETNONE["return None"]
    D -->|yes & chose_prev| RETPREV["return prev_thread"]
    D -->|yes| E{"root bucket differs from prev_bucket?"}
    E -->|yes| E1["drop prev_thread for deeper levels"]
    E -->|no| F
    E1 --> F["root_bucket_highest_clutch_bucket(root_bucket, prev_thread, first_timeslice)"]
    F --> G{"clutch bucket selected?"}
    G -->|no| RETNONE
    G -->|yes & chose_prev| RETPREV
    G -->|yes| H["thread = scb_thread_runq.peek_max()"]
    H --> I{"prev in same clutch bucket and wins tie?"}
    I -->|yes| RETPREV
    I -->|no| RETTH["return selected thread"]

    C --> C1["highest_root_bucket internals"]
    C1 --> C2{"Above-UI FIXPRI check wins?"}
    C2 -->|yes| C3["return FIXPRI root bucket"]
    C2 -->|no| C4["evaluate_root_buckets (EDF loop)"]
    C4 --> C5{"higher non-EDF bucket can warp?"}
    C5 -->|yes| C6["select warp bucket if window active"]
    C5 -->|no| C7["EDF winner path"]
    C7 --> C8{"starvation avoidance should activate?"}
    C8 -->|yes| C9["mark starvation mode"]
    C8 -->|no| C10["deadline_update + reset warp budget"]
```

**Element Notes**
- `highest_root_bucket(...)`: Chooses winning QoS root lane.
- `prev_bucket`: Current thread’s lane for tie/keep-running rules.
- `root_bucket_highest_clutch_bucket(...)`: Chooses winning thread-group bucket in that lane.
- `scb_thread_runq.peek_max()`: Reads top runnable thread in selected bucket.
- `warp`: Temporary preference that can elevate service for a higher lane.
- `EDF winner path`: Earliest-deadline choice for root-level fairness.
- `starvation avoidance`: Ensures delayed lower lanes eventually receive CPU0 service.

## 6) Dispatch / Quantum / Block Decisions (1 CPU)

```mermaid
flowchart TD
    A["thread_dispatch(old, new, ts) on CPU0"] --> B["Account old CPU segment if switching"]
    B --> C["new.state=RUNNING; computation_epoch=ts"]
    C --> D["if quantum_remaining<=0 then reset_quantum()"]
    D --> E["CPU0.active_thread=new; current_pri=new.sched_pri"]

    E --> F["engine schedules QUANTUM_EXPIRE at now + quantum_remaining"]
    F --> G{"non-RT?"}
    G -->|yes| H["engine schedules THREAD_BLOCK at now + sampled CPU burst"]
    G -->|no| I["RT block scheduled by RT_PERIOD_START handler"]

    Q["QUANTUM_EXPIRE event"] --> Q1["thread_quantum_expire(...)"]
    Q1 --> Q2["account CPU + timeshare update"]
    Q2 --> Q3["old.first_timeslice=False; old.quantum_remaining=0; state=RUNNABLE"]
    Q3 --> Q4["thread_select(prev_thread=old)"]
    Q4 --> Q5{"selected old again?"}
    Q5 -->|yes| A
    Q5 -->|no| Q6{"selected different thread?"}
    Q6 -->|yes| Q7["re-enqueue old at TAIL; dispatch new"]
    Q6 -->|no| A

    BL["THREAD_BLOCK event"] --> BL1["thread_block(...)"]
    BL1 --> BL2["account CPU; set WAITING; quantum_remaining=0"]
    BL2 --> BL3["decrement run_count for non-RT unbound"]
    BL3 --> BL4["thread_select(no prev)"]
    BL4 --> BL5{"new selected?"}
    BL5 -->|yes| A
    BL5 -->|no| BL6["CPU0 becomes IDLE"]
```

**Element Notes**
- `thread_dispatch(old, new, ts) on CPU0`: Context-switch/install path on the only CPU.
- `QUANTUM_EXPIRE`: Timeslice timer for current thread fired.
- `thread_quantum_expire(...)`: Select-then-dispatch after quantum end.
- `THREAD_BLOCK`: Voluntary block event (sleep/I/O/wait).
- `thread_block(...)`: Marks thread waiting and chooses replacement.
- `re-enqueue old at TAIL`: Old thread remains runnable but yields queue position.
- `CPU0 becomes IDLE`: No runnable replacement exists.

## 7) Timeshare Dynamic Priority Update Loop (1 CPU)

```mermaid
flowchart TD
    A["Timeshare thread runs for delta_us"] --> B["update_thread_cpu_usage"]
    B --> B1["cpu_usage += delta_us"]
    B1 --> B2{"pri_shift < 127?"}
    B2 -->|yes| B3["sched_usage += delta_us"]
    B2 -->|no| B4["skip sched_usage charge"]

    C["sched_tick"] --> C1["for each runnable clutch bucket group: pri_shift_update(load, cpu_count=1)"]
    C1 --> C2["for each timeshare thread: age_thread_cpu_usage"]
    C2 --> C3["thread.pri_shift = cbg.scbg_pri_shift"]
    C3 --> C4["new_pri = compute_sched_pri(base_pri, sched_usage, pri_shift)"]
    C4 --> C5{"priority changed?"}
    C5 -->|yes| C6["refresh runqueue ordering"]
    C5 -->|no| C7["keep order"]

    W["thread_setrun for timeshare"] --> W1["_timeshare_setrun_update"]
    W1 --> W2["age by elapsed ticks via sched_stamp"]
    W2 --> W3["set pri_shift from bucket group (or 127 if bound)"]
    W3 --> W4["recompute sched_pri"]
```

**Element Notes**
- `cpu_usage`: Total charged runtime for this thread.
- `sched_usage`: Decay-sensitive usage used for timeshare penalty.
- `pri_shift`: Load-derived penalty aggressiveness.
- `compute_sched_pri(...)`: Recomputes dynamic priority from usage/base/shift.
- `sched_tick`: Periodic maintenance pass.
- `refresh runqueue ordering`: Reorders queues after priority changes.
- `_timeshare_setrun_update`: Wakeup-time update before enqueue.

## 8) RT Decision Flow (1 CPU)

```mermaid
flowchart TD
    A["RT thread becomes runnable"] --> B{"rt_deadline set?"}
    B -->|no| B1["rt_deadline = now + rt_constraint"]
    B -->|yes| C
    B1 --> C["enqueue RTQueue by (sched_pri, rt_deadline)"]

    C --> D["_check_preemption for RT (against CPU0 current thread)"]
    D --> E{"CPU0 running non-RT?"}
    E -->|yes| PRE["preempt CPU0"]
    E -->|no| F{"CPU0 running RT with lower pri?"}
    F -->|yes| PRE
    F -->|no| G{"equal pri but earlier deadline?"}
    G -->|yes| PRE
    G -->|no| NONE["no immediate preempt"]

    S["thread_select with prev RT on CPU0"] --> S1{"first_timeslice keep-running allowed?"}
    S1 -->|yes| KEEP["keep prev RT running"]
    S1 -->|no| PICK["pick from RTQueue"]

    PICK --> P2{"strict priority?"}
    P2 -->|yes| P3["highest RT priority band wins"]
    P2 -->|no| P4{"EDF override safe vs higher-pri constraint?"}
    P4 -->|yes| P5["earliest-deadline RT may win"]
    P4 -->|no| P3
```

**Element Notes**
- `rt_deadline`: Absolute deadline for active RT period.
- `enqueue RTQueue by (sched_pri, rt_deadline)`: RT ordering key.
- `_check_preemption for RT (against CPU0 current thread)`: Decide immediate CPU0 interruption.
- `first_timeslice keep-running`: May allow current RT to continue safely.
- `strict priority`: If on, RT priority dominates over deadline crossover.
- `EDF override safe`: In non-strict mode, deadline-based choice only when safe.
- `preempt CPU0`: Immediate reschedule request for better RT candidate.

---

## Reading Order

Read in this order for the full single-CPU walkthrough:

1. Diagram 1 (global control flow)
2. Diagram 2 (event engine)
3. Diagram 3 (`thread_setrun` + preemption)
4. Diagram 4 (`thread_select`)
5. Diagram 5 (Clutch hierarchy internals)
6. Diagram 6 (dispatch/quantum/block)
7. Diagram 7 (timeshare priority dynamics)
8. Diagram 8 (RT specifics)
