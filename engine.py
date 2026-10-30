"""Moteur de rushgrab : installe les outils et pilote yt-dlp et ffmpeg."""
import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "rushgrab"
BIN_DIR = APP_DIR / "bin"
TMP_DIR = APP_DIR / "tmp"
LOG_FILE = APP_DIR / "dernier-telechargement.log"

YT_DLP = BIN_DIR / "yt-dlp.exe"
FFMPEG = BIN_DIR / "ffmpeg.exe"
FFPROBE = BIN_DIR / "ffprobe.exe"
DENO = BIN_DIR / "deno.exe"

YT_DLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_URL = (
    "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl-shared.zip"
)
DENO_URL = (
    "https://github.com/denoland/deno/releases/latest/download/"
    "deno-x86_64-pc-windows-msvc.zip"
)

PROGRESS_MARK = "[rg-progress]"
FILE_MARK = "[rg-file]"
PROGRESS_TEMPLATE = (
    f"download:{PROGRESS_MARK}%(progress.downloaded_bytes)s|%(progress.total_bytes)s"
    "|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s"
)

ERROR_HINTS = [
    ("sign in to confirm your age", "Cette vidéo est soumise à une limite d'âge."),
    ("sign in to confirm", "YouTube bloque temporairement ce téléchargement (anti-bot)."),
    ("private video", "Cette vidéo est privée."),
    ("video unavailable", "Cette vidéo n'est pas disponible."),
    ("video is unavailable", "Cette vidéo n'est pas disponible."),
    ("unsupported url", "Ce lien n'est pas pris en charge."),
    ("is not a valid url", "Ce lien n'est pas valide."),
    ("http error 404", "Cette page n'existe pas."),
]

# fraction de 0 à 1, ou None quand l'avancement est inconnu
OnProgress = Callable[[Optional[float], str], None]


class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


def fetch(url: str, dest: Path, label: str, on_progress: OnProgress) -> None:
    part = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=30) as response, open(part, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            on_progress(done / total if total else None, f"{label} : {done >> 20} / {total >> 20} Mo")
    part.replace(dest)


def install_zip(url: str, label: str, on_progress: OnProgress) -> None:
    archive = BIN_DIR / "download.zip"
    fetch(url, archive, label, on_progress)
    on_progress(None, f"Installation de {label}…")
    with zipfile.ZipFile(archive) as zf:
        members = [m for m in zf.infolist() if m.filename.lower().endswith((".exe", ".dll"))]
        # Les .exe en dernier : s'ils existent, l'installation est allée au bout
        for member in sorted(members, key=lambda m: m.filename.lower().endswith(".exe")):
            with zf.open(member) as src, open(BIN_DIR / Path(member.filename).name, "wb") as dst:
                shutil.copyfileobj(src, dst)
    archive.unlink()


def ensure_tools(on_progress: OnProgress) -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if YT_DLP.exists():
        on_progress(None, "Recherche de mises à jour…")
        try:
            subprocess.run(
                [str(YT_DLP), "-U"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            pass
    else:
        fetch(YT_DLP_URL, YT_DLP, "yt-dlp", on_progress)
    if not (FFMPEG.exists() and FFPROBE.exists()):
        install_zip(FFMPEG_URL, "ffmpeg", on_progress)
    if not DENO.exists():
        install_zip(DENO_URL, "deno", on_progress)


def probe(path: Path) -> tuple[Optional[str], Optional[str], float]:
    """Renvoie le codec vidéo, le codec audio et la durée d'un fichier."""
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type,codec_name:format=duration",
         "-of", "json", str(path)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    info = json.loads(result.stdout or "{}")
    codecs = {s.get("codec_type"): s.get("codec_name") for s in info.get("streams", [])}
    return codecs.get("video"), codecs.get("audio"), to_number(info.get("format", {}).get("duration")) or 0


def to_number(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def french(value: float, unit: str) -> str:
    return f"{value:.1f} {unit}".replace(".", ",")


def size_status(label: str, done: float, total: Optional[float], speed, eta) -> str:
    parts = [f"{label} : {french(done / 1e6, 'Mo')}"]
    if total:
        parts[0] += f" / {french(total / 1e6, 'Mo')}"
    if speed:
        parts.append(f"{french(speed / 1e6, 'Mo/s')}")
    if eta:
        parts.append(f"{int(eta)} s")
    return " · ".join(parts)


class Download:
    def __init__(self, url: str, mode: str, height: int, out_dir: Path, on_progress: OnProgress):
        self.url = url
        self.mode = mode
        self.height = height
        self.out_dir = out_dir
        self.on_progress = on_progress
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._log: list[str] = []

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            # yt-dlp.exe lance des sous-processus : il faut tuer tout l'arbre
            subprocess.run(
                ["taskkill", "/PID", str(self._proc.pid), "/T", "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

    def run(self) -> Path:
        shutil.rmtree(TMP_DIR, ignore_errors=True)
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        try:
            path = self._fetch()
            return self._make_editable(path) if self.mode == "mp4" else path
        finally:
            LOG_FILE.write_text("\n".join(self._log), encoding="utf-8")

    def _spawn(self, args: list[str]) -> subprocess.Popen:
        if self._cancelled:
            raise Cancelled()
        self._log.append("> " + " ".join(args))
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return self._proc

    def _ytdlp_args(self) -> list[str]:
        args = [
            str(YT_DLP), "--ignore-config", "--no-playlist", "--newline", "--color", "no_color",
            "--encoding", "utf-8", "--windows-filenames",
            "--ffmpeg-location", str(BIN_DIR),
            "--js-runtimes", f"deno:{DENO}",
            "--progress-template", PROGRESS_TEMPLATE,
            "--no-quiet", "--print", f"after_move:{FILE_MARK}%(filepath)s",
            "-P", f"home:{self.out_dir}", "-P", f"temp:{TMP_DIR}",
        ]
        if self.mode == "mp3":
            # CBR : le MP3 à débit variable peut se désynchroniser dans Premiere
            args += ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "320K",
                     "-o", "%(title).150B.%(ext)s"]
        else:
            args += ["-S", f"hdr:sdr,res:{self.height},vcodec:h264,acodec:aac",
                     "--merge-output-format", "mp4",
                     "-o", "%(title).150B [%(height)sp].%(ext)s"]
        return args + ["--", self.url]

    def _fetch(self) -> Path:
        path = error = None
        streams = 0
        labels = ["Audio"] if self.mode == "mp3" else ["Vidéo", "Audio"]
        self.on_progress(None, "Analyse du lien…")
        proc = self._spawn(self._ytdlp_args())
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith(PROGRESS_MARK):
                done, total, estimate, speed, eta = map(to_number, line[len(PROGRESS_MARK):].split("|"))
                size = total or estimate
                label = labels[min(streams, len(labels)) - 1] if streams else labels[0]
                self.on_progress(done / size if done and size else None,
                                 size_status(label, done or 0, size, speed, eta))
                continue
            self._log.append(line)
            if line.startswith(FILE_MARK):
                path = Path(line[len(FILE_MARK):])
            elif line.startswith("[download] Destination:"):
                streams += 1
            elif line.startswith("[Merger]"):
                self.on_progress(None, "Assemblage de la vidéo et du son…")
            elif line.startswith("[ExtractAudio]"):
                self.on_progress(None, "Conversion en MP3…")
            elif line.startswith("ERROR:"):
                error = line[len("ERROR:"):].strip()
        proc.wait()
        if self._cancelled:
            raise Cancelled()
        if proc.returncode or path is None:
            raise DownloadError(self._explain(error))
        return path

    def _explain(self, error: Optional[str]) -> str:
        for needle, message in ERROR_HINTS:
            if error and needle in error.lower():
                return message
        return error or "Le téléchargement a échoué."

    def _make_editable(self, path: Path) -> Path:
        """Garantit du H.264 + AAC, les seuls codecs lus sans souci par les logiciels de montage."""
        video, audio, duration = probe(path)
        if video in ("h264", None) and audio in ("aac", None):
            return path
        target = TMP_DIR / path.name
        args = [
            str(FFMPEG), "-y", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
            "-i", str(path), "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", *(["copy"] if video == "h264" else
                      ["libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]),
            "-c:a", *(["copy"] if audio == "aac" else ["aac", "-b:a", "192k"]),
            "-movflags", "+faststart", str(target),
        ]
        self.on_progress(0, "Conversion H.264 pour le montage…")
        proc = self._spawn(args)
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                position = to_number(line.split("=", 1)[1])
                if position and duration:
                    fraction = min(position / 1e6 / duration, 1)
                    self.on_progress(fraction, f"Conversion H.264 pour le montage : {fraction:.0%}")
            elif "=" not in line:
                self._log.append(line)
        proc.wait()
        if self._cancelled:
            raise Cancelled()
        if proc.returncode:
            raise DownloadError("La conversion en H.264 a échoué.")
        shutil.move(target, path)
        return path
