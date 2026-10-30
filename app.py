"""Interface de rushgrab."""
import json
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import engine

# Le rendu par défaut dépend d'une police qui ne se charge pas sur tous les PC
ctk.DrawEngine.preferred_drawing_method = "polygon_shapes"

SETTINGS_FILE = engine.APP_DIR / "settings.json"
QUALITIES = {"2160p (4K)": 2160, "1440p": 1440, "1080p": 1080, "720p": 720, "480p": 480}
DEFAULTS = {"mode": "MP4", "quality": "1080p", "folder": str(Path.home() / "Downloads")}

BG = "#000000"
FIELD = "#191919"
FIELD_HOVER = "#2a2a2a"
TEXT = "#e1e1e1"
MUTED = "#8a8a8a"
ERROR = "#ff6b6b"


def resource(relative: str) -> str:
    return str(Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / relative)


def load_settings() -> dict:
    try:
        return DEFAULTS | json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(DEFAULTS)


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        self.title("rushgrab")
        self.geometry("560x400")
        self.resizable(False, False)
        self.iconbitmap(resource("assets/icon.ico"))
        self.settings = load_settings()
        self.events: queue.Queue = queue.Queue()
        self.job: engine.Download | None = None
        self.ready = False
        self.last_file: Path | None = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._poll)
        self._prepare()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        body = ctk.CTkFrame(self, fg_color=BG)
        body.grid(row=0, column=0, sticky="ew", padx=28, pady=24)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text="rushgrab", text_color=TEXT,
                     font=ctk.CTkFont(size=26, weight="bold")).grid(row=0, column=0, sticky="w")

        url_row = ctk.CTkFrame(body, fg_color=BG)
        url_row.grid(row=1, column=0, sticky="ew", pady=(16, 10))
        url_row.grid_columnconfigure(0, weight=1)
        self.url = ctk.CTkEntry(url_row, height=44, placeholder_text="colle le lien ici",
                                fg_color=FIELD, border_width=0, text_color=TEXT)
        self.url.grid(row=0, column=0, sticky="ew")
        self.url.bind("<Return>", lambda _: self._on_main_button())
        self._button(url_row, "coller", self._paste).grid(row=0, column=1, padx=(8, 0))

        options = ctk.CTkFrame(body, fg_color=BG)
        options.grid(row=2, column=0, sticky="ew")
        self.mode_buttons = {}
        for column, mode in enumerate(("MP4", "MP3")):
            button = self._button(options, mode, lambda m=mode: self._set_mode(m))
            button.grid(row=0, column=column, padx=(0, 8))
            self.mode_buttons[mode] = button
        self.quality = ctk.CTkOptionMenu(
            options, values=list(QUALITIES), height=36, command=lambda _: self._on_option(),
            fg_color=FIELD, button_color=FIELD, button_hover_color=FIELD_HOVER,
            dropdown_fg_color=FIELD, dropdown_hover_color=FIELD_HOVER, text_color=TEXT,
        )
        self.quality.set(self.settings["quality"])
        self.quality.grid(row=0, column=2)
        self.hint = ctk.CTkLabel(body, text="", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.hint.grid(row=3, column=0, sticky="w", pady=(4, 0))

        folder_row = ctk.CTkFrame(body, fg_color=BG)
        folder_row.grid(row=4, column=0, sticky="ew", pady=(10, 14))
        folder_row.grid_columnconfigure(0, weight=1)
        self.folder = ctk.CTkLabel(folder_row, text="", text_color=MUTED, anchor="w")
        self.folder.grid(row=0, column=0, sticky="ew")
        self._button(folder_row, "changer", self._choose_folder).grid(row=0, column=1, padx=(8, 0))

        self.main_button = ctk.CTkButton(
            body, text="télécharger", height=44, command=self._on_main_button,
            fg_color=TEXT, hover_color="#ffffff", text_color="#000000",
            text_color_disabled="#555555", font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.main_button.grid(row=5, column=0, sticky="ew")

        self.bar = ctk.CTkProgressBar(body, height=6, fg_color=FIELD, progress_color=TEXT)
        self.bar.set(0)
        self.bar.grid(row=6, column=0, sticky="ew", pady=(14, 6))

        status_row = ctk.CTkFrame(body, fg_color=BG)
        status_row.grid(row=7, column=0, sticky="ew")
        status_row.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(status_row, text="", text_color=MUTED, anchor="w",
                                   justify="left", wraplength=500)
        self.status.grid(row=0, column=0, sticky="ew")
        self.open_button = self._button(status_row, "ouvrir", self._open_file)

        self._on_option()
        self._show_folder()

    def _button(self, parent, text: str, command) -> ctk.CTkButton:
        return ctk.CTkButton(parent, text=text, width=76, height=36, command=command,
                             fg_color=FIELD, hover_color=FIELD_HOVER, text_color=TEXT)

    def _set_mode(self, mode: str) -> None:
        self.settings["mode"] = mode
        self._on_option()

    def _on_option(self) -> None:
        mp4 = self.settings["mode"] == "MP4"
        for mode, button in self.mode_buttons.items():
            selected = mode == self.settings["mode"]
            button.configure(fg_color=TEXT if selected else FIELD,
                             hover_color="#ffffff" if selected else FIELD_HOVER,
                             text_color="#000000" if selected else TEXT)
        self.quality.configure(state="normal" if mp4 else "disabled")
        if not mp4:
            self.hint.configure(text="MP3 320 kbps, débit constant")
        elif QUALITIES[self.quality.get()] > 1080:
            self.hint.configure(text="H.264 + AAC. Au-delà de 1080p la conversion prend du temps")
        else:
            self.hint.configure(text="H.264 + AAC, prêt pour Premiere et After Effects")
        self.settings["quality"] = self.quality.get()
        self._save_settings()

    def _save_settings(self) -> None:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")

    def _show_folder(self) -> None:
        folder = self.settings["folder"]
        self.folder.configure(text=folder if len(folder) <= 58 else "…" + folder[-57:])

    def _paste(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        self.url.delete(0, "end")
        self.url.insert(0, text)

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.settings["folder"])
        if folder:
            self.settings["folder"] = str(Path(folder))
            self._save_settings()
            self._show_folder()

    def _prepare(self) -> None:
        self.main_button.configure(state="disabled", text="préparation…")
        threading.Thread(target=self._prepare_worker, daemon=True).start()

    def _prepare_worker(self) -> None:
        try:
            engine.ensure_tools(self._post_progress)
            self.events.put(("ready",))
        except Exception as exc:
            self.events.put(("prepare_error", f"Installation impossible : {exc}"))

    def _on_main_button(self) -> None:
        if self.job:
            self.main_button.configure(state="disabled", text="annulation…")
            self.job.cancel()
        elif not self.ready:
            if self.main_button.cget("state") == "normal":
                self._prepare()
        else:
            self._start()

    def _start(self) -> None:
        url = self.url.get().strip()
        if not url.lower().startswith(("http://", "https://")):
            self._set_status("Colle d'abord un lien commençant par https://", ERROR)
            return
        self.open_button.grid_remove()
        self.main_button.configure(text="annuler")
        self.job = engine.Download(url, self.settings["mode"].lower(), QUALITIES[self.quality.get()],
                                   Path(self.settings["folder"]), self._post_progress)
        threading.Thread(target=self._download_worker, args=(self.job,), daemon=True).start()

    def _download_worker(self, job: engine.Download) -> None:
        try:
            self.events.put(("done", job.run()))
        except engine.Cancelled:
            self.events.put(("cancelled",))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _post_progress(self, fraction, text: str) -> None:
        self.events.put(("progress", fraction, text))

    def _poll(self) -> None:
        while True:
            try:
                event, *args = self.events.get_nowait()
            except queue.Empty:
                break
            getattr(self, f"_on_{event}")(*args)
        self.after(100, self._poll)

    def _on_progress(self, fraction, text: str) -> None:
        if fraction is None:
            if self.bar.cget("mode") != "indeterminate":
                self.bar.configure(mode="indeterminate")
                self.bar.start()
        else:
            if self.bar.cget("mode") != "determinate":
                self.bar.stop()
                self.bar.configure(mode="determinate")
            self.bar.set(fraction)
        self._set_status(text)

    def _reset_bar(self, value: float) -> None:
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.bar.set(value)

    def _set_status(self, text: str, color: str = MUTED) -> None:
        self.status.configure(text=text, text_color=color)

    def _finish_job(self) -> None:
        self.job = None
        self.main_button.configure(state="normal", text="télécharger")

    def _on_ready(self) -> None:
        self.ready = True
        self._reset_bar(0)
        self._set_status("")
        self.main_button.configure(state="normal", text="télécharger")

    def _on_prepare_error(self, message: str) -> None:
        self._reset_bar(0)
        self._set_status(message, ERROR)
        self.main_button.configure(state="normal", text="réessayer")

    def _on_done(self, path: Path) -> None:
        self._finish_job()
        self._reset_bar(1)
        self.last_file = path
        self.url.delete(0, "end")
        self._set_status(f"Terminé : {path.name}", TEXT)
        self.open_button.grid(row=0, column=1, padx=(8, 0))

    def _on_cancelled(self) -> None:
        self._finish_job()
        self._reset_bar(0)
        self._set_status("Téléchargement annulé.")

    def _on_error(self, message: str) -> None:
        self._finish_job()
        self._reset_bar(0)
        self._set_status(message, ERROR)

    def _open_file(self) -> None:
        if self.last_file:
            subprocess.Popen(f'explorer /select,"{self.last_file}"')

    def _close(self) -> None:
        if self.job:
            self.job.cancel()
        self.destroy()


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    App().mainloop()
