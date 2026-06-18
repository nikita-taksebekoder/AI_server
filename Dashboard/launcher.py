#!/usr/bin/env python3
"""
AI Server Dashboard Launcher v3.0 — Source-Linked
===================================================
Запускает backend.py и frontend/ напрямую из source-папки,
указанной в config.json рядом с launcher.py / .exe.

Правишь код в source-папке → перезапускаешь .exe → работает новая версия.
Никакого копирования, никаких пересборок exe.

Перенос папки: поменяй source_dir в config.json → перезапусти .exe.
"""
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ─── Пути ────────────────────────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

CONFIG_FILE = APP_DIR / "config.json"

def load_source_dir() -> Path:
    """Читает config.json и возвращает source_dir. При отсутствии — APP_DIR."""
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            raw = cfg.get("source_dir", "")
            if raw:
                p = Path(raw)
                if p.is_dir():
                    return p
                log.warning("source_dir from config does not exist: %s — falling back to APP_DIR", raw)
        except Exception as exc:
            log.warning("Failed to read config.json: %s — falling back to APP_DIR", exc)
    return APP_DIR

SOURCE_DIR = load_source_dir()

LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "launcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("launcher")

AI_SERVER_BASE = Path(r"C:\Users\Forestsnow\workspace\AI_server")

# ─── Серверы для автозапуска ─────────────────────────────────────────────────

SERVERS = [
    ("QWEN",     AI_SERVER_BASE / "QWEN"     / "QwenServerLauncher.exe",     3264),
    ("DEEPSEEK", AI_SERVER_BASE / "DEEPSEEK" / "DeepseekServerLauncher.exe", 9655),
    ("ROUTER",   AI_SERVER_BASE / "ROUTER"   / "RouterServerLauncher.exe",   3270),
    ("KIMI",     AI_SERVER_BASE / "KIMI"     / "kimi-launcher.exe",         3265),
]

# ─── Утилиты ─────────────────────────────────────────────────────────────────

def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_python() -> str:
    """Находит python.exe для запуска backend."""
    # 1. Если лаунчер упакован — ищем python рядом
    if getattr(sys, "frozen", False):
        for name in ("python.exe", "pythonw.exe"):
            local = APP_DIR / name
            if local.exists():
                return str(local)

    # 2. Hermes venv
    hermes_python = Path(
        r"C:\Users\Forestsnow\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
    )
    if hermes_python.exists():
        return str(hermes_python)

    # 3. PATH
    for cmd in ("python3", "python", "py"):
        try:
            r = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return cmd
        except Exception:
            pass

    raise RuntimeError("Python not found! Install Python or check PATH.")


# ─── Автозапуск AI-серверов ──────────────────────────────────────────────────

def autostart_servers():
    print("\n=== Auto-starting AI servers ===")
    for name, launcher_path, port in SERVERS:
        if port and is_port_open("127.0.0.1", port):
            print(f"  [OK] {name}: already running (port {port})")
            continue
        if not launcher_path.exists():
            print(f"  [WARN] {name}: launcher not found at {launcher_path}")
            log.warning("%s launcher missing: %s", name, launcher_path)
            continue
        try:
            subprocess.Popen(
                [str(launcher_path)],
                cwd=str(launcher_path.parent),
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                ),
            )
            print(f"  [START] {name}: launched {launcher_path}")
            log.info("Launched %s via %s", name, launcher_path)
        except Exception as e:
            print(f"  [ERR] {name}: {e}")
            log.exception("Failed to launch %s", name)
    print("=== Done ===\n")


# ─── Запуск backend ───────────────────────────────────────────────────────────

def start_backend() -> subprocess.Popen:
    """
    Запускает backend.py из SOURCE_DIR как отдельный процесс.
    backend.py сам найдёт frontend/ рядом с собой.
    """
    python_exe = find_python()
    backend_py = SOURCE_DIR / "backend.py"

    if not backend_py.exists():
        raise FileNotFoundError(
            f"backend.py not found at {backend_py}\n"
            f"Check source_dir in config.json (currently: {SOURCE_DIR})"
        )

    log.info("Starting backend: %s %s", python_exe, backend_py)
    log.info("Source dir: %s", SOURCE_DIR)

    proc = subprocess.Popen(
        [python_exe, str(backend_py)],
        cwd=str(SOURCE_DIR),
        creationflags=(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        ),
    )
    log.info("Backend started with PID %d", proc.pid)
    return proc


def wait_for_backend(timeout: int = 30) -> bool:
    for _ in range(timeout):
        if is_port_open("127.0.0.1", 8000, timeout=0.5):
            return True
        time.sleep(1)
    return False


# ─── Трей ─────────────────────────────────────────────────────────────────────

def create_icon() -> str | None:
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 62, 62], fill=(13, 17, 23, 255), outline=(88, 166, 255, 255), width=2)
        draw.ellipse([12, 28, 20, 36], fill=(63, 185, 80, 255))
        draw.ellipse([28, 28, 36, 36], fill=(88, 166, 255, 255))
        draw.ellipse([44, 28, 52, 36], fill=(210, 153, 34, 255))
        icon_dir = APP_DIR / "assets"
        icon_dir.mkdir(exist_ok=True)
        icon_path = icon_dir / "icon.ico"
        img.save(icon_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        return str(icon_path)
    except ImportError:
        return None


def setup_tray(icon_path: str):
    try:
        import pystray
        from PIL import Image
        import requests

        def open_dashboard(icon, item):
            webbrowser.open("http://127.0.0.1:8000")

        def start_all(icon, item):
            autostart_servers()

        def stop_all(icon, item):
            for name, _, port in SERVERS:
                try:
                    requests.post(f"http://127.0.0.1:8000/api/servers/{name}/stop", timeout=2)
                except Exception:
                    pass

        def restart_backend(icon, item):
            try:
                requests.post("http://127.0.0.1:8000/api/restart", timeout=2)
            except Exception:
                pass

        def exit_app(icon, item):
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Открыть дашборд", open_dashboard),
            pystray.MenuItem("Запустить все серверы", start_all),
            pystray.MenuItem("Остановить все серверы", stop_all),
            pystray.MenuItem("Перезапуск backend", restart_backend),
            pystray.MenuItem("Выход", exit_app),
        )

        image = Image.open(icon_path)
        icon = pystray.Icon("AI Dashboard", image, "AI Server Dashboard", menu)
        icon.run()

    except ImportError:
        print("[WARN] pystray не установлен. Трей недоступен.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            os._exit(0)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  AI Server Dashboard Launcher v3.0 (Source-Linked)")
    print("=" * 50)
    print(f"  APP_DIR:    {APP_DIR}")
    print(f"  SOURCE_DIR: {SOURCE_DIR}")
    print(f"  CONFIG:     {CONFIG_FILE}")
    print("=" * 50)

    # 1) Автозапуск серверов
    autostart_servers()

    # 2) Запуск backend из source-папки
    backend_proc = start_backend()

    # 3) Ожидание старта
    print("[...] Waiting for backend to start...")
    if wait_for_backend():
        print("[OK] Backend is ready at http://127.0.0.1:8000")
    else:
        print("[WARN] Backend didn't start in time. Check logs.")
        log.error("Backend failed to start within timeout")

    # 4) Открываем браузер
    webbrowser.open("http://127.0.0.1:8000")
    print("[OK] Browser opened")

    # 5) Трей
    icon_path = create_icon()
    if icon_path:
        print(f"[OK] Tray icon: {icon_path}")
        setup_tray(icon_path)
    else:
        print("[WARN] No tray icon (Pillow not installed)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            backend_proc.terminate()
            os._exit(0)


if __name__ == "__main__":
    main()
