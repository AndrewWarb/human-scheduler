# Running the Task Scheduler GUI

## Quick start

```bash
python gui.py
```

Open `http://127.0.0.1:3000` (live reload enabled by default).
API/SSE backend remains `http://127.0.0.1:8765`.

## Select adapter

Set in `.env`:

```env
GUI_ADAPTER=nextjs
```

or

```env
GUI_ADAPTER=terminal
```

You can also override from CLI:

```bash
python gui.py --adapter terminal
```

## Select scenario

Set in `.env`:

```env
GUI_SCENARIO=workday_blend
```

Available scenarios:
- `empty`
- `workday_blend`
- `exam_crunch`
- `home_reset`

Or override from CLI:

```bash
python gui.py --scenario exam_crunch
```

## Host/port overrides

```bash
python gui.py --host 127.0.0.1 --port 9000
```

## Optional flags

- `--disable-timers` disables runtime notification timers
- `--open-browser` opens the GUI URL in your default browser
- `--frontend-dev` runs the Next.js UI in dev mode (hot reload)
- `--frontend-port 3000` sets the Next.js dev server port
- `--data-dir .gui_data` sets where JSON data files are stored

## Live reload while editing UI

This is now the default behavior of `python gui.py`.
Equivalent explicit command:

```bash
python gui.py --frontend-dev --frontend-port 3000
```

Then open `http://127.0.0.1:3000`.  
The Python backend still runs on `http://127.0.0.1:8765` for API/SSE.

You can also enable this permanently in `.env`:

```env
GUI_FRONTEND_DEV=true
GUI_FRONTEND_PORT=3000
```

To force static exported frontend instead:

```bash
python gui.py --no-frontend-dev
```

## Data persistence

GUI data now persists to JSON files by default:
- `.gui_data/life_areas.json`
- `.gui_data/tasks.json`

Set a custom location in `.env`:

```env
GUI_DATA_DIR=.gui_data
```

or via CLI:

```bash
python gui.py --data-dir /path/to/gui-data
```

When persisted data exists, the seed scenario is skipped to avoid duplicate tasks.
