# opentron-gui-edge

Opentrons GUI edge scaffold based on `PUDAP/edge-python-gui-template`, commit
`f72a05931341862c51cd169aa8a1896bcfbcf0c1`.

Screenshot contract updated from upstream commit
`e80b62a2cfa70c1f54a3405eb35114c7717bd7bf`: a single capture can return
image, capture context, and copied accessibility elements; `get_elements` is removed.

Implemented Opentrons command: `list_protocols()` (first high-level `@command`
in `driver.py`). It navigates to Protocols when necessary and returns
`{"protocols": [{"name": "...", "instruments": [], "updated": "..."}], "count": N}`.
Duplicate names are preserved; timestamps use the App display format. It reads
AX cards, including offscreen entries, and requires the list's footer to reject
truncated/unsupported captures. Layouts without this footer (including unverified
empty-library layouts) raise instead of claiming an empty list. No robot actions
are dispatched. Verified on the live desktop library: 8 cards; 61 tests pass.

After configuring and starting the edge, invoke:
`puda machine run opentron-gui-edge list_protocols`

`import_protocol(file_path, timeout=30.0)` imports an existing absolute `.py` or
`.json` path through Protocols → Import → browse → the system file picker. It
validates the path before input and returns `imported_file` plus the newly observed
protocol card. It never starts setup/runs or automatically repeats an uncertain
import. Library-card verification is not proof of successful protocol analysis.
Concurrent imports can make card attribution ambiguous; serialize GUI commands.
This command uses the existing native-dialog helper, which foregrounds the chooser
and types its path on Linux. End-to-end import testing requires a selected file
and permission to use foreground input; it has only been tested offline so far.

Example after deployment:
`puda machine run opentron-gui-edge import_protocol --file_path "/absolute/path/protocol.py"`

`start_setup(protocol_name: str)` opens the exact named card's three-dot menu,
chooses `Start setup`, and waits for the robot-selection entry screen containing
`Proceed to setup` (it may be disabled). Returns `protocol_name` and
`setup_open=True`. It does not select a robot or click `Proceed to setup` and
never starts a run. Duplicate names, missing cards, ambiguous menus, and offscreen
buttons raise before menu input. Scroll the intended card into view beforehand.
Waits are bounded to 10 seconds per phase; no setup click is automatically retried.
This command is offline-tested; live setup navigation has not been exercised.

Example after deployment:
`puda machine run opentron-gui-edge start_setup --protocol_name "100 uL Water Transfer"`

`select_robot(robot_name: str = "")` selects a robot in the currently open
robot-choice drawer. Omitted/empty name uses the first listed card; supplied names
match exactly. No listed robots, missing names, duplicates, unsupported/closed
drawers, and offscreen targets raise without a selection click. After selecting,
it waits for an enabled `Proceed to setup`, clicks once, and verifies the intended
robot's visible `Not started` setup page. This uploads/creates the setup run on
the robot; use only with setup-progression authorization. It never clicks Start run.

Returns `robot_name`, `selection_dispatched`, `selection_verified`, and
`setup_open=True`. The selection flag refers only to AX card selection and can be
false for CSS-only cards; `setup_open` requires a separate destination-page check.
Proceed availability waits up to 10 seconds; setup-page verification up to 30.
Timeouts raise without repeating Proceed. The implementation is offline-tested,
not live-tested.

Examples after deployment:
`puda machine run opentron-gui-edge select_robot`
`puda machine run opentron-gui-edge select_robot --robot_name "your-robot-name"`

`start_run(timeout: float = 30.0)` operates on the current prepared run only.
The caller must verify robot/protocol identity, successful analysis, setup readiness,
physical clearance and authorization. It requires `Not started` and one enabled
Start run button, clicks once, then returns `started=True` with observed `Running`
or `Completed`. It raises on failure, a confirmation dialog, or timeout and never
silently confirms warnings or repeats Start. Short runs may complete before a
Running capture. A run-start response is not proof of experiment completion unless
its returned status is Completed.

Live-test preparation revealed that even the comment-only import-fix protocol's
App Run Preview includes automatic homing before the comment. Do not classify it
as motion-free based on source alone. The queued run was inspected but not started:
additional homing/clearance authorization was unanswered. Evidence is in
`docs/live-test/`; live Start run remains untested.

Run-state commands (all operate on the current run-detail page):

- `get_run_status()` is read-only and returns robot/protocol identity, displayed
  run timestamp, status, run time, enabled header controls, and confirmation_pending.
  This is the requested name; no `get_run_process` alias was added. The parser scopes
  the run header so preview headings and historical records are not mistaken for
  current state. Status and timestamps retain the App's wording/format.
- `pause_run(timeout=30.0)` requires Running, clicks Pause run once, verifies Paused.
- `resume_run(timeout=30.0)` requires Paused, clicks Resume run once, verifies
  Running or rapid Completed. Door-open/recovery states are not bypassed.
- `cancel_run(timeout=30.0)` clicks Cancel run and confirms only the standard
  `Are you sure you want to cancel?` → `Yes, cancel run` modal, then verifies
  Canceled. OT-2 cancellation can drop attached tips and home; modules can remain
  active. Caller must authorize these consequences and verify physical clearance.

Every control checks that robot/protocol/run identity remains unchanged, uses fresh
read-back, rejects invalid states and unknown warnings, and never retries input
on timeout. A run-state response is not independent proof that all hardware has
stopped or cleanup ended. Control methods are offline-tested, not live-exercised.
The read-only status method was live-tested and observed the harmless queued run
as Completed with App-displayed duration `00:00:18`; this agent did not start it.

Inventory commands:

- `list_devices()` navigates to Devices, expands collapsed availability sections,
  and returns `devices` (name, model, available, instruments) plus `count`. It checks
  parsed counts against Available/Not Available section totals. Availability does
  not imply idle robot state; no robot controls are opened.
- `list_labware(category="All", sort_by="Alphabetical")` navigates to Labware,
  selects the actual GUI category and sort options, and returns `labware`
  (name, category, api_name), `count`, selected `category`, and `sort_by`. It keeps
  the GUI order, includes offscreen accessibility cards, and verifies the list footer.
  No labware definitions are imported, deleted or modified.

Category labels (case-insensitive): All, Adapter, Aluminum Block, Custom Labware,
Lid, Reservoir, Tip Rack, Tube Rack, Well Plate.
Sort labels (case-insensitive): Alphabetical, Reverse alphabetical.
Unsupported labels raise before navigation. No fuzzy aliases are inferred.

Live-tested: 2 devices; default All/Alphabetical returned 119 labware definitions;
Tip Rack/Reverse alphabetical returned 18 definitions in the reversed baseline
order; Custom Labware returned a verified empty list. Defaults were restored after
validation. Full results are saved under `docs/live-test/` as
`list-devices.json`, `list-labware-all.json`, and `list-labware-tip-rack-reverse.json`.

Examples after deployment:
`puda machine run opentron-gui-edge list_devices`
`puda machine run opentron-gui-edge list_labware --category "Tip Rack" --sort_by "Reverse alphabetical"`

The generic template `import_file` command has been removed. Use `import_protocol`
for Opentrons imports. Only the high-level workflows and the inspection
command listed below are remotely exposed; low-level actions remain inherited
Python operations for internal use.

The example configuration targets `Opentrons OT-2` (the observed App name/title,
not the broad `Opentrons` substring which can also match editor windows) and proposes machine ID
`opentron-gui-edge`. Confirm the machine ID and NATS servers before deployment.
No live `.env` is created and no edge service is started during scaffolding.

Generic template documentation follows.

A template for PUDA edge services that integrate **any desktop instrument software** into PUDA without a hardware SDK. Copy it once per machine, set the window name, and add that machine's commands. It runs on **Windows** and **Linux (X11)**.

| Layer | Technology | Role |
|---|---|---|
| GUI automation | [Hermes computer use](https://hermes-agent.nousresearch.com/docs/user-guide/features/computer-use) → `cua-driver` MCP | Capture the app and dispatch accessibility / keyboard / mouse actions |
| PUDA integration | `puda==0.0.18` `EdgeRunner` + NATS | Expose allowlisted commands and machine state to the PUDA platform |

There is **no LLM**: screens are returned as raw base64 PNG, and the driver selects elements by exact, case-sensitive accessibility labels and optional roles.

---

## Repo Structure

```
edge-python-gui-template/
├── pyproject.toml    # dependencies (puda, mcp, pydantic-settings)
├── main.py           # Config → Driver → EdgeNatsClient → EdgeRunner
├── driver.py         # Driver: machine-specific commands built on GuiDriver
├── gui_driver.py     # GuiDriver: undecorated GUI operations and lifecycle
├── cua_client.py     # CuaDriverClient: MCP connection, window discovery and input
├── tests/            # offline tests for the generic logic
├── .env.example      # environment variable template
├── start_edge.bat    # Windows launcher
└── start_edge.sh     # Linux launcher
```

---

## How It Works

```
PUDA CLI / Protocol
       │  NATS
       ▼
  EdgeRunner ───────────►  Driver (@command methods)
   (state_handler =                │
    driver._snapshot)          GuiDriver
                                   │
                              CuaDriverClient
                                   │
                             cua-driver MCP
                                   │
                          ┌────────▼─────────┐
                          │ Instrument       │
                          │ software (any)   │
                          └──────────────────┘
```

This follows the PUDA 0.1.x edge contract:

1. Only methods marked `@command` are remotely callable.
2. Internal helpers, startup, cached state and telemetry use a leading underscore.
3. `EdgeRunner` publishes heartbeat and host-health telemetry; `main.py` passes `driver._snapshot` as the state handler.
4. Command signatures and docstrings are published in the command catalog, so every command needs type hints and a docstring.

---

## Prerequisites

### 1. Install Hermes Agent with computer use (both platforms)

```bash
hermes computer-use install
hermes computer-use doctor      # all checks should be green
```

`cua-driver` must be on your `PATH`.

### 2. Python environment (uv)

```bash
uv sync
```

### 3. Platform requirements

**Windows**
- Run from an interactive session (RDP or console). Over SSH (Session 0) the GUI is not reachable; use the [Windows SSH guide](https://cua.ai/docs/how-to-guides/driver/windows-ssh) or the cua-driver autostart task.
- `main.py` restarts itself once in UTF-8 mode so PUDA can decode command output.

**Linux**
- **Use an X11 session.** On GNOME/Wayland, native Wayland windows (including the file chooser) are invisible to cua-driver. At the login screen click your user, then the ⚙ icon at the bottom right and pick **Ubuntu on Xorg**. Check with `echo $XDG_SESSION_TYPE` → `x11`.
- Start the driver from a terminal **inside** that desktop session (or export `DISPLAY` and `XAUTHORITY`). The driver forwards `DISPLAY`, `XAUTHORITY`, `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`, `XDG_SESSION_TYPE` and `DBUS_SESSION_BUS_ADDRESS` to cua-driver.
- Electron apps may need `--no-sandbox --force-renderer-accessibility` to start and to expose their accessibility tree.
- Terminals inside Cursor / VS Code set `ELECTRON_RUN_AS_NODE=1`, which makes Electron apps exit silently. `unset ELECTRON_RUN_AS_NODE` before launching one (`start_edge.sh` does this for the driver).
- The target window needs desktop focus for input; the driver brings it to the foreground before capturing.

---

## Setup

```bash
cp .env.example .env        # Windows: Copy-Item .env.example .env
```

| Variable | Description |
|---|---|
| `MACHINE_ID` | Unique PUDA machine ID, e.g. `hplc-1` |
| `NATS_SERVERS` | NATS cluster URLs |
| `TARGET_APP` | Window title (or a unique part of it) of the instrument software |

### Finding the TARGET_APP name

`TARGET_APP` is matched case-insensitively against the window **title** and the **app name** as cua-driver sees them.

```powershell
# Windows
Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object MainWindowTitle
```

```bash
# Linux (X11)
xwininfo -root -tree | grep '"'
```

---

## Run

Run the edge directly on the instrument's desktop host, in the same interactive desktop session as the target application. The agent can connect remotely through PUDA; desktop automation runs on this host.

```bash
# Windows
.\start_edge.bat
# Linux
./start_edge.sh
# Or directly
uv run python main.py
```

---

## GUI operations and remote commands

`driver.py` exposes these commands through `@command`:

- Protocols: `list_protocols`, `import_protocol`, `start_setup`, `select_robot`.
- Runs: `start_run`, `pause_run`, `resume_run`, `cancel_run`, `get_run_status`.
- Inventory: `list_devices`, `list_labware`.
- Inspection: `capture_screenshot` (optionally with `include_elements=True`).

The eight low-level operations `find_element`, `wait_for_element`, `click_element`,
`set_value`, `type_text`, `scroll`, `press_key`, and `click_at` are not remotely
callable. Their decorated overrides were removed from `driver.py`; high-level
commands still use the ordinary inherited implementations in `GuiDriver`.
`GuiDriver` now returns copied elements from the same screenshot capture.
`cua_client.py` is unchanged by this upstream update.

`capture_screenshot()` returns `image_b64` and copied `capture` metadata.
`capture_screenshot(include_elements=True)` additionally returns a deep-copied
`elements` list from that same capture. Without the flag, no elements field is
returned. The separate `get_elements` method/command has been removed from Driver
and GuiDriver; internal workflows consume the single screenshot response instead.
Captures foreground the App and invalidate previous coordinate-capture IDs.

Constructing `Driver` connects the MCP client. `main.py` calls `_close()` in a
`finally` block on exit or failure. No generic reset command is exposed.

### Example CLI usage

```bash
puda machine run opentron-gui-edge capture_screenshot
puda machine run opentron-gui-edge capture_screenshot --include_elements true
puda machine run opentron-gui-edge list_protocols
puda machine run opentron-gui-edge list_labware --category "Tip Rack"
```

### Command migration

Machine commands call the public methods directly: `find_element`, `click_element`, and `capture_screenshot(include_elements=False)`. The redundant private wrappers have been removed. Use `capture_screenshot()["image_b64"]` when only the PNG is needed.

Command responses omit the configured app name. `capture_screenshot` returns `image_b64` and `capture`; `include_elements=True` also returns a copied `elements` list from the same capture. The configured `target_app` remains in machine state for diagnostics. The copied `capture` context contains `capture_id`, `pid`, `window_id`, `bounds` (window x/y/width/height), and screenshot pixel `width`/`height`.

`click_at(x, y, capture_id)` requires `result["capture"]["capture_id"]` from the screenshot used to choose coordinates. The ID is single-use and invalidated by subsequent captures or input. The client verifies the exact window's identity, visibility, and bounds before and after foregrounding it; it does not reposition the window or recapture. Call `capture_screenshot` separately for post-click feedback. If capture metadata or native targeted input is unavailable, `capture` is null and coordinate clicks are unavailable. These checks cannot detect changed content inside an otherwise unchanged window or prevent an external change between validation and dispatch.

`capture_screenshot` replaces both `status` and `ask_screen`; interpret images in the calling agent. Replace `find_and_click(description)` with `click_element(label, role)` using exact, case-sensitive values from `capture_screenshot(include_elements=True)["elements"]`. Replace `type_text(text, field_description)` with separate `click_element` and `type_text` calls. Machine helpers now use `click_element(label, role)` instead of the former fuzzy helper.

Matching considers enabled elements only. Missing or duplicate matches raise before input. `capture_screenshot(include_elements=True)` requires a capture backend that supplies accessibility elements; screenshot-only backends cannot support element lookup. This does not change the client's existing window-selection heuristics or guarantee that the UI action completed; machine commands should check their expected result.

## Extending this driver

Keep machine-specific workflows in `driver.py`, reusable Python GUI operations
in `gui_driver.py`, and MCP/desktop transport in `cua_client.py`. Add `@command`
only to intended remote workflows; exposing a helper is an explicit API change.
If overriding the constructor, retain `super().__init__(target_app=target_app)`.

High-level commands can call inherited helpers such as `self.click_element(...)`,
`self.wait_for_element(...)`, and `self._choose_file_in_dialog(...)` without
making those helpers remotely callable. Use `import_protocol` for the native
file-picker workflow and `get_run_status` for run-detail read-back.

Document public commands with a summary, parameter descriptions, returned
evidence, and expected failures. State precisely what a successful return proves.
Dispatch each consequential action once, verify a fresh operation-specific state,
and raise on failure/timeout rather than returning a misleading false result.
Keep robot identity, protocol identity and run identity stable across transitions.

Test commands, their invalid states, stale/ambiguous selectors, disabled controls,
known errors and timeouts. Verify both the exact remote catalog and continued
internal inheritance using `uv run python -m unittest discover -s tests`.
Offline tests are not evidence of live physical readiness or successful GUI input.

### Telemetry

The base driver does not schedule screenshot telemetry. A machine that needs it can define its own method in `driver.py`, decorate it with `@tlm_stream(interval=30.0, name="instrument_status")` (imported from `puda`), and return `{"image_b64": self.capture_screenshot()["image_b64"]}`. Each capture brings the window to the foreground and invalidates any outstanding coordinate-click capture ID.

---

## Things to Know

- **The app repaints slowly.** Wait for an expected UI state with a bounded timeout rather than assuming a fixed sleep proves completion. `_wait_file_dialog` polls for dialog appearance and disappearance.
- **Prefer `click_element` over pixels.** Use `click_at` only with coordinates taken from a fresh screenshot.
- **Windows and Linux differ only at the edges:** the file-chooser (handled by `_choose_file_in_dialog`) and how the window is found. Page-level checks that rely on an app exposing its URL do not work on Linux accessibility trees; verify the screen instead.

---

## Troubleshooting

**`cua-driver not found`** — run `hermes computer-use install` and confirm `cua-driver --version` works in a new terminal.

**`No window matching 'X'`** — the app is not running, is minimised on another desktop, or (Linux) is a native Wayland window. Switch to an X11 session and check `TARGET_APP` against the window list above.

**No image returned from capture** — the window may be off-screen; the driver tries to restore it. On Windows run `hermes computer-use doctor`.

**`foreground_unavailable` / `background_unavailable`** — the window could not get input focus. Click the target window once, or make sure you are in an X11 session.

**`No accessible UI element matched …`** — use words that appear in the element's label, or take a screenshot and use `click_at`.

**File dialog is not found (Linux)** — it must be an X11 window (X11 session). The GNOME chooser is owned by `xdg-desktop-portal-gnome` and titled "Open Files".

**Electron app exits immediately (Linux)** — `unset ELECTRON_RUN_AS_NODE`; add `--no-sandbox` if you see a `chrome-sandbox` error.
