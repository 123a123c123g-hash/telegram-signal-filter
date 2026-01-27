from __future__ import annotations

import json
import logging
import os
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.simpledialog import askstring

from tg_client import ChatInfo, TGClient


BASE_DIR = os.path.dirname(__file__)
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


DEFAULT_CONFIG = {
    "api_id": 32834673,
    "api_hash": "7894d2351fc4202e683d7e4f33706cc1",
    "source_chat_id": None,
    "notify_chat_id": 3727425191,
    "min_distance": 1.5,
    "ignore_forwarded": False,
    "enable_graph_screenshot": True,
    "screenshot_timeout_ms": 15000,
    "screenshot_wait_ms": 1500,
    "screenshot_viewport": "1280x720",
    "screenshot_full_page": True,
}


def setup_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("tg-gui")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        formatter = logging.Formatter(log_format)
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(formatter)
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        backup_path = CONFIG_PATH + ".bad"
        try:
            os.replace(CONFIG_PATH, backup_path)
        except OSError:
            pass
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class App:
    def __init__(self, root: tk.Tk, logger: logging.Logger) -> None:
        self.root = root
        self.logger = logger
        self.config = load_config()

        self.client = TGClient(
            api_id=int(self.config["api_id"]),
            api_hash=str(self.config["api_hash"]),
            logger=self.logger,
            screenshot_config=self.config,
        )

        self.chats: list[ChatInfo] = []
        self.chat_map: dict[str, ChatInfo] = {}

        self.source_var = tk.StringVar()
        self.notify_var = tk.StringVar()
        self.min_distance_var = tk.StringVar(value=str(self.config["min_distance"]))
        self.ignore_forwarded_var = tk.BooleanVar(value=bool(self.config["ignore_forwarded"]))
        self.status_var = tk.StringVar(value="Disconnected | Monitoring OFF")

        self._build_ui()

    def _build_ui(self) -> None:
        self.root.title("Telegram Signal Filter")
        self.root.geometry("760x420")

        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        btn_request = ttk.Button(top, text="Request code", command=self.on_request_code)
        btn_login = ttk.Button(top, text="Login", command=self.on_login)
        btn_load = ttk.Button(top, text="Load chats", command=self.on_load_chats)
        btn_start = ttk.Button(top, text="Start monitoring", command=self.on_start)
        btn_stop = ttk.Button(top, text="Stop monitoring", command=self.on_stop)
        btn_request.pack(side="left", padx=4)
        btn_login.pack(side="left", padx=4)
        btn_load.pack(side="left", padx=4)
        btn_start.pack(side="left", padx=4)
        btn_stop.pack(side="left", padx=4)

        form = ttk.Frame(self.root, padding=10)
        form.pack(fill="x")

        ttk.Label(form, text="Source chat:").grid(row=0, column=0, sticky="w")
        self.source_combo = ttk.Combobox(form, textvariable=self.source_var, width=80, state="readonly")
        self.source_combo.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(form, text="Notify chat:").grid(row=1, column=0, sticky="w")
        self.notify_combo = ttk.Combobox(form, textvariable=self.notify_var, width=80, state="readonly")
        self.notify_combo.grid(row=1, column=1, sticky="we", pady=4)

        btn_default_notify = ttk.Button(
            form, text="Use default notify id 3727425191", command=self.on_use_default_notify
        )
        btn_default_notify.grid(row=1, column=2, padx=6)

        ttk.Label(form, text="Min distance:").grid(row=2, column=0, sticky="w")
        self.min_distance_entry = ttk.Entry(form, textvariable=self.min_distance_var, width=12)
        self.min_distance_entry.grid(row=2, column=1, sticky="w", pady=4)

        self.ignore_cb = ttk.Checkbutton(
            form, text="Ignore forwarded", variable=self.ignore_forwarded_var
        )
        self.ignore_cb.grid(row=3, column=1, sticky="w", pady=4)

        form.columnconfigure(1, weight=1)

        status_frame = ttk.Frame(self.root, padding=10)
        status_frame.pack(fill="x")
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor="w")

    def on_login(self) -> None:
        try:
            self.client.connect()
        except Exception as exc:
            messagebox.showerror("Connect error", str(exc))
            return

        phone = askstring(
            "Login", "Enter phone number (with country code):", initialvalue=getattr(self, "_phone_cache", "")
        )
        if not phone:
            return
        code = askstring("Login", "Enter the code you received:")
        if not code:
            return
        password = None
        try:
            self.client.login(phone=phone, code=code, password=None, send_code=False)
        except Exception as exc:
            if "Password" in exc.__class__.__name__ or "SessionPasswordNeededError" in str(exc):
                password = askstring("Login", "Enter 2FA password:", show="*")
                if not password:
                    return
                try:
                    self.client.login(phone=phone, code=code, password=password, send_code=False)
                except Exception as exc2:
                    messagebox.showerror("Login error", str(exc2))
                    return
            else:
                messagebox.showerror("Login error", str(exc))
                return

        self.status_var.set("Connected | Monitoring OFF")
        self.logger.info("Logged in")
        self._phone_cache = phone

    def on_request_code(self) -> None:
        try:
            self.client.connect()
        except Exception as exc:
            messagebox.showerror("Connect error", str(exc))
            return

        phone = askstring(
            "Request code", "Enter phone number (with country code):", initialvalue=getattr(self, "_phone_cache", "")
        )
        if not phone:
            return
        try:
            self.client.request_code(phone=phone)
        except Exception as exc:
            messagebox.showerror("Request code error", str(exc))
            return
        self._phone_cache = phone
        self.status_var.set("Connected | Code requested")

    def on_load_chats(self) -> None:
        try:
            self.client.connect()
            chats = self.client.load_chats()
        except Exception as exc:
            messagebox.showerror("Load chats error", str(exc))
            return

        self.chats = chats
        self.chat_map = {c.display_name(): c for c in chats}
        values = list(self.chat_map.keys())
        self.source_combo["values"] = values
        self.notify_combo["values"] = values

        source_selected = self._find_by_id(self.config.get("source_chat_id"))
        notify_selected = self._find_by_id(self.config.get("notify_chat_id"))
        if source_selected:
            self.source_var.set(source_selected.display_name())
        if notify_selected:
            self.notify_var.set(notify_selected.display_name())

        self.status_var.set("Connected | Chats loaded")

    def _find_by_id(self, chat_id) -> ChatInfo | None:
        for chat in self.chats:
            if chat.chat_id == chat_id:
                return chat
        return None

    def on_use_default_notify(self) -> None:
        chat = self._find_by_id(DEFAULT_CONFIG["notify_chat_id"])
        if chat:
            self.notify_var.set(chat.display_name())
        else:
            self.notify_var.set(str(DEFAULT_CONFIG["notify_chat_id"]))

    def on_start(self) -> None:
        if not self.source_var.get() or not self.notify_var.get():
            messagebox.showwarning("Missing data", "Select source and notify chats.")
            return
        try:
            min_distance = float(self.min_distance_var.get())
        except ValueError:
            messagebox.showwarning("Invalid distance", "Min distance must be a number.")
            return

        source = self.chat_map.get(self.source_var.get())
        notify = self.chat_map.get(self.notify_var.get())
        if source is None or notify is None:
            messagebox.showwarning("Invalid chat", "Please reload chats and select valid items.")
            return

        self.client.start_monitoring(
            source=source,
            notify=notify,
            min_distance=min_distance,
            ignore_forwarded=self.ignore_forwarded_var.get(),
            on_signal=self.on_signal,
        )

        self._save_state(source.chat_id, notify.chat_id, min_distance, self.ignore_forwarded_var.get())
        self.status_var.set(
            f"Connected | Monitoring ON | Source={source.chat_id} Notify={notify.chat_id}"
        )

    def on_stop(self) -> None:
        self.client.stop_monitoring()
        self.status_var.set("Connected | Monitoring OFF")

    def on_signal(self, distance: float) -> None:
        self.status_var.set(f"Connected | Monitoring ON | Last signal: {distance:.3f}%")

    def _save_state(self, source_id: int, notify_id: int, min_distance: float, ignore_forwarded: bool) -> None:
        self.config["source_chat_id"] = source_id
        self.config["notify_chat_id"] = notify_id
        self.config["min_distance"] = min_distance
        self.config["ignore_forwarded"] = ignore_forwarded
        save_config(self.config)


def main() -> None:
    logger = setup_logging()
    root = tk.Tk()
    app = App(root, logger)
    root.protocol("WM_DELETE_WINDOW", root.quit)
    root.mainloop()


if __name__ == "__main__":
    main()
