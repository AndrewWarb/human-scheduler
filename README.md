# Human Task Scheduler

A personal task scheduler that adapts the macOS/XNU Clutch scheduler to decide **what you should work on next**. Instead of a static to-do list, it applies real OS scheduling algorithms (timeshare decay, EDF deadlines, warp budgets, starvation avoidance) to balance urgency, fairness, and focus across competing life areas.

<img width="1177" height="925" alt="image" src="https://github.com/user-attachments/assets/40e8d57c-d3ff-4599-b658-59a5950ba1ba" />

## How It Works

The XNU Clutch scheduler solves the problem of fairly distributing CPU time across competing workloads. Human task management is the same problem at a different timescale: you have limited attention (the "CPU") and many tasks competing across work, health, household, hobbies, etc.

### Concept Mapping

| XNU Concept | Human Concept | Example |
|---|---|---|
| Thread | Task | "Mop kitchen floor", "Write API endpoint" |
| ThreadGroup / SchedClutch | Life Area | "Work", "Health", "Home" |
| Processor | Attention slot | Your single focus stream (1 CPU) |
| Thread quantum | Focus block | How long to work before re-evaluation |
| ClutchRootBucket (QoS) | Urgency tier | Groups tasks by urgency across all life areas |
| EDF deadlines / warp | Fairness & urgency boost | Neglected areas surface; urgent areas get bursts |

### Urgency Tiers

| Tier | XNU Equivalent | Meaning |
|---|---|---|
| Critical | Fixed-priority | Deadline-imminent ("Submit tax return today") |
| Active Focus | Foreground | Currently selected project's tasks |
| Important | User-Initiated | Time-sensitive ("Reply to boss's email") |
| Normal | Default | Standard priority ("Grocery shopping") |
| Maintenance | Utility | Low priority ("Organize bookshelf") |
| Someday | Background | Aspirational ("Learn watercolors") |

### What the Scheduler Gives You

- **Starvation avoidance** -- neglected life areas eventually surface even if you've been focused elsewhere
- **Warp budgets** -- urgent areas get temporary priority bursts before falling back to fair scheduling
- **Timeshare decay** -- tasks that consumed lots of attention naturally drop in priority
- **Interactivity scoring** -- life areas you actively engage with get responsiveness boosts

## Project Structure

```
xnu_sched/          # Faithful Python port of the XNU Clutch scheduler
  scheduler.py      #   Core: thread_select, thread_setrun, quantum_expire, sched_tick
  clutch.py         #   SchedClutch / ClutchBucket hierarchy
  clutch_root.py    #   ClutchRoot with EDF + warp + starvation avoidance
  thread.py         #   Thread state machine
  processor.py      #   Processor (CPU) model
  rt_queue.py       #   Real-time priority queue

human_sched/        # Human task management layer on top of xnu_sched
  domain/           #   Task, LifeArea, UrgencyTier (pure domain, no I/O)
  application/      #   HumanTaskScheduler runtime, use cases (create/pause/complete)
  ports/            #   Notification port (abstract)
  adapters/         #   Terminal notifier, time-scale config
  gui/              #   Web GUI host (HTTP API + SSE + Next.js frontend)
    nextjs_site/    #     Next.js frontend (dashboard, task management, settings)
    adapters/       #     GUI adapter implementations (nextjs, terminal)
    scenarios.py    #     Seed scenarios (workday_blend, exam_crunch, home_reset)

simulator/          # Discrete-event simulation engine for the XNU scheduler
tests/              # Unit tests
```

## Quick Start

**Requirements:** Python 3.12+, Node.js (for the web GUI)

```bash
# Install Python dependencies
uv sync

# Run the GUI
python gui.py
```

Open http://127.0.0.1:3000. The API/SSE backend runs on http://127.0.0.1:8765.

### Seed Scenarios

The GUI ships with pre-built scenarios to get started quickly:

- **Workday Blend** -- mixed work/health/home tasks at varying urgencies
- **Exam Crunch** -- student workload where one urgent lane dominates
- **Home Reset** -- personal-life heavy with maintenance and backlog tasks
- **Empty** -- blank slate

Set via `.env` (`GUI_SCENARIO=workday_blend`) or CLI (`python gui.py --scenario exam_crunch`).

### CLI Flags

```
--adapter terminal|nextjs    GUI adapter (default: nextjs)
--scenario <name>            Seed scenario
--host / --port              Backend host/port
--disable-timers             Disable runtime notification timers
--open-browser               Open GUI URL on startup
--frontend-dev               Next.js dev mode with hot reload (default)
--data-dir <path>            JSON persistence directory (default: .gui_data)
```

## Running the Simulator

The standalone XNU scheduler simulator runs discrete-event simulations independent of the human task layer:

```bash
python main.py
```

Configure via `.env`:

```env
SCENARIO=mixed
CPUS=1
DURATION_MS=1000
TRACE=false
```

## Time Scaling

The XNU scheduler operates in microseconds; humans operate in hours. A configurable multiplier bridges them:

```env
# 1 scheduler microsecond = 0.00025 real hours (default)
TIME_SCALE_HOURS_PER_US=0.00025
```

## Tests

```bash
python -m pytest tests/
```

## Data Persistence

GUI state persists to JSON files in `.gui_data/` by default:

- `.gui_data/life_areas.json`
- `.gui_data/tasks.json`

When persisted data exists, the seed scenario is skipped to avoid duplicates.
