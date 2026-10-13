"""Opentrons App workflows and read-only inspection commands for PUDA.

Only the decorated high-level workflows and capture_screenshot are remotely callable. Generic GUI actions remain inherited Python operations
from GuiDriver for internal composition; they are not exposed as commands.
"""

import math
import re
import time
from collections import Counter
from pathlib import Path

from puda import command

from gui_driver import ElementNotFoundError, GuiDriver


class Driver(GuiDriver):
    """Opentrons workflows; to run a protocol, load it, start setup, select a robot, then start the run."""

    def __init__(self, target_app: str) -> None:
        """Connect the GUI backend for this instrument.

        Args:
            target_app: Application name or window-title substring to target.

        Raises:
            RuntimeError: The GUI backend cannot start or initialize.
            TimeoutError: Backend initialization exceeds its timeout.
        """
        super().__init__(target_app=target_app)

    # Shared snapshot inspection and validation.

    def _capture_elements(self) -> list[dict]:
        """Capture fresh accessibility elements; indices belong to this snapshot."""
        return self.capture_screenshot(include_elements=True)["elements"]

    def _visible_elements(self, context: str) -> list[dict]:
        """Capture elements with usable on-screen positions."""
        visible = []
        for element in self._capture_elements():
            try:
                self._validate_element_position(element, context)
            except RuntimeError:
                continue
            visible.append(element)
        return visible

    @staticmethod
    def _is_confirmation(element: dict) -> bool:
        """Recognize native and App-specific confirmation containers."""
        return (element.get("role") in {"dialog", "alert dialog"}
                or element.get("label") == "ModalShell_ModalArea")

    @staticmethod
    def _validate_timeout(timeout: float) -> None:
        """Reject unbounded or negative command timeouts before GUI input."""
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and non-negative")

    # Protocol library and setup commands.

    @command
    def list_protocols(self) -> dict:
        """Read imported protocol cards from the Opentrons App's Protocols page.

        Returns names, instrument labels and displayed update timestamps without
        opening a protocol or contacting the robot. Duplicate names are preserved.
        Uses the App accessibility tree, including offscreen cards. Unsupported or
        incomplete layouts raise rather than returning a misleading empty list.

        Returns:
            dict: protocols (name, instruments, updated) and count. Timestamps
                retain the App's displayed format; no timezone is inferred.

        Raises:
            RuntimeError: The page or card layout is unsupported, incomplete,
                ambiguous, or the GUI backend fails.
        """
        elements = self._capture_elements()
        links = {e.get("element_index") for e in elements if e.get("role") == "link"}
        on_list = any(e.get("role") == "heading" and e.get("label") == "Protocols"
                      and e.get("parent_index") not in links for e in elements)
        if not on_list:
            if not any(e.get("role") == "link" and e.get("label") == "Protocols"
                       for e in elements):
                raise RuntimeError("Opentrons Protocols navigation is unavailable")
            self.click_element("Protocols", role="link")
            # Refresh separately: dispatch alone does not establish navigation.
            deadline = time.monotonic() + 10.0
            while True:
                elements = self._capture_elements()
                links = {e.get("element_index") for e in elements if e.get("role") == "link"}
                if any(e.get("role") == "heading" and e.get("label") == "Protocols"
                       and e.get("parent_index") not in links for e in elements):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Timed out waiting for the Protocols list")
                time.sleep(0.2)
        if not any(e.get("label") == "Create or download a new protocol" for e in elements):
            raise RuntimeError("Protocol list is incomplete or its accessibility layout is unsupported")
        children = self._children_by_parent(elements)
        protocols = []
        for e in elements:
            if e.get("role") != "section":
                continue
            fields = [x.get("label", "") for x in children.get(e.get("element_index"), [])
                      if x.get("role") == "paragraph"]
            if "Instruments" not in fields:
                continue
            instrument_index = fields.index("Instruments")
            updates = [i for i, label in enumerate(fields) if label.startswith("Updated ")]
            if instrument_index != 1 or len(updates) != 1 or updates[0] != len(fields) - 1:
                raise RuntimeError("Unsupported protocol card layout")
            protocols.append({"name": fields[0],
                              "instruments": fields[instrument_index + 1:updates[0]],
                              "updated": fields[updates[0]][len("Updated "):]})
        return {"protocols": protocols, "count": len(protocols)}

    @command
    def import_protocol(self, file_path: str, timeout: float = 30.0) -> dict:
        """Import a protocol into the Opentrons App using the system file picker.

        This loads the protocol as the first step of the run workflow. After a
        successful import, call start_setup with its displayed name, then call
        select_robot, and finally call start_run.

        Opens Protocols, clicks Import, then browse in the import sidebar and
        selects the file with the native chooser. Returns only after observing
        exactly one new protocol card. Does not start setup or run the robot.
        Card creation confirms library import, not successful protocol analysis.
        Never automatically retries an import after an uncertain outcome.

        Args:
            file_path: Absolute path to an existing .py or .json file on this host.
            timeout: Finite non-negative timeout in seconds for each wait phase;
                defaults to 30. GUI captures have their own backend timeout.

        Returns:
            dict: imported_file and protocol (name, instruments, updated) observed
                as a new library entry after selecting the requested file.

        Raises:
            ValueError: Path is empty, relative, has an unsupported extension, or
                timeout is invalid.
            FileNotFoundError: Path does not identify a readable file.
            TimeoutError: The new card is not observed before the deadline.
            RuntimeError: GUI/picker fails, layout is unsupported, or multiple new
                entries make import verification ambiguous.
        """
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path must be a non-empty absolute path")
        path = Path(file_path)
        if not path.is_absolute():
            raise ValueError("file_path must be absolute")
        if path.suffix.lower() not in {".py", ".json"}:
            raise ValueError("Protocol file must have a .py or .json extension")
        self._validate_timeout(timeout)
        if not path.is_file():
            raise FileNotFoundError(file_path)
        with path.open("rb") as stream:
            stream.read(1)  # validate readability before any GUI input

        def signature(card: dict) -> tuple[str, tuple[str, ...], str]:
            return (card["name"], tuple(card["instruments"]), card["updated"])

        before = Counter(signature(card) for card in self.list_protocols()["protocols"])
        self.click_element("Import", role="push button")
        sidebar = self.wait_for_element("Import a Protocol", role="heading", timeout=timeout)
        self._validate_element_position(sidebar, "Import a Protocol")
        self.click_element("browse", role="push button")
        self._choose_file_in_dialog(file_path, timeout=timeout)

        deadline = time.monotonic() + timeout
        while True:
            cards = self.list_protocols()["protocols"]
            remaining = before.copy()
            added = []
            for card in cards:
                key = signature(card)
                if remaining[key] > 0:
                    remaining[key] -= 1
                else:
                    added.append(card)
            if len(added) > 1:
                raise RuntimeError("Multiple new protocol cards; import result is ambiguous")
            if len(added) == 1:
                return {"imported_file": file_path, "protocol": added[0]}
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise TimeoutError("Import was submitted but no new protocol card was verified; inspect the App before retrying")
            time.sleep(min(0.5, remaining_time))

    @command
    def start_setup(self, protocol_name: str) -> dict:
        """Open a protocol's setup entry screen through its three-dot menu.

        The protocol must already be loaded in the library, using import_protocol
        if necessary. After this command succeeds, call select_robot and then
        start_run.

        Matches the exact, case-sensitive protocol name in the complete library;
        duplicate names are rejected. Opens only that card's overflow menu and
        chooses Start setup. Verifies the robot-selection screen's Proceed to
        setup control, even if disabled pending robot selection. Does not select
        a robot, press Proceed to setup, upload to a robot, or start a run.

        Args:
            protocol_name: Non-empty exact displayed name of one imported protocol.

        Returns:
            dict: protocol_name and setup_open=True after the entry screen is observed.

        Raises:
            ValueError: protocol_name is empty or not a string.
            ElementNotFoundError: No protocol has the requested name.
            RuntimeError: Name/menu is ambiguous, a card is offscreen, the layout
                changes, or GUI input fails. Scroll the card into view if needed.
            TimeoutError: Start setup or the setup entry screen is not observed
                within 10 seconds per phase. Actions are never automatically retried.
        """
        if not isinstance(protocol_name, str) or not protocol_name.strip():
            raise ValueError("protocol_name must be a non-empty exact name")
        matches = [p for p in self.list_protocols()["protocols"]
                   if p["name"] == protocol_name]
        if not matches:
            raise ElementNotFoundError(f"No protocol named {protocol_name!r}")
        if len(matches) != 1:
            raise RuntimeError(f"Ambiguous protocol name: {protocol_name!r}")

        # Resolve the card and its unlabeled overflow button in one fresh capture.
        elements = self._capture_elements()
        children = self._children_by_parent(elements)
        cards = [element for element in elements if element.get("role") == "section"
                 and any(child.get("label") == protocol_name and child.get("role") == "paragraph"
                         for child in children.get(element.get("element_index"), []))
                 and any(child.get("label") == "Instruments"
                         for child in children.get(element.get("element_index"), []))]
        if len(cards) != 1:
            raise RuntimeError("Protocol card changed or is ambiguous; no menu was opened")
        descendants = self._descendants(
            children, cards[0]["element_index"], "Malformed accessibility tree"
        )
        buttons = [element for element in descendants
                   if element.get("role") == "push button" and element.get("enabled", True)]
        if len(buttons) != 1:
            raise RuntimeError("Expected one protocol-card overflow button; no menu was opened")
        button = buttons[0]
        self._validate_element_position(button, f"{protocol_name} overflow menu")
        self._run(self._cua.click(element=int(button["element_index"])))
        menu_item = self.wait_for_element("Start setup", timeout=10.0)
        self._validate_element_position(menu_item, "Start setup")
        self.click_element("Start setup")

        deadline = time.monotonic() + 10.0
        while True:
            elements = self._capture_elements()
            proceed = [element for element in elements
                       if element.get("label") == "Proceed to setup"
                       and element.get("role") == "push button"]
            if len(proceed) > 1:
                raise RuntimeError("Ambiguous setup entry screen")
            if len(proceed) == 1:
                self._validate_element_position(proceed[0], "Proceed to setup")
                return {"protocol_name": protocol_name, "setup_open": True}
            if time.monotonic() >= deadline:
                raise TimeoutError("Setup was requested but its entry screen was not verified; inspect before retrying")
            time.sleep(0.2)

    def _robot_choices(self, elements: list[dict]) -> list[tuple[dict, dict]]:
        """Extract model/name cards only within the open robot-choice drawer."""
        by_index = {e["element_index"]: e for e in elements}
        children = self._children_by_parent(elements)

        def descendants(index: int) -> list[dict]:
            return self._descendants(
                children, index, "Malformed robot-choice accessibility tree"
            )

        headings = [e for e in elements if e.get("role") == "heading"
                    and " ".join(e.get("label", "").split()).casefold().startswith("choose robot to run")]
        if len(headings) != 1:
            raise RuntimeError("Open one robot-selection screen with start_setup first")
        self._validate_element_position(headings[0], "robot-selection drawer")
        scope = by_index.get(headings[0].get("parent_index"))
        visited = set()
        while scope is not None:
            index = scope["element_index"]
            if index in visited:
                raise RuntimeError("Malformed robot-choice ancestry")
            visited.add(index)
            items = descendants(index)
            if any(e.get("role") == "push button" and e.get("label") in
                   {"Proceed to setup", "Continue to parameters"} for e in items):
                break
            scope = by_index.get(scope.get("parent_index"))
        if scope is None:
            raise RuntimeError("Unsupported robot-selection drawer layout")
        scoped = {e["element_index"] for e in descendants(scope["element_index"])}
        choices = []
        used = set()
        for model in elements:
            if model["element_index"] not in scoped or model.get("role") != "heading" or model.get("label") not in {"OT-2", "Flex"}:
                continue
            card = by_index.get(model.get("parent_index"))
            while card is not None and card["element_index"] in scoped:
                names = [e for e in descendants(card["element_index"])
                         if e.get("role") == "paragraph" and e.get("label", "").strip()
                         and "\ufffc" not in e.get("label", "")]
                if len(names) == 1:
                    name = names[0]
                    if name["element_index"] not in used and name.get("enabled", True):
                        used.add(name["element_index"])
                        choices.append((name, card))
                    break
                if len(names) > 1:
                    raise RuntimeError("Unsupported robot card: multiple possible robot names")
                card = by_index.get(card.get("parent_index"))
        return choices

    def _wait_for_robot_setup(self, robot_name: str) -> None:
        """Require visible robot identity and Not started after Proceed dispatch."""
        deadline = time.monotonic() + 30.0
        while True:
            visible = self._visible_elements("setup read-back")
            labels = {e.get("label", "") for e in visible}
            drawer_open = any(e.get("role") == "heading" and
                              " ".join(e.get("label", "").split()).casefold().startswith("choose robot to run")
                              for e in visible)
            if robot_name in labels and "Not started" in labels and not drawer_open:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Proceed was dispatched but the intended robot's Not started setup page was not verified; inspect before retrying")
            time.sleep(0.5)

    @command
    def select_robot(self, robot_name: str = "") -> dict:
        """Select a listed robot in the currently open setup robot-choice screen.

        Call start_setup for a loaded protocol before this command. After robot
        selection and setup succeed, verify physical readiness and authorization,
        then call start_run.

        An omitted or empty name chooses the first listed robot in accessibility
        order. A supplied name must match exactly and uniquely. Clicks the enabled
        Proceed to setup button once, then waits for the intended robot's visible
        Not started setup page. This may upload/create a robot run for setup, but
        never clicks Start run. Requires authorization for setup progression.

        Args:
            robot_name: Exact, case-sensitive robot name. Defaults to "", meaning
                the first listed robot; whitespace is not normalized.

        Returns:
            dict: robot_name, selection_dispatched, selection_verified, and
                setup_open=True after robot identity and Not started are observed.
                selection_verified refers only to the card's AX selection state;
                CSS-only card selection may leave this false even when the
                destination setup page is verified.

        Raises:
            ValueError: robot_name is not a string.
            RuntimeError: No robots are listed, the named robot is missing or
                ambiguous, the drawer is closed/unsupported, the chosen card is
                offscreen, GUI input fails, or the robot disappears after input.
            TimeoutError: Proceed stays unavailable for 10 seconds or the setup
                page is not verified within 30 seconds. Never retries Proceed.
        """
        if not isinstance(robot_name, str):
            raise ValueError("robot_name must be a string; omit it to choose the first robot")
        choices = self._robot_choices(self._capture_elements())
        if not choices:
            raise RuntimeError("No robots are listed in the setup robot-selection screen")
        matches = [choice for choice in choices if choice[0]["label"] == robot_name] if robot_name else [choices[0]]
        if not matches:
            raise RuntimeError(f"No listed robot named {robot_name!r}")
        if len(matches) != 1:
            raise RuntimeError(f"Ambiguous robot name: {robot_name!r}")
        name_element, _ = matches[0]
        chosen_name = name_element["label"]
        self._validate_element_position(name_element, f"robot {chosen_name}")
        self._run(self._cua.click(element=int(name_element["element_index"])))
        observed = [choice for choice in self._robot_choices(self._capture_elements())
                    if choice[0]["label"] == chosen_name]
        if len(observed) != 1:
            raise RuntimeError("Robot list changed after selection; inspect before retrying")
        name, card = observed[0]
        verified = any(e.get("selected") is True or e.get("checked") is True for e in (name, card))
        proceed = self.wait_for_element("Proceed to setup", role="push button", timeout=10.0)
        self._validate_element_position(proceed, "Proceed to setup")
        self.click_element("Proceed to setup", role="push button")
        self._wait_for_robot_setup(chosen_name)
        return {"robot_name": chosen_name, "selection_dispatched": True,
                "selection_verified": verified, "setup_open": True}

    @command
    def start_run(self, timeout: float = 30.0) -> dict:
        """Start the currently prepared, authorized protocol run in the App.

        Required command sequence: load the protocol with import_protocol if it is
        not already in the library, call start_setup for that protocol, call
        select_robot, then call start_run. Do not skip setup or robot selection.

        The caller must verify robot/protocol identity, analysis, physical readiness
        and run authorization before invocation. Requires Not started and one
        enabled Start run control. Clicks once, then observes Running or Completed.
        Does not automatically accept warning dialogs, resume, or repeat Start.
        A confirmation dialog raises for explicit inspection rather than guessing.

        Args:
            timeout: Finite non-negative seconds to observe the post-click status;
                defaults to 30. Backend capture timeouts are separate.

        Returns:
            dict: started=True and status (Running or Completed). Completed allows
                very short protocols that finish before a Running capture.

        Raises:
            ValueError: timeout is invalid.
            RuntimeError: The run is not ready, controls are ambiguous/disabled,
                a confirmation is needed, input fails, or the run reports failure.
            TimeoutError: Start was dispatched but no accepted transition is observed.
                Inspect the live run before retrying; dispatch is never repeated.
        """
        self._validate_timeout(timeout)

        elements = self._visible_elements("run control/status")
        if any(self._is_confirmation(e) for e in elements):
            raise RuntimeError("An existing confirmation must be resolved before Start run")
        labels = {e.get("label", "") for e in elements}
        if "Not started" not in labels or labels.intersection({"Running", "Completed", "Failed", "Stopped"}):
            raise RuntimeError("The current run must be Not started before Start run")
        buttons = [e for e in elements if e.get("label") == "Start run"
                   and e.get("role") == "push button" and e.get("enabled", True)]
        if len(buttons) != 1:
            raise RuntimeError("Expected one enabled Start run control")
        self.click_element("Start run", role="push button")
        deadline = time.monotonic() + timeout
        while True:
            elements = self._visible_elements("run control/status")
            labels = {e.get("label", "") for e in elements}
            if labels.intersection({"Failed", "Stopped"}):
                raise RuntimeError("The run reported failure/stopped after Start")
            if any(self._is_confirmation(e) for e in elements):
                raise RuntimeError("Start run confirmation is open; inspect and authorize it explicitly")
            if "Completed" in labels:
                return {"started": True, "status": "Completed"}
            if "Running" in labels:
                return {"started": True, "status": "Running"}
            if time.monotonic() >= deadline:
                raise TimeoutError("Start run was dispatched but not verified; inspect before retrying")
            time.sleep(0.5)

    @command
    def get_run_status(self) -> dict:
        """Read the current run-detail header without changing run state.

        Requires the run-detail page, not a device's history table. Values retain
        their displayed formatting. Unsupported or ambiguous layouts raise.

        Returns:
            dict: robot_name, protocol_name, run_label, status, run_time,
                available_controls (enabled header buttons), confirmation_pending.
                Run label is the displayed timestamp, not a robot API run ID.

        Raises:
            RuntimeError: The current run header/identity is absent or ambiguous,
                the status is unsupported, or accessibility capture fails.
        """
        elements = self._visible_elements("run status")
        children = self._children_by_parent(elements)
        by_index = {e["element_index"]: e for e in elements}
        headers = []
        for parent, siblings in children.items():
            labels = [e.get("label", "") for e in siblings if e.get("role") == "paragraph"]
            if all(label in labels for label in ("Run", "Status", "Run Time")):
                headers.append((parent, siblings))
        if len(headers) != 1:
            raise RuntimeError("Open one run-detail page; current run header is missing or ambiguous")
        parent, siblings = headers[0]
        paragraphs = [e.get("label", "") for e in siblings if e.get("role") == "paragraph"]

        def field(label: str) -> str:
            if paragraphs.count(label) != 1:
                raise RuntimeError(f"Ambiguous run field {label!r}")
            index = paragraphs.index(label) + 1
            if index >= len(paragraphs):
                raise RuntimeError(f"Missing run field {label!r}")
            return paragraphs[index]

        status = field("Status")
        if status not in {"Not started", "Running", "Paused", "Paused - door open",
                          "Awaiting recovery", "Stop requested", "Canceled", "Completed", "Failed", "Finishing"}:
            raise RuntimeError(f"Unsupported run status {status!r}")
        run_label = field("Run")
        titles = [e for e in elements if e.get("role") == "heading" and
                  by_index.get(e.get("parent_index"), {}).get("role") == "link" and
                  by_index.get(e.get("parent_index"), {}).get("parent_index") == parent]
        if len(titles) != 1:
            raise RuntimeError("Current protocol title is absent or ambiguous")
        crumbs = [e for e in elements if e.get("role") == "link" and e.get("label") == run_label]
        if len(crumbs) != 1:
            raise RuntimeError("Current run breadcrumb is absent or ambiguous")
        links = [e for e in children.get(crumbs[0].get("parent_index"), []) if e.get("role") == "link"]
        run_index = links.index(crumbs[0])
        if run_index == 0 or links[run_index - 1].get("label") == "Devices":
            raise RuntimeError("Current robot identity is missing")
        controls = [e.get("label") for e in siblings if e.get("role") == "push button"
                    and e.get("enabled", True) and e.get("label") in
                    {"Start run", "Pause run", "Resume run", "Cancel run", "Run again"}]
        modal = any(self._is_confirmation(e) for e in elements)
        return {"robot_name": links[run_index - 1]["label"],
                "protocol_name": titles[0]["label"], "run_label": run_label,
                "status": status, "run_time": field("Run Time"),
                "available_controls": controls, "confirmation_pending": modal}

    def _confirm_cancel_run(self) -> None:
        """Validate and accept only the recognized cancellation confirmation."""
        elements = self._capture_elements()
        areas = [e for e in elements if self._is_confirmation(e)]
        if len(areas) != 1:
            raise RuntimeError("Cancel confirmation is absent or ambiguous")
        self._validate_element_position(areas[0], "cancel confirmation")
        scoped = self._descendants(
            self._children_by_parent(elements), areas[0]["element_index"],
            "Malformed cancel confirmation accessibility tree",
        )
        scoped.append(areas[0])
        if not any(e.get("label") == "Are you sure you want to cancel?" for e in scoped):
            raise RuntimeError("Unexpected cancel warning; no confirmation was sent")
        buttons = [e for e in scoped if e.get("label") == "Yes, cancel run"
                   and e.get("role") == "push button" and e.get("enabled", True)]
        if len(buttons) != 1:
            raise RuntimeError("Cancel confirmation control is unavailable or ambiguous")
        self._validate_element_position(buttons[0], "Yes, cancel run")
        self.click_element("Yes, cancel run", role="push button")

    def _change_run_state(self, control: str, allowed: set[str], expected: set[str], timeout: float) -> dict:
        """Dispatch once and verify a status transition on the same run."""
        self._validate_timeout(timeout)
        before = self.get_run_status()
        if before["confirmation_pending"]:
            raise RuntimeError("An existing confirmation must be resolved before changing run state")
        if before["status"] not in allowed or control not in before["available_controls"]:
            raise RuntimeError(f"{control} is unavailable for status {before['status']!r}")
        identity = tuple(before[key] for key in ("robot_name", "protocol_name", "run_label"))
        self.click_element(control, role="push button")
        deadline = time.monotonic() + timeout
        cancel_confirmed = False
        while True:
            after = self.get_run_status()
            if tuple(after[key] for key in ("robot_name", "protocol_name", "run_label")) != identity:
                raise RuntimeError("Run identity changed after input; inspect before retrying")
            if after["confirmation_pending"]:
                if control != "Cancel run":
                    raise RuntimeError("A confirmation opened; inspect it before proceeding")
                if cancel_confirmed:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Cancel confirmation was sent but cancellation is not verified; inspect before retrying")
                    time.sleep(0.5)
                    continue
                self._confirm_cancel_run()
                cancel_confirmed = True
                continue
            if after["status"] in expected:
                return after
            if after["status"] in {"Completed", "Canceled", "Failed"}:
                raise RuntimeError(f"Run reached {after['status']!r} instead of the requested state")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{control} was dispatched but not verified; inspect before retrying")
            time.sleep(0.5)

    @command
    def pause_run(self, timeout: float = 30.0) -> dict:
        """Pause the current Running run and verify Paused on the same run.

        Requires authorization to control this run. Dispatches Pause run once;
        does not stop modules or claim that all hardware is stationary.

        Args:
            timeout: Finite non-negative seconds for verification; defaults to 30.

        Returns:
            dict: Fresh get_run_status fields after observing Paused.

        Raises:
            ValueError: timeout is invalid.
            RuntimeError: Run is not Running, control is unavailable, a confirmation
                is pending, identity changes, or a different terminal state appears.
            TimeoutError: Paused is not observed; inspect before retrying.
        """
        return self._change_run_state("Pause run", {"Running"}, {"Paused"}, timeout)

    @command
    def resume_run(self, timeout: float = 30.0) -> dict:
        """Resume the current Paused run and verify Running or Completed.

        Caller must authorize resumed motion and verify physical readiness.
        Does not bypass door/recovery conditions or acknowledge warning dialogs.
        Dispatches Resume run once, never automatically retries.

        Args:
            timeout: Finite non-negative seconds for verification; defaults to 30.

        Returns:
            dict: Fresh get_run_status fields after Running or rapid Completed.

        Raises:
            ValueError: timeout is invalid.
            RuntimeError: The run is not Paused, controls/interlocks block resume,
                a confirmation is pending, identity changes, or the run fails.
            TimeoutError: Expected status is not observed; inspect before retrying.
        """
        return self._change_run_state("Resume run", {"Paused"}, {"Running", "Completed"}, timeout)

    @command
    def cancel_run(self, timeout: float = 30.0) -> dict:
        """Cancel the current nonterminal run and verify Canceled on the same run.

        Invoking this command authorizes Cancel run and the recognized standard
        Yes, cancel run confirmation. The OT-2 may drop attached tips and home;
        active modules may retain their states. Caller must verify safe clearance
        and authorization. This is not an emergency-stop or module-deactivation
        command. Unknown warnings are never accepted and input is never retried.

        Args:
            timeout: Finite non-negative seconds for verification; defaults to 30.

        Returns:
            dict: Fresh get_run_status fields after observing Canceled. This status
                does not independently prove all cleanup or module activity ended.

        Raises:
            ValueError: timeout is invalid.
            RuntimeError: Cancel is unavailable, a prior/unknown confirmation exists,
                run identity changes, or another terminal state is observed.
            TimeoutError: Canceled is not observed; inspect before retrying.
        """
        return self._change_run_state("Cancel run", {"Not started", "Running", "Paused",
                                      "Paused - door open", "Awaiting recovery"}, {"Canceled"}, timeout)

    def _inventory_tree(
        self, tab: str, elements: list[dict]
    ) -> tuple[int, dict[int | None, list[dict]]]:
        """Resolve the inventory page heading, excluding sidebar link headings."""
        by_index = {e["element_index"]: e for e in elements}
        headings = [e for e in elements if e.get("role") == "heading" and e.get("label") == tab
                    and by_index.get(e.get("parent_index"), {}).get("role") != "link"]
        if not headings:
            raise ElementNotFoundError(f"{tab} inventory page is not yet open")
        if len(headings) != 1:
            raise RuntimeError(f"Ambiguous {tab} inventory page")
        self._validate_element_position(headings[0], f"{tab} inventory page")
        return headings[0]["parent_index"], self._children_by_parent(elements)

    def _open_inventory(self, tab: str) -> list[dict]:
        """Navigate once, then poll a fresh page heading for up to ten seconds."""
        self.click_element(tab, role="link")
        deadline = time.monotonic() + 10.0
        while True:
            elements = self._capture_elements()
            try:
                self._inventory_tree(tab, elements)
                return elements
            except ElementNotFoundError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out opening the {tab} inventory")
                time.sleep(0.2)

    def _expand_device_groups(self, elements: list[dict]) -> list[dict]:
        """Expand each incomplete group once and wait for its advertised cards."""
        toggled = set()
        deadline = time.monotonic() + 10.0
        while True:
            root, children = self._inventory_tree("Devices", elements)
            groups = {}
            active = None
            for node in children.get(root, []):
                fields = [e.get("label", "") for e in children.get(node["element_index"], [])
                          if e.get("role") == "paragraph"]
                headers = [re.fullmatch(r"(Available|Not Available) \((\d+)\)", text) for text in fields]
                headers = [match for match in headers if match]
                if headers:
                    if len(headers) != 1 or headers[0][1] in groups:
                        raise RuntimeError("Ambiguous device groups")
                    active = headers[0][1]
                    groups[active] = {"count": int(headers[0][2]), "seen": 0, "node": node}
                elif fields and fields[0] in {"OT-2", "Flex"} and active is not None:
                    groups[active]["seen"] += 1
            if not groups:
                raise RuntimeError("Device group counts are unavailable")
            missing = [(name, group) for name, group in groups.items() if group["seen"] < group["count"]]
            if not missing:
                return elements
            clicked = False
            for name, group in missing:
                if name in toggled:
                    continue
                buttons = [e for e in children.get(group["node"]["element_index"], [])
                           if e.get("role") == "push button" and e.get("enabled", True)]
                if len(buttons) != 1:
                    raise RuntimeError("Device group expansion control is ambiguous or unavailable")
                self._validate_element_position(buttons[0], f"expand {name} devices")
                self._run(self._cua.click(element=int(buttons[0]["element_index"])))
                toggled.add(name)
                clicked = True
                break  # recapture before using another snapshot-local index
            if time.monotonic() >= deadline:
                raise TimeoutError("Device group counts did not match captured cards")
            if not clicked:
                time.sleep(0.2)
            elements = self._capture_elements()

    @command
    def list_devices(self) -> dict:
        """Open Devices and read the App's available and unavailable robot cards.

        Expands collapsed device groups once and verifies their advertised counts.
        Does not open robot controls, connect, home, or start any run. Requires
        collected cards to match the App's advertised group counts.

        Returns:
            dict: devices (name, model, available, instruments) and count.
                Availability is the App's classification, not proof of idle state.

        Raises:
            RuntimeError: Device layout is unsupported or group counts mismatch.
            TimeoutError: The Devices inventory does not open within ten seconds.
        """
        elements = self._expand_device_groups(self._open_inventory("Devices"))
        root, children = self._inventory_tree("Devices", elements)
        devices = []
        counts = {}
        group = None
        for node in children.get(root, []):
            if node.get("role") != "section":
                continue
            fields = [e.get("label", "") for e in children.get(node["element_index"], [])
                      if e.get("role") == "paragraph"]
            headers = [re.fullmatch(r"(Available|Not Available) \((\d+)\)", label) for label in fields]
            headers = [match for match in headers if match]
            if headers:
                if len(headers) != 1 or headers[0][1] in counts:
                    raise RuntimeError("Ambiguous device group counts")
                group = headers[0][1]
                counts[group] = int(headers[0][2])
                continue
            if fields and fields[0] in {"OT-2", "Flex"}:
                if group is None or len(fields) < 2:
                    raise RuntimeError("Unsupported device card layout")
                instruments = fields[fields.index("Instruments") + 1:] if "Instruments" in fields else []
                devices.append({"name": fields[1], "model": fields[0],
                                "available": group == "Available", "instruments": instruments})
        if not counts or any(sum(d["available"] == (group == "Available") for d in devices) != total
                             for group, total in counts.items()):
            raise RuntimeError("Device list is incomplete; expand the device groups before listing")
        return {"devices": devices, "count": len(devices)}

    def _labware_dropdown(self, elements: list[dict], label: str) -> tuple[dict, list[dict]]:
        """Find the current value and options of one inventory dropdown."""
        root, children = self._inventory_tree("Labware", elements)
        siblings = children.get(root, [])
        labels = [i for i, e in enumerate(siblings) if e.get("role") == "paragraph" and e.get("label") == label]
        if len(labels) != 1 or labels[0] + 1 >= len(siblings):
            raise RuntimeError(f"Unsupported labware {label} dropdown")
        container = siblings[labels[0] + 1]
        nodes = self._descendants(
            children, container["element_index"],
            "Malformed labware dropdown accessibility tree",
        )
        values = [e for e in nodes if e.get("role") == "paragraph" and e.get("label")]
        if not values:
            raise RuntimeError(f"Labware {label} value is unavailable")
        return values[0], [e for e in nodes if e.get("role") == "push button"]

    def _select_labware_dropdown(self, elements: list[dict], label: str, target: str) -> list[dict]:
        """Select one GUI dropdown option and verify a fresh selected value."""
        value, options = self._labware_dropdown(elements, label)
        if value["label"] == target and not options:
            return elements
        if not options:
            self._validate_element_position(value, f"labware {label}")
            self._run(self._cua.click(element=int(value["element_index"])))
        self.wait_for_element(target, role="push button", timeout=10.0)
        self.click_element(target, role="push button")
        deadline = time.monotonic() + 10.0
        while True:
            elements = self._capture_elements()
            value, options = self._labware_dropdown(elements, label)
            if value["label"] == target and not options:
                return elements
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Labware {label} selection was not verified")
            time.sleep(0.2)

    @command
    def list_labware(self, category: str = "All", sort_by: str = "Alphabetical") -> dict:
        """Open Labware, set GUI category/sort, and read the resulting cards.

        Both options accept case-insensitive GUI labels, without fuzzy matching.
        Preserves the GUI's order and duplicate definitions. Includes offscreen
        AX cards and requires the library footer to reject truncated captures.
        Does not import, delete, or change any labware definition.

        Args:
            category: All (default), Adapter, Aluminum Block, Custom Labware, Lid,
                Reservoir, Tip Rack, Tube Rack, or Well Plate.
            sort_by: Alphabetical (default) or Reverse alphabetical.

        Returns:
            dict: labware (name, category, api_name), count, selected category,
                and sort_by. This is the App library, not physical deck occupancy.

        Raises:
            ValueError: A category/sort label is unsupported or not a string.
            RuntimeError: The dropdown/card layout is unsupported or the full
                library footer is absent.
            TimeoutError: Navigation or option verification exceeds ten seconds.
        """
        categories = {label.casefold(): label for label in
                      ("All", "Adapter", "Aluminum Block", "Custom Labware", "Lid",
                       "Reservoir", "Tip Rack", "Tube Rack", "Well Plate")}
        sorts = {label.casefold(): label for label in ("Alphabetical", "Reverse alphabetical")}
        if not isinstance(category, str) or category.casefold() not in categories:
            raise ValueError("category must match a supported GUI category label")
        if not isinstance(sort_by, str) or sort_by.casefold() not in sorts:
            raise ValueError("sort_by must be Alphabetical or Reverse alphabetical")
        category, sort_by = categories[category.casefold()], sorts[sort_by.casefold()]
        elements = self._open_inventory("Labware")
        elements = self._select_labware_dropdown(elements, "Category", category)
        elements = self._select_labware_dropdown(elements, "Sort by", sort_by)
        root, children = self._inventory_tree("Labware", elements)
        siblings = children.get(root, [])
        if not any(e.get("label") == "Create a new labware definition" for e in siblings):
            raise RuntimeError("Labware library capture is incomplete or unsupported")
        labware = []
        for card in siblings:
            if card.get("role") != "link":
                continue
            fields = children.get(card["element_index"], [])
            if not any(e.get("role") == "heading" and e.get("label") == "API NAME" for e in fields):
                if "API NAME" in card.get("label", ""):
                    raise RuntimeError("Labware card accessibility data is truncated")
                continue
            names = [e.get("label", "") for e in fields if e.get("role") == "heading" and e.get("label") != "API NAME"]
            paragraphs = [e.get("label", "") for e in fields if e.get("role") == "paragraph"]
            if len(names) != 1 or len(paragraphs) != 2 or not all([names[0], *paragraphs]):
                raise RuntimeError("Unsupported labware card layout")
            labware.append({"name": names[0], "category": paragraphs[0], "api_name": paragraphs[1]})
        return {"labware": labware, "count": len(labware), "category": category, "sort_by": sort_by}

    # ── Read-only GUI inspection commands ──────────────────────────────────
    # Generic actions remain inherited from GuiDriver for internal use only.

    @command
    def capture_screenshot(self, include_elements: bool = False) -> dict:
        """Capture a PNG and a copied context for coordinate clicks.

        Capturing foregrounds the app and invalidates earlier capture IDs.

        Args:
            include_elements: Include accessibility elements from the same capture.
                Defaults to False.

        Returns:
            dict: image_b64 and capture. capture contains capture_id, pid, window_id,
            bounds, width, and height, or is None when coordinate input is unavailable.
            When include_elements=True, also includes a copied elements list.

        Raises:
            TypeError: include_elements is not a bool.
            RuntimeError: Capture fails, returns no image, or cannot provide requested elements.
        """
        return super().capture_screenshot(include_elements=include_elements)
