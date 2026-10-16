# opentrons-gui-edge

PUDA edge for the Opentrons App. These are the remote commands.

A protocol run is `import_protocol` (if it is not already in the library), then `start_setup`, `select_robot`, and `start_run`.

## Protocols

**`list_protocols()`**

Reads the Protocols page. Returns `protocols` (`name`, `instruments`, `updated`) and `count`. Duplicate names are kept. Timestamps stay in the App's display format. Does not open a protocol or contact a robot.

**`import_protocol(file_path, timeout=30.0)`**

Imports an absolute `.py` or `.json` path through Protocols → Import → the system file picker. Returns `imported_file` and the new protocol card (`name`, `instruments`, `updated`). A new card means the file entered the library, not that analysis succeeded. Does not start setup or a run.

**`start_setup(protocol_name)`**

Opens the named protocol's three-dot menu and chooses Start setup. The name must match one card exactly. Returns `protocol_name` and `setup_open=True` once the robot-selection screen is showing, including when Proceed to setup is still disabled. Does not select a robot or start a run.

**`select_robot(robot_name="")`**

Selects a robot on the open setup screen from `start_setup`. An empty name uses the first listed robot; a supplied name must match exactly. Clicks Proceed to setup once. Returns `robot_name`, `selection_dispatched`, `selection_verified`, and `setup_open=True` after that robot's Not started setup page is visible. This can upload the protocol for setup. It does not click Start run.

## Runs

These commands act on the current run-detail page.

**`start_run(timeout=30.0)`**

Clicks Start run once when the current run is Not started. Returns `started=True` and `status` (`Running` or `Completed`). A short run can finish before a Running capture. Does not accept warning dialogs.

**`get_run_status()`**

Reads the current run header without changing it. Returns `robot_name`, `protocol_name`, `run_label`, `status`, `run_time`, `available_controls`, and `confirmation_pending`.

**`pause_run(timeout=30.0)`**

Pauses a Running run and returns a fresh status once it is Paused.

**`resume_run(timeout=30.0)`**

Resumes a Paused run and returns a fresh status once it is Running or Completed. Door-open and recovery states are left as they are.

**`cancel_run(timeout=30.0)`**

Cancels the current run, confirms the standard cancel dialog, and returns a fresh status once it is Canceled. On an OT-2 this can drop attached tips and home the robot. Modules can stay active.

## Inventory

**`list_devices()`**

Opens Devices, expands collapsed groups, and returns `devices` (`name`, `model`, `available`, `instruments`) and `count`. Availability is the App's grouping, not proof the robot is idle. Does not open robot controls.

**`list_labware(category="All", sort_by="Alphabetical")`**

Opens Labware, sets the category and sort, and returns `labware` (`name`, `category`, `api_name`), `count`, `category`, and `sort_by` in the App's order.

Categories: All, Adapter, Aluminum Block, Custom Labware, Lid, Reservoir, Tip Rack, Tube Rack, Well Plate.

Sort: Alphabetical, Reverse alphabetical.

This is the definition library, not what is on the deck. Definitions are not imported, deleted, or edited.

## Inspection

**`capture_screenshot(include_elements=False)`**

Returns `image_b64` and `capture` (`capture_id`, `pid`, `window_id`, `bounds`, `width`, `height`). `include_elements=True` also returns the accessibility `elements` from that same capture. Bringing the App forward invalidates earlier capture IDs.
