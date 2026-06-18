import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_PORT = 3270
DEFAULT_HOST = "127.0.0.1"
MAX_RESTARTS = 10          # max restarts within window
RESTART_WINDOW_SEC = 300   # 5-minute window for restart counting
RESTART_COOLDOWN_SEC = 30  # wait between restarts


def exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(host: str, port: int, seconds: int = 60) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_is_open(host, port):
            return True
        time.sleep(0.5)
    return False


def kill_existing(host: str, port: int) -> None:
    """Kill any existing process listening on the port (Windows)."""
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                print(f"Killing existing process PID {pid} on port {port}")
                subprocess.run(["taskkill", "/F", "/PID", pid],
                             capture_output=True, timeout=5)
                time.sleep(1)
                return
    except Exception as e:
        print(f"Warning: could not kill existing process: {e}")


def start_server_once(host: str, port: int) -> subprocess.Popen:
    root = exe_dir()
    server = root / "server.js"
    config = root / "config.json"
    package_json = root / "package.json"

    if not server.exists():
        raise FileNotFoundError(f"Cannot find server.js next to launcher: {server}")
    if not config.exists():
        raise FileNotFoundError(f"Cannot find config.json next to launcher: {config}")
    if not package_json.exists():
        raise FileNotFoundError(f"Cannot find package.json next to launcher: {package_json}")

    env = os.environ.copy()
    env.setdefault("NON_INTERACTIVE", "1")
    env.setdefault("SKIP_ACCOUNT_MENU", "1")

    out_log = root / "router.out.log"
    err_log = root / "router.err.log"

    # Rotate logs if too large (>5 MB)
    for log_file in [out_log, err_log]:
        if log_file.exists() and log_file.stat().st_size > 5 * 1024 * 1024:
            backup = log_file.with_suffix(".log.bak")
            try:
                log_file.rename(backup)
            except OSError:
                pass

    out = open(out_log, "a", encoding="utf-8")
    err = open(err_log, "a", encoding="utf-8")

    proc = subprocess.Popen(
        ["node", "server.js"],
        cwd=str(root),
        env=env,
        stdout=out,
        stderr=err,
        stdin=subprocess.DEVNULL,
        creationflags=(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        ),
    )
    return proc


def run_with_restart(host: str, port: int) -> None:
    """Start the server with automatic restart on crash."""
    restart_timestamps = []

    # Kill any existing instance first
    if port_is_open(host, port):
        print(f"Port {port} is already in use, cleaning up…")
        kill_existing(host, port)

    while True:
        # Clean old restart timestamps outside the window
        now = time.time()
        restart_timestamps = [t for t in restart_timestamps if now - t < RESTART_WINDOW_SEC]

        if len(restart_timestamps) >= MAX_RESTARTS:
            print(f"ERROR: Too many restarts ({MAX_RESTARTS}) in {RESTART_WINDOW_SEC}s. Giving up.")
            sys.exit(1)

        print(f"Starting AI Router at http://{host}:{port}/v1 …")

        try:
            proc = start_server_once(host, port)
        except Exception as e:
            print(f"Failed to start: {e}")
            sys.exit(1)

        if wait_for_port(host, port, seconds=30):
            print(f"AI Router started: http://{host}:{port}/v1 (PID: {proc.pid})")
        else:
            print("WARNING: Port didn't open in time, but process is running.")

        # Wait for the process to exit (crash or kill)
        proc.wait()

        exit_code = proc.returncode
        print(f"AI Router exited with code {exit_code}")

        if exit_code == 0:
            print("Clean exit, not restarting.")
            break

        restart_timestamps.append(time.time())
        print(f"Restarting in {RESTART_COOLDOWN_SEC}s … "
              f"({len(restart_timestamps)}/{MAX_RESTARTS} in window)")
        time.sleep(RESTART_COOLDOWN_SEC)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start local AI Router OpenAI-compatible fallback proxy.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-restart", action="store_true", help="Disable auto-restart on crash")
    args = parser.parse_args()

    try:
        if args.no_restart:
            proc = start_server_once(args.host, args.port)
            if wait_for_port(args.host, args.port, seconds=30):
                print(f"AI Router started: http://{args.host}:{args.port}/v1 (PID: {proc.pid})")
            return 0
        else:
            run_with_restart(args.host, args.port)
        return 0
    except Exception as exc:
        print(f"Failed to start AI Router: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
