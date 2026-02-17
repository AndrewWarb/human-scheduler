# Simulator Object Diagrams

## 1) Static Object Hierarchy (Ownership + References)

```mermaid
graph TD
    MAIN["main.py::run_scenario(...)"] --> ENG["SimulationEngine"]
    ENG --> EQ["event_queue: Event heap"]
    ENG --> SCHED["Scheduler"]
    ENG --> PSET["ProcessorSet"]
    ENG --> STATS["StatsCollector"]
    ENG --> TB["thread_behaviors: tid -> BehaviorProfile"]

    PSET --> CPUS["processors: Processor[]"]
    PSET --> RTQ["RTQueue"]
    PSET --> ROOT["ClutchRoot"]

    SCHED --> ALLT["all_threads: Thread[]"]
    SCHED --> BRQ["_bound_runqs: one runqueue per CPU"]
    SCHED --> RTQ
    SCHED --> ROOT

    THREAD["Thread"] --> TG["ThreadGroup"]
    TG --> SC["SchedClutch"]

    SC --> CBGS["sc_clutch_groups[6 QoS buckets]"]
    CBGS --> CBS["scbg_clutch_buckets[num_clusters]"]

    CBS --> TRQ["scb_thread_runq (runnable ordering)"]
    CBS --> CPRQ["scb_clutchpri_prioq (base/promoted pri)"]
    CBS --> TSL["scb_timeshare_threads (sched_tick aging)"]

    ROOT --> RBU["unbound ClutchRootBucket[6]"]
    ROOT --> RBB["bound ClutchRootBucket[6]"]
    RBU --> CBRQ["scrb_clutch_buckets (queue of SchedClutchBucket refs)"]
    RBB --> CBRQ
```

## 2) Where Threads Live By State

```mermaid
flowchart TD
    REG["Scheduler.all_threads (global registry)"]

    WAIT["WAITING"] -->|wake/period event| RUNNABLE["RUNNABLE"]
    RUNNABLE -->|thread_select| RUNNING["RUNNING on Processor.active_thread"]
    RUNNING -->|voluntary block| WAIT
    RUNNING -->|quantum expire or preempt| RUNNABLE

    RUNNABLE -->|if realtime| QRT["RTQueue"]
    RUNNABLE -->|if bound non-RT| QB["Scheduler._bound_runqs[cpu]"]
    RUNNABLE -->|if unbound non-RT| QC["SchedClutchBucket queues\nscb_thread_runq / scb_clutchpri_prioq / scb_timeshare_threads"]

    REG --- WAIT
    REG --- RUNNABLE
    REG --- RUNNING
```

## 3) Selection Flow (`thread_select`)

```mermaid
flowchart TD
    START["thread_select(processor, prev_thread)"] --> RTKEEP{"prev is RT and can keep running?"}
    RTKEEP -->|yes| KEEP["select prev_thread"]
    RTKEEP -->|no| RTQ{"RT queue non-empty?"}
    RTQ -->|yes| PICKRT["dequeue RT thread"]
    RTQ -->|no| CMP["compare clutch_root.scr_priority vs bound_runq priority"]

    CMP -->|clutch side wins| CLUTCH["clutch_root.hierarchy_thread_highest(...)"]
    CLUTCH --> ROOTPHASE["Root-bucket phase:\nEDF + warp + starvation avoidance"]
    ROOTPHASE --> BUCKETPHASE["Pick clutch bucket in selected root bucket"]
    BUCKETPHASE --> THREADPHASE["Pick thread from scb_thread_runq"]
    THREADPHASE --> OUTC["selected clutch thread"]

    CMP -->|bound side wins| BOUNDSEL["pick from bound runq (or keep prev bound)"]
    BOUNDSEL --> OUTB["selected bound thread"]

    OUTC --> DONE["return (thread, chose_prev)"]
    OUTB --> DONE
    KEEP --> DONE
    PICKRT --> DONE
```

## 4) Enqueue Paths (`thread_setrun`)

```mermaid
flowchart LR
    IN["thread_setrun(thread, ts, options)"] --> MODE{"thread type?"}
    MODE -->|RT| RTENQ["enqueue into RTQueue"]
    MODE -->|bound non-RT| BENQ["enqueue into bound runq for target CPU"]
    MODE -->|unbound non-RT| CENQ["enqueue into thread_group.sched_clutch bucket queues"]

    RTENQ --> PRE["check preemption target CPU"]
    BENQ --> PRE
    CENQ --> PRE
    PRE --> RES["return Processor or None"]
```

## 5) RT (Real-Time) Lifecycle

```mermaid
flowchart TD
    PERIOD["RT_PERIOD_START event"] --> DEADLINE["set thread.rt_deadline = now + rt_constraint"]
    DEADLINE --> WAKE{"thread is WAITING?"}
    WAKE -->|yes| SETRUN["thread_setrun(thread, PREEMPT|TAILQ)"]
    WAKE -->|no| KEEPSTATE["already runnable/running; keep state"]

    SETRUN --> INRTQ["enqueue in RTQueue"]
    INRTQ --> PRECHK["check preemption target CPU"]
    PRECHK -->|CPU returned| PREEMPT["engine handles preemption/dispatch"]
    PRECHK -->|None| NOWAIT["no immediate preemption"]

    KEEPSTATE --> BLOCKSCHED["schedule THREAD_BLOCK at now + rt_computation"]
    PREEMPT --> BLOCKSCHED
    NOWAIT --> BLOCKSCHED
    BLOCKSCHED --> NEXTPERIOD["schedule next RT_PERIOD_START at now + rt_period"]
```

## 6) RTQueue Ordering and Pick Rules

```mermaid
flowchart TD
    ENQ["RT thread enqueued"] --> BAND["placed in priority band by sched_pri"]
    BAND --> DEAD["within band: ordered by earliest rt_deadline"]
    DEAD --> DEQ["when selecting: choose highest RT priority band"]
    DEQ --> EDFSAFE{"lower-pri earlier deadline allowed?\n(safety check passes)"}
    EDFSAFE -->|yes| EDFWIN["pick earlier-deadline lower-pri RT thread"]
    EDFSAFE -->|no| HWIN["pick highest-pri RT thread"]
```

## RT Reading Guide

- `RT` threads do not use normal Clutch timeshare queues while runnable; they use `RTQueue`.
- In `thread_select`, any eligible RT candidate is considered before non-RT queues.
- RT can preempt non-RT immediately when preemption checks choose a processor.
- RT periodic behavior is event-driven: `RT_PERIOD_START` activates, `THREAD_BLOCK` ends computation slice.
