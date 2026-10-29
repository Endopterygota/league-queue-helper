from __future__ import annotations

import base64
import json
import os
import queue
import ssl
import subprocess
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox


APP_NAME = "League Queue Helper"
POLL_SECONDS = 1.0


class LeagueClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class LockfileData:
    port: int
    password: str
    protocol: str

    @classmethod
    def read(cls, path: Path) -> "LockfileData":
        try:
            parts = path.read_text(encoding="utf-8").strip().split(":")
            if len(parts) != 5:
                raise ValueError("unexpected lockfile format")
            return cls(port=int(parts[2]), password=parts[3], protocol=parts[4])
        except (OSError, ValueError) as exc:
            raise LeagueClientError(f"Could not read League lockfile: {exc}") from exc


def _strings_in_json(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _strings_in_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings_in_json(child)
    elif isinstance(value, str):
        yield value


def _lockfile_beside(path_text: str) -> Path | None:
    path = Path(path_text.replace("/", os.sep))
    if path.name.lower() == "lockfile" and path.is_file():
        return path

    start = path if path.is_dir() else path.parent
    for folder in (start, *list(start.parents)[:3]):
        candidate = folder / "lockfile"
        if candidate.is_file() and "league" in str(folder).lower():
            return candidate
    return None


def find_lockfile() -> Path:
    override = os.environ.get("LEAGUE_LOCKFILE")
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate

    # The running process is the most reliable way to support custom installs.
    if os.name == "nt":
        command = (
            "Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe'\" | "
            "Select-Object -First 1 -ExpandProperty ExecutablePath"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if result.stdout.strip():
                found = _lockfile_beside(result.stdout.strip())
                if found:
                    return found
        except (OSError, subprocess.SubprocessError):
            pass

    # Riot's install manifest often contains the custom game path.
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    manifest = program_data / "Riot Games" / "RiotClientInstalls.json"
    try:
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        for text in _strings_in_json(manifest_data):
            found = _lockfile_beside(text)
            if found:
                return found
    except (OSError, json.JSONDecodeError):
        pass

    candidates = [Path.cwd() / "lockfile"]
    if os.name == "nt":
        for drive in "CDEFG":
            candidates.append(Path(f"{drive}:\\Riot Games\\League of Legends\\lockfile"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise LeagueClientError(
        "League Client was not found. Open League, sign in, and leave the client running."
    )


class LeagueClient:
    def __init__(self, lockfile: LockfileData):
        token = base64.b64encode(f"riot:{lockfile.password}".encode()).decode()
        self.base_url = f"{lockfile.protocol}://127.0.0.1:{lockfile.port}"
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.ssl_context = ssl._create_unverified_context()

    @classmethod
    def connect(cls) -> "LeagueClient":
        return cls(LockfileData.read(find_lockfile()))

    def request(self, method: str, path: str):
        request = urllib.request.Request(
            self.base_url + path,
            data=b"" if method != "GET" else None,
            headers=self.headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request, context=self.ssl_context, timeout=4
            ) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(details)
                details = payload.get("message") or payload.get("errorCode") or details
            except json.JSONDecodeError:
                pass
            raise LeagueClientError(f"League Client returned {exc.code}: {details}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LeagueClientError(f"Could not talk to League Client: {exc}") from exc

    def phase(self) -> str:
        phase = self.request("GET", "/lol-gameflow/v1/gameflow-phase")
        return phase if isinstance(phase, str) else "Unknown"

    def start_matchmaking(self) -> None:
        self.request("POST", "/lol-lobby/v2/lobby/matchmaking/search")

    def accept_ready_check(self) -> None:
        self.request("POST", "/lol-matchmaking/v1/ready-check/accept")


class QueueHelperApp(tk.Tk):
    BG = "#090d18"
    PANEL = "#111827"
    GOLD = "#c89b3c"
    GOLD_ACTIVE = "#e0b95b"
    TEXT = "#f2e9d0"
    MUTED = "#9ca3af"
    GREEN = "#29c985"
    RED = "#f26b6b"

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("500x440")
        self.minsize(460, 410)
        self.configure(bg=self.BG)

        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.run_id = 0
        self.running = False

        self._build_ui()
        self.after(100, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_ui(self):
        header = tk.Frame(self, bg=self.BG)
        header.pack(fill="x", padx=30, pady=(26, 14))

        tk.Label(
            header,
            text="QUEUE HELPER",
            bg=self.BG,
            fg=self.TEXT,
            font=("Segoe UI Semibold", 20),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="One click to search and accept the ready check.",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        card = tk.Frame(self, bg=self.PANEL, highlightthickness=1, highlightbackground="#243047")
        card.pack(fill="both", expand=True, padx=30, pady=(0, 28))

        self.status_dot = tk.Label(card, text="●", bg=self.PANEL, fg=self.MUTED, font=("Segoe UI", 12))
        self.status_dot.pack(pady=(22, 0))
        self.status_label = tk.Label(
            card,
            text="Ready",
            bg=self.PANEL,
            fg=self.TEXT,
            font=("Segoe UI Semibold", 16),
        )
        self.status_label.pack(pady=(3, 3))
        self.detail_label = tk.Label(
            card,
            text="Open League and prepare a lobby, then press Play.",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Segoe UI", 9),
            wraplength=390,
        )
        self.detail_label.pack(pady=(0, 18))

        self.play_button = tk.Button(
            card,
            text="▶  PLAY",
            command=self._start,
            bg=self.GOLD,
            activebackground=self.GOLD_ACTIVE,
            fg="#09111d",
            activeforeground="#09111d",
            disabledforeground="#536071",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 13),
            padx=34,
            pady=12,
            borderwidth=0,
        )
        self.play_button.pack()

        self.stop_button = tk.Button(
            card,
            text="STOP & RESET",
            command=self._stop,
            state="disabled",
            bg=self.PANEL,
            activebackground="#1b2638",
            fg=self.MUTED,
            activeforeground=self.TEXT,
            disabledforeground="#465063",
            relief="flat",
            cursor="hand2",
            font=("Segoe UI Semibold", 9),
            pady=8,
            borderwidth=0,
        )
        self.stop_button.pack(pady=(8, 15))

        tk.Frame(card, height=1, bg="#243047").pack(fill="x", padx=28)
        tk.Label(
            card,
            text="FLOW",
            bg=self.PANEL,
            fg="#68758a",
            font=("Segoe UI Semibold", 8),
        ).pack(pady=(15, 7))
        self.flow_label = tk.Label(
            card,
            text="Find Match   →   Wait   →   Accept   →   Reset",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Segoe UI", 10),
        )
        self.flow_label.pack(pady=(0, 18))

    def _set_status(self, title: str, detail: str, color: str):
        self.status_label.configure(text=title)
        self.detail_label.configure(text=detail)
        self.status_dot.configure(fg=color)

    def _start(self):
        if self.running:
            return
        self.running = True
        self.run_id += 1
        current_run = self.run_id
        self.stop_event = threading.Event()
        self.play_button.configure(state="disabled", bg="#374151")
        self.stop_button.configure(state="normal")
        self._set_status("Connecting…", "Looking for the running League Client.", self.GOLD)

        threading.Thread(
            target=self._automation_worker,
            args=(current_run, self.stop_event),
            daemon=True,
        ).start()

    def _emit(self, run_id: int, kind: str, *payload):
        self.events.put((run_id, kind, payload))

    def _automation_worker(self, run_id: int, stop: threading.Event):
        try:
            client = LeagueClient.connect()
            phase = client.phase()

            if phase == "Lobby":
                self._emit(run_id, "status", "Starting search…", "Pressing Find Match.", self.GOLD)
                client.start_matchmaking()
            elif phase == "Matchmaking":
                self._emit(run_id, "status", "Searching…", "A search is already active.", self.GOLD)
            elif phase == "ReadyCheck":
                self._emit(run_id, "status", "Match found!", "Accepting the ready check.", self.GREEN)
                client.accept_ready_check()
                self._emit(run_id, "accepted")
                return
            else:
                raise LeagueClientError(
                    f"League is in '{phase}'. Create a lobby and select your queue/roles first."
                )

            self._emit(run_id, "status", "Searching…", "Waiting for a match. You can stop at any time.", self.GOLD)
            while not stop.wait(POLL_SECONDS):
                phase = client.phase()
                if phase == "ReadyCheck":
                    self._emit(run_id, "status", "Match found!", "Accepting the ready check.", self.GREEN)
                    client.accept_ready_check()
                    self._emit(run_id, "accepted")
                    return
                if phase not in {"Matchmaking", "Lobby"}:
                    raise LeagueClientError(f"Search ended while League was in '{phase}'.")

            self._emit(run_id, "stopped")
        except LeagueClientError as exc:
            self._emit(run_id, "error", str(exc))
        except Exception as exc:
            self._emit(run_id, "error", f"Unexpected error: {exc}")

    def _stop(self):
        if not self.running:
            return
        self.stop_event.set()
        self.run_id += 1  # Ignore any late events from the old worker.
        self._reset("Stopped", "Automation stopped and reset.", self.MUTED)

    def _reset(self, title="Ready", detail="Open League and prepare a lobby, then press Play.", color=None):
        self.running = False
        self.play_button.configure(state="normal", bg=self.GOLD)
        self.stop_button.configure(state="disabled")
        self._set_status(title, detail, color or self.MUTED)

    def _drain_events(self):
        try:
            while True:
                run_id, kind, payload = self.events.get_nowait()
                if run_id != self.run_id:
                    continue
                if kind == "status":
                    self._set_status(*payload)
                elif kind == "accepted":
                    self._reset(
                        "Accepted — ready again",
                        "The match was accepted. Press Play for another queue later.",
                        self.GREEN,
                    )
                elif kind == "stopped":
                    self._reset("Stopped", "Automation stopped and reset.", self.MUTED)
                elif kind == "error":
                    self._reset("Couldn’t continue", payload[0], self.RED)
                    messagebox.showerror(APP_NAME, payload[0], parent=self)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _close(self):
        self.stop_event.set()
        self.destroy()


if __name__ == "__main__":
    QueueHelperApp().mainloop()
