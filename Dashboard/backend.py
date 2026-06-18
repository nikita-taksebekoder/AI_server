"""
AI Server Dashboard - FastAPI Backend v2.5
Мониторинг и управление AI-серверами (QWEN, DEEPSEEK, ROUTER)
Glassmorphism Edition + Real Token Tracking from Logs + Auth Fix + PID/Uptime Fix
"""

import json
import logging
import os
import re
import subprocess
import sys as _sys
import time
from pathlib import Path
from typing import Optional

# Patterns to redact sensitive data from logs
_SENSITIVE_PATTERNS = [
    (re.compile(r'(sk-[a-zA-Z0-9]{20,})', re.IGNORECASE), '[REDACTED_KEY]'),
    (re.compile(r'(Bearer\s+)([a-zA-Z0-9_\-\.]+)', re.IGNORECASE), r'\1[REDACTED_TOKEN]'),
    (re.compile(r'(api[_-]?key["\s:=]+)([a-zA-Z0-9_\-\.]+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(password["\s:=]+)(\S+)', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(token["\s:=]+)([a-zA-Z0-9_\-\.]+)', re.IGNORECASE), r'\1[REDACTED]'),
]


def sanitize_log_line(line: str) -> str:
    """Redact sensitive data (API keys, tokens, passwords) from log lines."""
    result = line
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result

import psutil
import requests
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

# === Runtime paths and logging ===

if getattr(_sys, "frozen", False):
    # Persistent directory next to AIServerDashboard.exe.
    APP_DIR = Path(_sys.executable).resolve().parent
    # PyInstaller onefile extracts bundled data to sys._MEIPASS.
    BUNDLE_DIR = Path(getattr(_sys, "_MEIPASS", APP_DIR)).resolve()
else:
    APP_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = APP_DIR

LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "dashboard.log"

_log_handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if getattr(_sys, "stderr", None) is not None:
    _log_handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=_log_handlers,
)
log = logging.getLogger("dashboard")

# === Конфигурация ===

BASE_DIR = Path(r"C:\Users\Forestsnow\workspace\AI_server")

FRONTEND_CANDIDATES = [
    APP_DIR / "frontend",       # editable/portable dist layout
    BUNDLE_DIR / "frontend",    # PyInstaller onefile bundled data
    Path.cwd() / "frontend",    # manual cwd fallback
]
FRONTEND_DIR = next(
    (candidate for candidate in FRONTEND_CANDIDATES if (candidate / "index.html").exists()),
    FRONTEND_CANDIDATES[0],
)
log.info(
    "startup paths: frozen=%s app_dir=%s bundle_dir=%s frontend_dir=%s log_file=%s",
    getattr(_sys, "frozen", False), APP_DIR, BUNDLE_DIR, FRONTEND_DIR, LOG_FILE,
)

SERVERS = {
    "QWEN": {
        "name": "Qwen Server",
        "port": 3264,
        "launcher": "QWEN/QwenServerLauncher.exe",
        "server_dir": BASE_DIR / "QWEN",
        "log_out": "qwen-server.out.log",
        "log_err": "qwen-server.err.log",
        "health_endpoint": "/models",
        "health_expect_status": [200, 401],
        "accounts_path": BASE_DIR / "QWEN" / "src" / "Authorization.txt",
    },
    "DEEPSEEK": {
        "name": "DeepSeek Server",
        "port": 9655,
        "launcher": "DEEPSEEK/DeepseekServerLauncher.exe",
        "server_dir": BASE_DIR / "DEEPSEEK",
        "log_out": "deepseek-server.out.log",
        "log_err": "deepseek-server.err.log",
        "health_endpoint": "/models",
        "health_expect_status": [200],
        "accounts_path": BASE_DIR / "DEEPSEEK" / "deepseek-auth.json",
    },
    "ROUTER": {
        "name": "AI Router",
        "port": 3270,
        "launcher": "ROUTER/RouterServerLauncher.exe",
        "server_dir": BASE_DIR / "ROUTER",
        "log_out": "router.out.log",
        "log_err": "router.err.log",
        "health_endpoint": "/models",
        "health_expect_status": [200],
        "config_path": BASE_DIR / "ROUTER" / "config.json",
    },
    "KIMI": {
        "name": "KIMI Server",
        "port": 3265,
        "launcher": "KIMI/kimi-launcher.exe",
        "server_dir": BASE_DIR / "KIMI",
        "log_out": "kimi-server.out.log",
        "log_err": "kimi-server.err.log",
        "health_endpoint": "/health",
        "health_expect_status": [200],
        "config_path": BASE_DIR / "KIMI" / ".env",
        "accounts_path": BASE_DIR / "KIMI" / "auth.json",
    }
}

app = FastAPI(title="AI Server Dashboard", version="2.5.0")

# ---------- Auto‑start auxiliary servers on dashboard launch ----------
@app.on_event("startup")
def start_aux_servers():
    """Launch Qwen, DeepSeek, Router (and others) when the dashboard starts.
    Processes are started hidden (no console window) and are left running.
    If a launcher is missing or fails, we log the error – the dashboard will
    still be available and the log can be inspected via the new /log endpoint.
    """
    import time
    time.sleep(1)  # small delay to let uvicorn fully bind first
    for name, cfg in SERVERS.items():
        launcher = cfg.get("launcher")
        if not launcher:
            continue
        exe_path = BASE_DIR / launcher
        server_dir = cfg.get("server_dir", BASE_DIR)
        port = cfg.get("port", 0)
        # Skip if server is already running (port in use)
        if port and is_port_open("127.0.0.1", port):
            log.info(f"Server {name} already running on port {port}, skipping auto‑start")
            continue
        if not exe_path.exists():
            log.error(f"Launcher for {name} not found: {exe_path}")
            continue
        try:
            # DETACHED_PROCESS | CREATE_NO_WINDOW hides the console window
            creation = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen([str(exe_path)], cwd=str(server_dir), creationflags=creation,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info(f"Auto‑started {name} via {exe_path} (cwd={server_dir})")
        except Exception as e:
            log.error(f"Failed to start {name} ({exe_path}): {e}")


# === CORS Middleware ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Вспомогательные функции ===

def get_router_config() -> dict:
    """Load the router's config.json and return its virtualModels dict.
    Normalizes entries: objects with {contextLength, models: [...]} are flattened
    to plain arrays of candidate objects for backward compatibility."""
    router_cfg_path = SERVERS["ROUTER"]["config_path"]
    try:
        with open(router_cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        raw = cfg.get("virtualModels", {})
        virtual_models = {}
        for name, entry in raw.items():
            if isinstance(entry, list):
                virtual_models[name] = entry
            elif isinstance(entry, dict) and "models" in entry:
                virtual_models[name] = entry["models"]
            else:
                virtual_models[name] = entry
        return virtual_models
    except Exception as e:
        log.error(f"Failed to read router config: {e}")
        raise HTTPException(status_code=500, detail="Could not load router config")

def get_role_usage() -> dict:
    """Return token usage per router role by querying the router's /status endpoint."""
    router_cfg = SERVERS.get("ROUTER", {})
    port = router_cfg.get("port", 3270)
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/status", timeout=3)
        if resp.status_code != 200:
            return {}
        status = resp.json()
    except Exception as e:
        log.error(f"Failed to fetch router /status: {e}")
        return {}

    roles = status.get("roles", {})
    virtual_models = router_cfg.get("virtual_models") or {}
    # If config_path is set, read virtualModels from there to ensure we list all roles
    config_path = router_cfg.get("config_path")
    if config_path and Path(config_path).exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            virtual_models = cfg.get("virtualModels", virtual_models)
        except Exception:
            pass

    result = {}
    for role in (virtual_models or {}).keys():
        role_data = roles.get(role, {}) if isinstance(roles, dict) else {}
        usage = role_data.get("usage", {"prompt": 0, "completion": 0, "total": 0})
        tokens = role_data.get("tokens", usage)
        result[role] = {
            "usage": usage,
            "tokens": tokens,
            "requests": role_data.get("requests", 0),
            "selected": role_data.get("selected"),
            "processing": role_data.get("processing", False),
        }
    return result


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is open."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_pid_by_port(port: int) -> Optional[int]:
    """Find PID of process listening on a given port."""
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port:
                return conn.pid
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return None


def find_launcher_pid(launcher_name: str, port: int = None) -> Optional[int]:
    """Находит PID процесса.
    Сначала пытается найти по порту (node.exe или серверный процесс),
    затем fallback на поиск launcher.exe по имени.
    """
    # Приоритет: поиск по порту (активный серверный процесс)
    if port:
        pid = find_pid_by_port(port)
        if pid:
            return pid
    
    # Fallback: поиск launcher по имени
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == launcher_name.lower():
                return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def get_process_uptime(pid: int) -> Optional[float]:
    """Возвращает uptime процесса в секундах, или None если недоступно."""
    if not pid:
        return None
    try:
        proc = psutil.Process(pid)
        create_time = proc.create_time()
        return time.time() - create_time
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)

def read_log_tail(log_path: Path, lines: int = 20) -> list:
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            return [strip_ansi(line.rstrip()) for line in all_lines[-lines:]]
    except Exception:
        return []


# === Qwen Token Cache ===
_qwen_token_cache: Optional[str] = None
_qwen_token_loaded: bool = False

def get_qwen_token() -> Optional[str]:
    """Load and cache first non-comment JWT token from QWEN Authorization.txt.
    Reads file only once per process lifetime."""
    global _qwen_token_cache, _qwen_token_loaded
    if _qwen_token_loaded:
        return _qwen_token_cache
    
    path = SERVERS["QWEN"]["accounts_path"]
    _qwen_token_loaded = True
    if not path.exists():
        _qwen_token_cache = None
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    _qwen_token_cache = stripped
                    return _qwen_token_cache
    except Exception:
        pass
    _qwen_token_cache = None
    return None


def parse_tokens_from_logs(log_out_path: Path, log_err_path: Path, server_key: str) -> dict:
    """
    Parse token usage from server log files.
    
    Supports:
    - ROUTER: '[Orcestrator] success <provider>:<model> (<N> tokens)'
    - DEEPSEEK: Parse prompt_tokens/completion_tokens/total_tokens from logs
    - QWEN: Parse tokens/usage from logs, fallback to estimate
    
    Returns dict with input_tokens, output_tokens, total_tokens, requests_count, source.
    """
    result = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "requests_count": 0,
        "source": "log_parser",
        "tracking": "partial",
        "details": {},
    }
    
    # Read last 500 lines from both logs for better token capture
    out_lines = read_log_tail(log_out_path, 500) if log_out_path else []
    err_lines = read_log_tail(log_err_path, 500) if log_err_path else []
    all_lines = out_lines + err_lines
    
    if not all_lines:
        result["tracking"] = "not tracked"
        result["source"] = "no_logs"
        return result
    
    # ROUTER-specific parsing: extract token counts from success lines
    if server_key == "ROUTER":
        # New format: [VirtualModel] success openrouter:model-name (123 in / 456 out / 789 total)
        # Fallback: [VirtualModel] success openrouter:model-name (12345 tokens)
        router_pattern = re.compile(r'\[(\w+)\]\s+success\s+(\S+)\s+\((\d+)\s+in\s+/\s+(\d+)\s+out\s+/\s+(\d+)\s+total\)')
        router_pattern_old = re.compile(r'\[(\w+)\]\s+success\s+(\S+)\s+\((\d+)\s+tokens\)')
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        request_count = 0
        model_stats = {}
        by_virtual_model = {}
        
        for line in all_lines:
            match = router_pattern.search(line)
            if match:
                virtual_model = match.group(1)
                model_id = match.group(2)
                in_tok = int(match.group(3))
                out_tok = int(match.group(4))
                tot_tok = int(match.group(5))
                input_tokens += in_tok
                output_tokens += out_tok
                total_tokens += tot_tok
                request_count += 1
                
                if model_id not in model_stats:
                    model_stats[model_id] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "requests": 0}
                model_stats[model_id]["input_tokens"] += in_tok
                model_stats[model_id]["output_tokens"] += out_tok
                model_stats[model_id]["total_tokens"] += tot_tok
                model_stats[model_id]["requests"] += 1
                
                by_virtual_model[virtual_model] = {
                    "selected_model": model_id,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "total_tokens": tot_tok,
                    "requests": (by_virtual_model.get(virtual_model, {}).get("requests", 0) + 1)
                }
            else:
                match_old = router_pattern_old.search(line)
                if match_old:
                    virtual_model = match_old.group(1)
                    model_id = match_old.group(2)
                    tokens = int(match_old.group(3))
                    total_tokens += tokens
                    request_count += 1
                    
                    if model_id not in model_stats:
                        model_stats[model_id] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "requests": 0}
                    model_stats[model_id]["total_tokens"] += tokens
                    model_stats[model_id]["requests"] += 1
                    
                    by_virtual_model[virtual_model] = {
                        "selected_model": model_id,
                        "total_tokens": tokens,
                        "requests": (by_virtual_model.get(virtual_model, {}).get("requests", 0) + 1)
                    }
        
        if request_count > 0:
            result["input_tokens"] = input_tokens
            result["output_tokens"] = output_tokens
            result["total_tokens"] = total_tokens
            result["requests_count"] = request_count
            result["tracking"] = "live"
            result["details"] = {
                "by_model": model_stats,
                "by_virtual_model": by_virtual_model,
                "note": "Token counts from router logs (input/output split)"
            }
        else:
            result["tracking"] = "not tracked"
            result["details"] = {"note": "No successful requests found in recent logs"}
    
    # DEEPSEEK: Parse actual token usage from logs
    elif server_key == "DEEPSEEK":
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        request_count = 0
        
        # Patterns for DeepSeek token logging
        prompt_pattern = re.compile(r'prompt_tokens[":\s]+(\d+)', re.IGNORECASE)
        completion_pattern = re.compile(r'completion_tokens[":\s]+(\d+)', re.IGNORECASE)
        total_pattern = re.compile(r'total_tokens[":\s]+(\d+)', re.IGNORECASE)
        usage_pattern = re.compile(r'usage.*?prompt.*?(\d+).*?completion.*?(\d+)', re.IGNORECASE | re.DOTALL)
        req_pattern = re.compile(r'POST /v1/chat/completions')
        
        for line in all_lines:
            # Count requests
            if req_pattern.search(line):
                request_count += 1
            
            # Try structured usage pattern first
            usage_match = usage_pattern.search(line)
            if usage_match:
                input_tokens += int(usage_match.group(1))
                output_tokens += int(usage_match.group(2))
                continue
            
            # Individual token fields
            prompt_match = prompt_pattern.search(line)
            if prompt_match:
                input_tokens += int(prompt_match.group(1))
            
            completion_match = completion_pattern.search(line)
            if completion_match:
                output_tokens += int(completion_match.group(1))
            
            total_match = total_pattern.search(line)
            if total_match:
                total_tokens += int(total_match.group(1))
        
        # If we got individual tokens but no total, compute it
        if (input_tokens > 0 or output_tokens > 0) and total_tokens == 0:
            total_tokens = input_tokens + output_tokens
        
        if input_tokens > 0 or output_tokens > 0 or total_tokens > 0:
            result["input_tokens"] = input_tokens
            result["output_tokens"] = output_tokens
            result["total_tokens"] = total_tokens
            result["requests_count"] = request_count
            result["tracking"] = "live"
            result["details"] = {
                "note": "Token usage parsed from DeepSeek server logs"
            }
        elif request_count > 0:
            # Fallback: estimate tokens if only requests found
            estimated_total = request_count * 2000
            result["requests_count"] = request_count
            result["total_tokens"] = estimated_total
            result["tracking"] = "estimated"
            result["details"] = {
                "note": f"Requests found but no token data. Estimated ~{estimated_total} tokens ({request_count} req × 2000 avg)"
            }
        else:
            result["tracking"] = "not tracked"
            result["details"] = {"note": "No requests or token data found in recent logs"}
    
    # QWEN: Parse tokens from logs or estimate
    elif server_key == "QWEN":
        request_count = 0
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        
        # Multiple patterns for Qwen request detection
        req_patterns = [
            re.compile(r'Получен OpenAI-совместимый запрос'),
            re.compile(r'Ответ получен успешно'),
            re.compile(r'POST /v1/chat/completions'),
            re.compile(r'processing request', re.IGNORECASE),
            re.compile(r'request received', re.IGNORECASE),
        ]
        
        # Token patterns for Qwen logs
        token_patterns = [
            re.compile(r'tokens?[":\s]+(\d+)', re.IGNORECASE),
            re.compile(r'usage.*?(\d+)', re.IGNORECASE),
            re.compile(r'prompt.*?(\d+).*?completion.*?(\d+)', re.IGNORECASE),
        ]
        
        matched_lines = set()
        for line in all_lines:
            for pattern in req_patterns:
                if pattern.search(line):
                    matched_lines.add(line)
                    break
            
            # Try to extract token info
            for tp in token_patterns:
                tm = tp.search(line)
                if tm:
                    groups = tm.groups()
                    if len(groups) >= 2:
                        input_tokens += int(groups[0])
                        output_tokens += int(groups[1])
                    elif len(groups) == 1:
                        total_tokens += int(groups[0])
                    break
        
        # Each request typically produces 2 log lines (receive + response)
        request_count = len(matched_lines) // 2 if len(matched_lines) > 1 else len(matched_lines)
        
        # Compute total if we have input/output
        if (input_tokens > 0 or output_tokens > 0) and total_tokens == 0:
            total_tokens = input_tokens + output_tokens
        
        result["requests_count"] = request_count
        
        if input_tokens > 0 or output_tokens > 0 or total_tokens > 0:
            result["input_tokens"] = input_tokens
            result["output_tokens"] = output_tokens
            result["total_tokens"] = total_tokens
            result["tracking"] = "live"
            result["details"] = {
                "note": "Token usage parsed from Qwen server logs"
            }
        elif request_count > 0:
            # Fallback: estimate tokens
            estimated_total = request_count * 2000
            result["total_tokens"] = estimated_total
            result["tracking"] = "estimated"
            result["details"] = {
                "note": f"Qwen server does not log token counts. Estimated ~{estimated_total} tokens ({request_count} req × 2000 avg)"
            }
        else:
            result["tracking"] = "not tracked"
            result["details"] = {"note": "No requests found in recent Qwen logs"}
    
    # KIMI: Parse token usage from log lines like:
    # QWEN: Parse token usage from log lines like:
    # [QWEN] request {"model":"qwen-1.5","prompt_tokens":10,"completion_tokens":15,"total_tokens":25}
    elif server_key == "QWEN":
        qwen_pattern = re.compile(r'\[QWEN\] request\s+({.*})')
        for line in log_lines:
            m = qwen_pattern.search(line)
            if m:
                try:
                    data = json.loads(m.group(1))
                    result['input_tokens'] = result.get('input_tokens', 0) + data.get('prompt_tokens', 0)
                    result['output_tokens'] = result.get('output_tokens', 0) + data.get('completion_tokens', 0)
                    result['total_tokens'] = result.get('total_tokens', 0) + data.get('total_tokens', 0)
                except Exception:
                    pass
    # [KIMI] request {"model":"kimi-k2.5","prompt_tokens":10,"completion_tokens":15,"total_tokens":25}
    elif server_key == "KIMI":
        kimi_pattern = re.compile(r'\[KIMI\] request\s+({.*})')
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0
        request_count = 0

        for line in all_lines:
            m = kimi_pattern.search(line)
            if m:
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    continue
                request_count += 1
                input_tokens += data.get("prompt_tokens", 0)
                output_tokens += data.get("completion_tokens", 0)
                total_tokens += data.get("total_tokens", 0)

        if request_count > 0:
            result["input_tokens"] = input_tokens
            result["output_tokens"] = output_tokens
            result["total_tokens"] = total_tokens
            result["requests_count"] = request_count
            result["tracking"] = "live"
            result["details"] = {"note": "Token usage parsed from KIMI log lines"}
        else:
            result["tracking"] = "not tracked"
            result["details"] = {"note": "No KIMI request lines in recent logs"}

    return result


def check_server_health(server_key: str, token: Optional[str] = None) -> dict:
    """Check server health endpoint. For QWEN, passes auth token if provided."""
    cfg = SERVERS[server_key]
    url = f"http://127.0.0.1:{cfg['port']}/v1{cfg['health_endpoint']}"
    result = {
        "api_url": url,
        "api_status": "unknown",
        "api_response": None,
    }
    
    headers = {}
    if server_key == "QWEN":
        # Use provided token or load from cache
        auth_token = token if token else get_qwen_token()
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
    
    try:
        resp = requests.get(url, timeout=3, headers=headers)
        result["api_status"] = "ok" if resp.status_code in cfg["health_expect_status"] else f"error_{resp.status_code}"
        try:
            result["api_response"] = resp.json()
        except Exception:
            result["api_response"] = resp.text[:500] if resp.text else None
    except requests.ConnectionError:
        result["api_status"] = "offline"
        result["api_response"] = None
    except requests.Timeout:
        result["api_status"] = "timeout"
        result["api_response"] = None
    except Exception as e:
        result["api_status"] = f"error: {str(e)}"
        result["api_response"] = None
    return result


def parse_active_models_from_logs(log_out_path: Path, log_err_path: Path) -> list:
    """Parse router logs to find which models are currently active (selected).
    Returns list of {virtual_model, selected_model, provider, tokens, requests}.
    Scans last 500 lines to find the most recent success for each virtual model."""
    out_lines = read_log_tail(log_out_path, 500) if log_out_path else []
    err_lines = read_log_tail(log_err_path, 500) if log_err_path else []
    all_lines = out_lines + err_lines
    
    if not all_lines:
        return []
    
    # Pattern: [VirtualModel] success provider:model-name (N tokens)
    success_pattern = re.compile(r'\[(\w+)\]\s+success\s+(\S+)\s+\((\d+)\s+tokens\)')
    
    # Track the most recent selected model per virtual model
    active = {}
    for line in all_lines:
        m = success_pattern.search(line)
        if m:
            vmodel = m.group(1)
            model_id = m.group(2)
            tokens = int(m.group(3))
            provider = model_id.split(':', 1)[0] if ':' in model_id else 'unknown'
            if vmodel not in active:
                active[vmodel] = {
                    "virtual_model": vmodel,
                    "selected_model": model_id,
                    "provider": provider,
                    "tokens": 0,
                    "requests": 0,
                }
            active[vmodel]["tokens"] += tokens
            active[vmodel]["requests"] += 1
    
    return list(active.values())


def get_router_runtime_status(server_key: str) -> Optional[dict]:
    """Fetch live router runtime counters from local /status.

    This is safer than parsing old log files: /status is local-only and does
    not call OpenRouter, while logs can contain stale pre-restart selections.
    """
    if server_key != "ROUTER":
        return None
    cfg = SERVERS[server_key]
    try:
        resp = requests.get(f"http://127.0.0.1:{cfg['port']}/status", timeout=2)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        return None
    return None


def active_models_from_router_status(status: Optional[dict]) -> list:
    """Convert router /status roles into Dashboard active_models rows."""
    if not isinstance(status, dict):
        return []
    rows = []
    roles = status.get("roles") or {}
    for virtual_model, info in roles.items():
        if not isinstance(info, dict):
            continue
        selected = info.get("selected")
        if not selected:
            continue
        tokens = info.get("tokens") or {}
        rows.append({
            "virtual_model": virtual_model,
            "selected_model": selected,
            "provider": selected.split(":", 1)[0] if ":" in selected else "unknown",
            "tokens": tokens.get("total", 0),
            "requests": info.get("requests", 0),
            "upstream_requests": status.get("upstreamRequests", 0),
            "source": "live_status",
        })
    return rows


def get_server_status(server_key: str) -> dict:
    """Return server status plus selected model context length (if applicable)."""
    cfg = SERVERS[server_key]
    pid = find_launcher_pid(cfg["launcher"], port=cfg["port"])

    # Determine running state by port check (launcher may have exited after starting the server)
    port_open = is_port_open("127.0.0.1", cfg["port"]) if cfg.get("port") else False
    running = pid is not None or port_open

    # Get uptime if PID found
    uptime = get_process_uptime(pid) if pid else None

    log_out_path = BASE_DIR / server_key / cfg["log_out"]
    log_err_path = BASE_DIR / server_key / cfg["log_err"]

    log_out_tail = read_log_tail(log_out_path, 20)
    log_err_tail = read_log_tail(log_err_path, 20)

    # Pass token for QWEN health check
    qwen_token = get_qwen_token() if server_key == "QWEN" else None
    health = check_server_health(server_key, token=qwen_token) if running else {
        "api_url": f"http://127.0.0.1:{cfg['port']}/v1{cfg['health_endpoint']}",
        "api_status": "stopped",
        "api_response": None,
    }

    router_runtime = get_router_runtime_status(server_key) if running and server_key == "ROUTER" else None
    if router_runtime is not None:
        active_models = active_models_from_router_status(router_runtime)
    else:
        active_models = parse_active_models_from_logs(log_out_path, log_err_path) if running and server_key == "ROUTER" else []

    result = {
        "key": server_key,
        "name": cfg["name"],
        "status": "running" if running else "stopped",
        "pid": pid,
        "uptime": uptime,
        "port": cfg["port"],
        "api_url": health["api_url"],
        "api_status": health["api_status"],
        "api_response": health["api_response"],
        "log_out_tail": log_out_tail,
        "log_err_tail": log_err_tail,
        "active_models": active_models,
        "router_runtime": router_runtime,
        "selected_context": None,
    }

    # If this is the Router and we have a selected model, fetch its declared context window
    if server_key == "ROUTER" and router_runtime:
        models_info = fetch_models_from_server(cfg["port"], server_key)
        if isinstance(models_info, dict) and "data" in models_info:
            selected = None
            if active_models:
                selected = active_models[0].get("selected_model")
            if selected:
                for m in models_info["data"]:
                    if m.get("id") == selected:
                        result["selected_context"] = m.get("context_length")
                        break

    return result


def _load_qwen_token() -> Optional[str]:
    """Legacy wrapper — delegates to cached get_qwen_token()."""
    return get_qwen_token()


def start_server_process(server_key: str) -> dict:
    """Запускает launcher.exe или node server.js для сервера."""
    cfg = SERVERS[server_key]
    launcher_name = cfg.get("launcher", "").strip()

    if launcher_name:
        launcher_path = BASE_DIR / server_key / launcher_name
        if launcher_path.is_file():
            # Check if port already in use
            if is_port_open("127.0.0.1", cfg["port"]):
                existing_pid = find_pid_by_port(cfg["port"])
                return {"message": f"{cfg['name']} already running (port {cfg['port']})", "pid": existing_pid}
            proc = subprocess.Popen(
                [str(launcher_path)],
                cwd=str(BASE_DIR / server_key),
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            return {"message": f"{cfg['name']} started", "pid": proc.pid}

    # Fallback: try node src/server.js (KIMI-style) or node server.js
    for server_js_name in ("src/server.js", "server.js"):
        server_js = BASE_DIR / server_key / server_js_name
        if server_js.exists():
            log_out_path = BASE_DIR / server_key / cfg.get("log_out", "router.out.log")
            log_err_path = BASE_DIR / server_key / cfg.get("log_err", "router.err.log")
            log_out_path.parent.mkdir(parents=True, exist_ok=True)
            _stdout = open(log_out_path, "a", encoding="utf-8")
            _stderr = open(log_err_path, "a", encoding="utf-8")
            proc = subprocess.Popen(
                ["node", server_js_name],
                cwd=str(BASE_DIR / server_key),
                stdout=_stdout,
                stderr=_stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            proc._log_handles = (_stdout, _stderr)
            return {"message": f"{cfg['name']} started via node {server_js_name}", "pid": proc.pid}

    raise FileNotFoundError(f"No launcher or server.js found for {server_key}")


def stop_server_process(server_key: str) -> dict:
    """Останавливает сервер — сначала по порту, затем fallback на launcher."""
    cfg = SERVERS[server_key]

    # Приоритет: поиск по порту (активный серверный процесс)
    pid = find_pid_by_port(cfg["port"])

    # Fallback: поиск launcher по имени
    if not pid:
        pid = find_launcher_pid(cfg["launcher"])

    if not pid:
        return {"message": f"{cfg['name']} is not running"}

    try:
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait(timeout=5)
        return {"message": f"{cfg['name']} stopped", "pid": pid}
    except psutil.NoSuchProcess:
        return {"message": f"{cfg['name']} process already gone"}
    except psutil.TimeoutExpired:
        try:
            proc.kill()
            return {"message": f"{cfg['name']} force killed", "pid": pid}
        except Exception as e:
            return {"message": f"Failed to kill: {str(e)}", "pid": pid}


def fetch_models_from_server(port: int, server_key: str = None) -> dict:
    """Fetch /v1/models from a local AI server. For QWEN, uses cached auth token."""
    url = f"http://127.0.0.1:{port}/v1/models"
    headers = {}
    
    if server_key == "QWEN":
        token = get_qwen_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    
    try:
        resp = requests.get(url, timeout=5, headers=headers)
        # Fallback for QWEN if /v1/models fails with 401
        if resp.status_code == 401 and server_key == "QWEN":
            fallback_url = f"http://127.0.0.1:{port}/models"
            resp = requests.get(fallback_url, timeout=5, headers=headers)
        
        if resp.status_code == 401:
            return {"error": "Authorization required (401). Check token in Authorization.txt", "models": []}
        
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200] if e.response else str(e)}", "models": []}
    except Exception as e:
        return {"error": str(e), "models": []}


def load_accounts_qwen() -> list:
    """Load QWEN accounts from Authorization.txt (one token/key per line).
    Filters out comments (#) and empty lines. Returns only key previews."""
    path = SERVERS["QWEN"]["accounts_path"]
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = [
                l.strip() for l in f.readlines()
                if l.strip() and not l.strip().startswith("#")
            ]
        return [
            {
                "id": f"account_{i+1}",
                "token_preview": l[:8] + "..." if len(l) > 8 else l
            }
            for i, l in enumerate(lines)
        ]
    except Exception:
        return []


def load_accounts_deepseek() -> list:
    """Load DEEPSEEK accounts from deepseek-auth.json."""
    path = SERVERS["DEEPSEEK"]["accounts_path"]
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        # Support both single account object and list of accounts
        if isinstance(data, list):
            accounts = data
        elif isinstance(data, dict):
            accounts = [data]
        else:
            return []
        result = []
        for i, acc in enumerate(accounts):
            info = {"id": acc.get("id", f"account_{i+1}")}
            if "token" in acc:
                t = str(acc["token"])
                info["token_preview"] = t[:8] + "..." if len(t) > 8 else t
            if "cookie" in acc:
                c = str(acc["cookie"])
                info["has_cookie"] = True
            result.append(info)
        return result
    except Exception:
        return []

def load_accounts_kimi() -> list:
    """Load KIMI accounts from auth.json (same format as AccountManager expects)."""
    path = SERVERS["KIMI"]["accounts_path"]
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        # Expect {'accounts': [...]} or a list directly
        if isinstance(data, dict) and isinstance(data.get("accounts"), list):
            accounts = data["accounts"]
        elif isinstance(data, list):
            accounts = data
        elif isinstance(data, dict):
            accounts = [data]
        else:
            return []
        result = []
        for i, acc in enumerate(accounts):
            info = {"id": acc.get("id", f"account_{i+1}")}
            if "token" in acc:
                t = str(acc["token"])
                info["token_preview"] = t[:8] + "..." if len(t) > 8 else t
            if "cookie" in acc:
                info["has_cookie"] = True
            # Determine status based on cooldownUntil if present (timestamp ms)
            cooldown = acc.get("cooldownUntil")
            if cooldown is not None:
                try:
                    now_ms = int(time.time() * 1000)
                    info["status"] = "cooldown" if int(cooldown) > now_ms else "active"
                except Exception:
                    info["status"] = "active"
            else:
                info["status"] = "active"
            result.append(info)
        return result
    except Exception:
        return []


def load_router_config(server_key: str = "ROUTER") -> dict:
    """Load ROUTER/ROUTER2 config.json."""
    cfg = SERVERS.get(server_key, SERVERS["ROUTER"])
    path = cfg.get("config_path", BASE_DIR / server_key / "config.json")
    if not path.exists():
        return {"error": f"Config file not found: {path}"}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception as e:
        log.exception("Failed to load router config for %s from %s", server_key, path)
        return {"error": str(e), "path": str(path)}


def parse_router_selected_models(log_out_path: Path, log_err_path: Path) -> dict:
    """Parse router logs to find which models were actually selected/used.
    Returns dict mapping virtual_model -> {selected_model, provider, count}.
    Works for any virtual model name (Orcestrator, Coder, Debugger, etc.)."""
    result = {}
    
    out_lines = read_log_tail(log_out_path, 500) if log_out_path else []
    err_lines = read_log_tail(log_err_path, 500) if log_err_path else []
    all_lines = out_lines + err_lines
    
    # Pattern: [VirtualModel] success provider:model-name (N tokens)
    success_pattern = re.compile(r'\[(\w+)\]\s+success\s+(\S+)\s+\((\d+)\s+tokens\)')
    # Pattern: [VirtualModel] trying provider:model-name
    trying_pattern = re.compile(r'\[(\w+)\]\s+trying\s+(\S+)')
    # Pattern: [VirtualModel] failed provider:model-name
    failed_pattern = re.compile(r'\[(\w+)\]\s+failed\s+(\S+)')
    
    for line in all_lines:
        # Track successful model selections with token counts
        succ_match = success_pattern.search(line)
        if succ_match:
            vmodel = succ_match.group(1)
            model_id = succ_match.group(2)
            tokens = int(succ_match.group(3))
            
            if vmodel not in result:
                result[vmodel] = {"selected_model": model_id, "count": 0, "tokens": 0, "failures": 0}
            result[vmodel]["count"] += 1
            result[vmodel]["tokens"] += tokens
            if ':' in model_id:
                result[vmodel]["provider"] = model_id.split(':', 1)[0]
            continue
        
        # Track trying attempts
        try_match = trying_pattern.search(line)
        if try_match:
            vmodel = try_match.group(1)
            model_id = try_match.group(2)
            if vmodel not in result:
                result[vmodel] = {"selected_model": None, "count": 0, "tokens": 0, "failures": 0}
            if "tried_models" not in result[vmodel]:
                result[vmodel]["tried_models"] = []
            result[vmodel]["tried_models"].append(model_id)
            continue
        
        # Track failures
        fail_match = failed_pattern.search(line)
        if fail_match:
            vmodel = fail_match.group(1)
            model_id = fail_match.group(2)
            if vmodel not in result:
                result[vmodel] = {"selected_model": None, "count": 0, "tokens": 0, "failures": 0}
            result[vmodel]["failures"] += 1
            continue
    
    return result


# === Endpoints ===

@app.get("/")
async def serve_frontend():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        candidates = [str(candidate / "index.html") for candidate in FRONTEND_CANDIDATES]
        log.error(
            "Frontend not found. selected=%s candidates=%s cwd=%s app_dir=%s bundle_dir=%s",
            index_path, candidates, Path.cwd(), APP_DIR, BUNDLE_DIR,
        )
        raise HTTPException(
            status_code=404,
            detail=f"Frontend not found. See log: {LOG_FILE}",
        )
    return FileResponse(index_path, media_type="text/html")


@app.get("/api/debug/paths")
async def debug_paths():
    """Runtime path diagnostics for packaged dashboard troubleshooting."""
    return JSONResponse(content={
        "frozen": bool(getattr(_sys, "frozen", False)),
        "executable": str(getattr(_sys, "executable", "")),
        "cwd": str(Path.cwd()),
        "app_dir": str(APP_DIR),
        "bundle_dir": str(BUNDLE_DIR),
        "frontend_dir": str(FRONTEND_DIR),
        "frontend_index_exists": (FRONTEND_DIR / "index.html").exists(),
        "frontend_candidates": [
            {"path": str(candidate), "index_exists": (candidate / "index.html").exists()}
            for candidate in FRONTEND_CANDIDATES
        ],
        "log_file": str(LOG_FILE),
    })


@app.get("/api/servers")
async def list_servers():
    """Статус всех серверов."""
    statuses = []
    for key in SERVERS:
        statuses.append(get_server_status(key))
    return JSONResponse(content=statuses)


@app.post("/api/servers/all/start")
async def start_all_servers():
    """Запуск всех серверов одним вызовом."""
    results = {}
    for key in SERVERS:
        try:
            results[key] = start_server_process(key)
        except Exception as e:
            results[key] = {"error": str(e)}
    return JSONResponse(content=results)


@app.post("/api/servers/all/stop")
async def stop_all_servers():
    """Остановка всех серверов одним вызовом."""
    results = {}
    for key in SERVERS:
        try:
            results[key] = stop_server_process(key)
        except Exception as e:
            results[key] = {"error": str(e)}
    return JSONResponse(content=results)


@app.post("/api/servers/{server_key}/start")
async def start_server(server_key: str):
    """Запуск одного сервера через launcher.exe."""
    server_key = server_key.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")
    try:
        result = start_server_process(server_key)
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start: {str(e)}")


@app.post("/api/servers/{server_key}/stop")
async def stop_server(server_key: str):
    """Остановка одного сервера."""
    server_key = server_key.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")
    try:
        result = stop_server_process(server_key)
        return JSONResponse(content=result)
    except psutil.NoSuchProcess:
        return JSONResponse(content={"message": f"{SERVERS[server_key]['name']} process already gone"})
    except psutil.TimeoutExpired:
        try:
            cfg = SERVERS[server_key]
            pid = find_pid_by_port(cfg["port"]) or find_launcher_pid(cfg["launcher"])
            if pid:
                proc = psutil.Process(pid)
                proc.kill()
            return JSONResponse(content={"message": f"{SERVERS[server_key]['name']} force killed"})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to kill: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")


@app.get("/api/servers/{server_key}/logs")
async def get_logs(server_key: str, lines: int = Query(default=100, ge=1, le=1000)):
    """Последние N строк из log_out и log_err файлов.
    Возвращает stdout, stderr, combined (merged) и logs (alias для combined).
    """
    server_key = server_key.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")

    cfg = SERVERS[server_key]
    log_out_path = BASE_DIR / server_key / cfg["log_out"]
    log_err_path = BASE_DIR / server_key / cfg["log_err"]

    stdout_lines = [sanitize_log_line(l) for l in read_log_tail(log_out_path, lines)]
    stderr_lines = [sanitize_log_line(l) for l in read_log_tail(log_err_path, lines)]

    # Combine stdout + stderr; since we don't have timestamps in plain log tails,
    # interleave them preserving order: stdout first, then stderr appended.
    combined = stdout_lines + stderr_lines

    return JSONResponse(content={
        "key": server_key,
        "lines_requested": lines,
        "stdout": stdout_lines,
        "stderr": stderr_lines,
        "combined": combined,
        "logs": combined,  # alias for frontend compatibility
    })


@app.get("/api/servers/{server_key}/info")
async def get_server_info(server_key: str):
    """Расширенная информация о сервере: модели, аккаунты, конфиг роутера."""
    server_key = server_key.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")

    cfg = SERVERS[server_key]
    port = cfg["port"]

    # Check if server is reachable
    if not is_port_open("127.0.0.1", port):
        return JSONResponse(content={
            "key": server_key,
            "name": cfg["name"],
            "status": "offline",
            "error": f"Server not reachable on port {port}",
            "models": [],
            "accounts": [],
        })

    # Fetch models from /v1/models (with token for QWEN)
    models_data = fetch_models_from_server(port, server_key=server_key)
    if "error" in models_data and not models_data.get("models"):
        return JSONResponse(content={
            "key": server_key,
            "name": cfg["name"],
            "status": "error",
            "error": models_data["error"],
            "models": [],
            "accounts": [],
        })

    # Parse models list
    raw_models = models_data.get("data", models_data.get("models", []))
    parsed_models = []
    for m in raw_models:
        model_info = {
            "id": m.get("id", "unknown"),
            "object": m.get("object", "model"),
            "owned_by": m.get("owned_by", None),
        }
        # Extract capabilities if present
        caps = []
        if m.get("reasoning") or m.get("supports_reasoning"):
            caps.append("reasoning")
        if m.get("web_search") or m.get("supports_web_search"):
            caps.append("web_search")
        if m.get("files") or m.get("supports_files") or m.get("supports_vision"):
            caps.append("files")
        model_info["capabilities"] = caps

        # real_model hint (some proxies expose this)
        if "real_model" in m:
            model_info["real_model"] = m["real_model"]
        elif "internal_model" in m:
            model_info["real_model"] = m["internal_model"]

        parsed_models.append(model_info)

    result = {
        "key": server_key,
        "name": cfg["name"],
        "port": port,
        "status": "online",
        "models": parsed_models,
        "models_raw": models_data,
    }

    # Server-specific extras
    if server_key == "QWEN":
        result["accounts"] = load_accounts_qwen()
        result["models_count"] = len(parsed_models)
    elif server_key == "DEEPSEEK":
        result["accounts"] = load_accounts_deepseek()
        # Fetch additional DEEPSEEK info
        ds_extra = {}
        try:
            cap_url = f"http://127.0.0.1:{port}/v1/model-capabilities"
            cap_resp = requests.get(cap_url, timeout=3)
            if cap_resp.status_code == 200:
                ds_extra["model_capabilities"] = cap_resp.json()
        except Exception:
            pass
        try:
            sess_url = f"http://127.0.0.1:{port}/v1/sessions"
            sess_resp = requests.get(sess_url, timeout=3)
            if sess_resp.status_code == 200:
                ds_extra["sessions"] = sess_resp.json()
        except Exception:
            pass
        if ds_extra:
            result["deepseek_extra"] = ds_extra
    elif server_key == "KIMI":
        result["accounts"] = load_accounts_kimi()
    elif server_key == "ROUTER":
        router_cfg = load_router_config(server_key)
        result["router_config"] = router_cfg

        # Extract virtualModels summary
        vm = router_cfg.get("virtualModels", {}) if isinstance(router_cfg, dict) else {}
        virtual_summary = {}
        for vmodel_name, attempts in vm.items():
            virtual_summary[vmodel_name] = {
                "attempts_count": len(attempts) if isinstance(attempts, list) else 0,
                "providers": list(set(a.get("provider", "unknown") for a in attempts)) if isinstance(attempts, list) else [],
                "models": [a.get("model", "unknown") for a in attempts] if isinstance(attempts, list) else [],
            }

        # Add selected_model info from logs
        log_out_path = BASE_DIR / server_key / cfg["log_out"]
        log_err_path = BASE_DIR / server_key / cfg["log_err"]
        selected_models = parse_router_selected_models(log_out_path, log_err_path)
        
        # Merge selected model info into virtual_summary
        for vmodel_name in virtual_summary:
            if vmodel_name in selected_models:
                virtual_summary[vmodel_name]["selected_model"] = selected_models[vmodel_name].get("selected_model")
                virtual_summary[vmodel_name]["selection_count"] = selected_models[vmodel_name].get("count", 0)
        
        # Also add any models found in logs but not in config
        for key, val in selected_models.items():
            if key not in virtual_summary and not key.startswith("_used_"):
                virtual_summary[key] = {
                    "attempts_count": 0,
                    "providers": [],
                    "models": [],
                    "selected_model": val.get("selected_model"),
                    "selection_count": val.get("count", 0),
                    "source": "logs_only"
                }
        
        result["virtual_models"] = virtual_summary
        result["accounts"] = []  # Router doesn't have direct accounts

    return JSONResponse(content=result)


@app.get("/api/servers/{server_key}/tokens")
async def get_server_tokens(server_key: str):
    """Информация о токенах и запросах для сервера.
    Для ROUTER — берёт данные из runtimeState (/status).
    Для остальных — парсит лог-файлы.
    """
    server_key = server_key.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")

    cfg = SERVERS[server_key]

    # Для ROUTER используем live-данные из /status
    if server_key == "ROUTER":
        router_cfg = SERVERS.get("ROUTER", {})
        port = router_cfg.get("port", 3270)
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/status", timeout=3)
            if resp.status_code == 200:
                status = resp.json()
                usage = status.get("usage", {})
                by_model = usage.get("byCandidate", {})
                requests_count = status.get("totalRequests", 0)
                return JSONResponse(content={
                    "key": server_key,
                    "name": cfg["name"],
                    "input_tokens": usage.get("prompt", 0),
                    "output_tokens": usage.get("completion", 0),
                    "total_tokens": usage.get("total", 0),
                    "requests_count": requests_count,
                    "tracking": "live",
                    "source": "runtime_state",
                    "details": {
                        "by_model": {
                            k: {
                                "input_tokens": v.get("prompt", 0),
                                "output_tokens": v.get("completion", 0),
                                "total_tokens": v.get("total", 0),
                            }
                            for k, v in by_model.items()
                        },
                        "note": "Token counts from router runtime state (live)"
                    }
                })
        except Exception as e:
            log.error(f"Failed to fetch router /status for tokens: {e}")
            # Fallback to log parsing
            pass

    log_out_path = BASE_DIR / server_key / cfg["log_out"]
    log_err_path = BASE_DIR / server_key / cfg["log_err"]

    # Parse tokens from logs
    token_data = parse_tokens_from_logs(log_out_path, log_err_path, server_key)

    # Build response
    result = {
        "key": server_key,
        "name": cfg["name"],
        "input_tokens": token_data["input_tokens"],
        "output_tokens": token_data["output_tokens"],
        "total_tokens": token_data["total_tokens"],
        "requests_count": token_data["requests_count"],
        "tracking": token_data["tracking"],
        "source": token_data["source"],
    }

    # Add details if available
    if token_data.get("details"):
        result["details"] = token_data["details"]

    # Add note for servers without token tracking
    if token_data["tracking"] == "not tracked":
        result["note"] = "This server does not expose token usage statistics in logs."
    elif token_data["tracking"] == "estimated":
        result["note"] = "Token counts are estimated based on request count (no explicit token data in logs)."
    elif token_data["tracking"] == "requests_only":
        result["note"] = "Only request count is tracked. Token counts are not available in logs."

    return JSONResponse(content=result)


@app.post("/api/auth/run")
async def run_auth_script(skey: str):
    """Запуск скрипта auth для сервера (авторизация через браузер)."""
    server_key = skey.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")

    import subprocess as _subproc
    qwen_root = BASE_DIR / "QWEN"
    deepseek_root = BASE_DIR / "DEEPSEEK"

    if server_key == "QWEN":
        script_path = qwen_root / "scripts" / "auth.js"
        env_vars = {
            "SESSION_DIR": str(qwen_root / "session"),
            "HOME": os.path.expanduser("~"),
            "NODE_OPTIONS": "--no-warnings --openssl-legacy-provider",
        }
        cwd = str(qwen_root)
    elif server_key == "DEEPSEEK":
        script_path = deepseek_root / "scripts" / "deepseek_chrome_auth.js"
        env_vars = {
            "DEEPSEEK_AUTH_PATH": str(deepseek_root / "deepseek-auth.json"),
            "DEEPSEEK_CHROME_PROFILE": str(deepseek_root / ".chrome-for-testing-profile-deepseek"),
            "NODE_OPTIONS": "--no-warnings --openssl-legacy-provider",
        }
        cwd = str(deepseek_root)
    else:
        raise HTTPException(status_code=400, detail=f"Auth not supported for {server_key}")

    proc = _subproc.run(
        ["node", str(script_path)],
        capture_output=True, text=True, timeout=600, cwd=cwd,
        env={**dict(os.environ), **env_vars},
    )

    return {"stdout": proc.stdout.strip(), "stderr": proc.stderr.strip(), "exit_code": proc.returncode}


@app.post("/api/rotate-key/{server_key}")
async def rotate_key(server_key: str):
    """Rotate key between available accounts for server."""
    server_key = server_key.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")
    if server_key not in ("QWEN", "DEEPSEEK", "KIMI"):
        raise HTTPException(status_code=400, detail=f"Key rotation not supported for {server_key}")
    try:
        if server_key == "QWEN":
            return _rotate_qwen_account()
        elif server_key == "DEEPSEEK":
            return _rotate_deepseek_account()
        elif server_key == "KIMI":
            return _rotate_kimi_account()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rotate key: {str(e)}")


@app.get("/api/accounts/{server_key}")
async def list_accounts(server_key: str):
    """List all configured accounts for a server with status and current pointer."""
    server_key = server_key.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")

    if server_key == "QWEN":
        return _list_qwen_accounts()
    elif server_key == "DEEPSEEK":
        return _list_deepseek_accounts()
    elif server_key == "KIMI":
        return {"server_key": "KIMI", "accounts": load_accounts_kimi(), "total": len(load_accounts_kimi())}
    else:
        raise HTTPException(status_code=400, detail=f"Server {server_key} does not support accounts")


def _list_qwen_accounts():
    """Load Qwen accounts from session/tokens.json with round-robin status."""
    import json as _json
    qwen_root = BASE_DIR / "QWEN"
    tokens_file = qwen_root / "session" / "tokens.json"
    accounts_dir = qwen_root / "session" / "accounts"

    tokens = []
    if tokens_file.exists():
        try:
            with open(tokens_file, "r", encoding="utf-8") as f:
                tokens = _json.load(f)
        except Exception:
            tokens = []

    # Determine current account from round-robin pointer
    # tokenManager uses pointer % valid.length, so current = pointer % len(valid)
    # We can infer from the order: the last used is (pointer - 1) % valid_count
    # But we don't have direct access to pointer, so we check file modification time
    # and use a simpler heuristic: check which account was most recently active
    now = time.time()
    valid_tokens = [t for t in tokens if not t.get("invalid") and (not t.get("resetAt") or _parse_reset(t["resetAt"]) <= now)]
    invalid_tokens = [t for t in tokens if t.get("invalid")]
    cooldown_tokens = [t for t in tokens if not t.get("invalid") and t.get("resetAt") and _parse_reset(t["resetAt"]) > now]

    # Build account list with status
    accounts = []
    current_id = None

    # Try to read pointer from a state file (written by qwen server)
    pointer_file = qwen_root / "session" / "pointer.state"
    pointer = 0
    if pointer_file.exists():
        try:
            with open(pointer_file, "r") as f:
                pointer = int(f.read().strip())
        except Exception:
            pointer = 0

    if valid_tokens:
        current_idx = (pointer - 1) % len(valid_tokens) if pointer > 0 else len(valid_tokens) - 1
        current_id = valid_tokens[current_idx].get("id")

    for t in tokens:
        acc_id = t.get("id", "unknown")
        status = "active"
        if t.get("invalid"):
            status = "invalid"
        elif t.get("resetAt") and _parse_reset(t["resetAt"]) > now:
            status = "cooldown"

        # Check if token file exists
        token_file = accounts_dir / acc_id / "token.txt"
        has_token = token_file.exists()

        accounts.append({
            "id": acc_id,
            "status": status,
            "has_token": has_token,
            "is_current": acc_id == current_id,
            "reset_at": t.get("resetAt"),
        })

    return {"server_key": "QWEN", "accounts": accounts, "current_id": current_id, "total": len(tokens)}


def _parse_reset(reset_at_str):
    """Parse resetAt ISO string to timestamp."""
    from datetime import datetime
    try:
        return datetime.fromisoformat(reset_at_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def _list_deepseek_accounts():
    """Load DeepSeek accounts from auth-pool directory or deepseek-auth.json with round-robin status."""
    import json as _json
    ds_root = BASE_DIR / "DEEPSEEK"

    # Support directory pool, multi-path env, or single file
    auth_files = []
    auth_dir_env = os.environ.get("DEEPSEEK_AUTH_DIR", "")
    auth_path_env = os.environ.get("DEEPSEEK_AUTH_PATH", "")

    if auth_dir_env and os.path.isdir(auth_dir_env):
        auth_files = sorted([
            os.path.join(auth_dir_env, f)
            for f in os.listdir(auth_dir_env)
            if f.endswith(".json")
        ])
    elif auth_path_env and "," in auth_path_env:
        auth_files = [p.strip() for p in auth_path_env.split(",") if p.strip()]
    else:
        # Default: check auth-pool directory first, then fall back to single file
        auth_pool_dir = ds_root / "auth-pool"
        if auth_pool_dir.exists() and auth_pool_dir.is_dir():
            pool_files = sorted([
                str(f) for f in auth_pool_dir.glob("*.json")
            ])
            if pool_files:
                auth_files = pool_files
            else:
                # Fall back to legacy single file
                default_path = ds_root / "deepseek-auth.json"
                if default_path.exists():
                    auth_files = [str(default_path)]
        else:
            default_path = ds_root / "deepseek-auth.json"
            if default_path.exists():
                auth_files = [str(default_path)]

    accounts = []
    current_id = None

    # Try to read current account from server health endpoint
    # DeepSeek server returns current_account directly; fallback to last_used_at heuristic
    try:
        health_url = f"http://127.0.0.1:{SERVERS['DEEPSEEK']['port']}/health"
        resp = requests.get(health_url, timeout=2)
        if resp.status_code == 200:
            health_data = resp.json()
            current_id = health_data.get("current_account")
            # Fallback: if server doesn't provide current_account, pick account with latest last_used_at
            if not current_id:
                server_accounts = health_data.get("accounts", [])
                ready = [a for a in server_accounts if a.get("ready") and not a.get("cooldown")]
                if ready:
                    latest = max(ready, key=lambda a: a.get("last_used_at") or 0)
                    current_id = latest.get("id")
    except Exception:
        pass

    for i, fpath in enumerate(auth_files):
        acc_id = f"account_{i + 1}"
        has_token = False
        has_cookie = False
        status = "unknown"

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = _json.load(f)
            has_token = bool(data.get("token"))
            has_cookie = bool(data.get("cookie"))
            status = "active" if (has_token and has_cookie) else "incomplete"
        except Exception:
            status = "error"

        accounts.append({
            "id": acc_id,
            "status": status,
            "has_token": has_token,
            "has_cookie": has_cookie,
            "is_current": acc_id == current_id,
            "file": os.path.basename(fpath),
            "token_preview": (data.get("token", "")[:8] + "...") if has_token else None,
        })

    return {"server_key": "DEEPSEEK", "accounts": accounts, "current_id": current_id, "total": len(accounts)}


@app.post("/api/accounts/{server_key}/add")
async def add_account(server_key: str, mode: str = Query(default="browser", enum=["browser", "manual"])):
    """Add a new account to a server.
    
    mode=browser: launches the auth script (opens browser for login)
    manual: expects token/cookie in request body (not yet implemented)
    """
    server_key = server_key.upper()
    if server_key not in ("QWEN", "DEEPSEEK", "KIMI"):
        raise HTTPException(status_code=400, detail=f"Server {server_key} does not support accounts")

    if mode == "manual":
        # Manual mode is handled by a separate endpoint below
        raise HTTPException(status_code=400, detail="Use POST /api/accounts/{server}/add-manual for manual account addition.")

    # Launch auth script
    import subprocess as _subproc

    if server_key == "QWEN":
        script_path = BASE_DIR / "QWEN" / "scripts" / "auth.js"
        if not script_path.exists():
            raise HTTPException(status_code=404, detail="Auth script not found")
        cmd = ["node", str(script_path), "--add"]
        cwd = str(BASE_DIR / "QWEN")
        env_vars = {
            "SESSION_DIR": str(BASE_DIR / "QWEN" / "session"),
            "HOME": os.path.expanduser("~"),
            "NODE_OPTIONS": "--no-warnings --openssl-legacy-provider",
            "NON_INTERACTIVE": "0",
        }
    elif server_key == "DEEPSEEK":
        script_path = BASE_DIR / "DEEPSEEK" / "scripts" / "deepseek_chrome_auth.js"
        if not script_path.exists():
            raise HTTPException(status_code=404, detail="Auth script not found")
        cmd = ["node", str(script_path)]
        cwd = str(BASE_DIR / "DEEPSEEK")
        deepseek_auth_dir = str(BASE_DIR / "DEEPSEEK" / "auth-pool")
        env_vars = {
            "DEEPSEEK_AUTH_DIR": deepseek_auth_dir,
            "NODE_OPTIONS": "--no-warnings --openssl-legacy-provider",
        }
    elif server_key == "KIMI":
        # For KIMI: manual-only (no browser auth script); redirect to manual
        raise HTTPException(status_code=400, detail="KIMI only supports manual account addition. Use mode=manual or POST /api/accounts/KIMI/add-manual")

    try:
        # Launch auth script in a separate visible terminal window so the
        # user can interact with the browser login prompt.  Using
        # CREATE_NEW_CONSOLE (Windows) or xterm (Linux) keeps the script
        # alive with its own stdin/stdout, while the backend returns
        # immediately so the dashboard never blocks.
        _env = {**dict(os.environ), **env_vars}
        if os.name == "nt":
            # Windows: open a new console window
            _flags = _subproc.CREATE_NEW_CONSOLE
            _proc = _subproc.Popen(
                cmd, cwd=cwd, env=_env,
                creationflags=_flags,
                close_fds=True,
            )
        else:
            # Linux / macOS: try xterm, then fall back to nohup
            _term_cmd = ["xterm", "-e", " ".join(cmd)]
            try:
                _proc = _subproc.Popen(
                    _term_cmd, cwd=cwd, env=_env,
                    close_fds=True,
                )
            except FileNotFoundError:
                _proc = _subproc.Popen(
                    cmd, cwd=cwd, env=_env,
                    stdout=_subproc.DEVNULL, stderr=_subproc.DEVNULL,
                    close_fds=True,
                )
        return {
            "ok": True,
            "detail": f"Auth window opened for {server_key}. Complete login in the new window.",
            "pid": _proc.pid,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to launch auth script: {str(e)}")


@app.post("/api/accounts/{server_key}/add-manual")
async def add_account_manual(server_key: str, body: dict):
    """Manually add an account by providing token/cookie directly (no browser)."""
    server_key = server_key.upper()
    if server_key not in ("QWEN", "DEEPSEEK", "KIMI"):
        raise HTTPException(status_code=400, detail=f"Server {server_key} does not support accounts")

    token = body.get("token", "").strip()
    cookie = body.get("cookie", "").strip()

    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    if server_key == "QWEN":
        # For QWEN: append token to session/tokens.json
        qwen_root = BASE_DIR / "QWEN"
        tokens_file = qwen_root / "session" / "tokens.json"
        accounts_dir = qwen_root / "session" / "accounts"

        tokens = []
        if tokens_file.exists():
            try:
                with open(tokens_file, "r", encoding="utf-8") as f:
                    tokens = json.load(f)
            except Exception:
                tokens = []

        # Generate account ID
        acc_id = f"acc_{int(time.time() * 1000)}"

        # Add to tokens.json
        tokens.append({
            "id": acc_id,
            "token": token,
            "resetAt": None,
            "invalid": False
        })

        # Ensure accounts dir exists
        accounts_dir.mkdir(parents=True, exist_ok=True)
        acc_dir = accounts_dir / acc_id
        acc_dir.mkdir(exist_ok=True)

        # Write token.txt
        token_file = acc_dir / "token.txt"
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(token)

        # Save tokens.json
        with open(tokens_file, "w", encoding="utf-8") as f:
            json.dump(tokens, f, indent=2)

        return {"ok": True, "account_id": acc_id, "detail": "Account added to QWEN token pool"}

    elif server_key == "DEEPSEEK":
        # For DeepSeek: always save as a new file in auth-pool directory
        ds_root = BASE_DIR / "DEEPSEEK"
        auth_pool_dir = ds_root / "auth-pool"
        auth_pool_dir.mkdir(parents=True, exist_ok=True)

        # Find next available index
        existing = []
        for f in auth_pool_dir.glob("deepseek-auth-*.json"):
            try:
                idx = int(f.stem.replace("deepseek-auth-", ""))
                existing.append(idx)
            except Exception:
                pass
        next_idx = max(existing) + 1 if existing else 1
        auth_file = auth_pool_dir / f"deepseek-auth-{next_idx}.json"

        # Write the file
        with open(auth_file, "w", encoding="utf-8") as f:
            json.dump({"token": token, "cookie": cookie}, f, indent=2)

        return {"ok": True, "auth_file": auth_file.name, "detail": f"Account added to DeepSeek auth pool (total: {next_idx})"}

    elif server_key == "KIMI":
        # For KIMI: append account to auth.json accounts array
        kimi_root = BASE_DIR / "KIMI"
        auth_file = kimi_root / "auth.json"
        accounts = []
        if auth_file.exists():
            try:
                with open(auth_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("accounts"), list):
                    accounts = data["accounts"]
                elif isinstance(data, list):
                    accounts = data
                elif isinstance(data, dict):
                    accounts = [data]
            except Exception:
                accounts = []
        # Generate account ID
        acc_id = f"kimi_{int(time.time() * 1000)}"
        new_account = {"id": acc_id, "provider": "kimi", "token": token}
        if cookie:
            new_account["cookie"] = cookie
        accounts.append(new_account)
        # Write back
        with open(auth_file, "w", encoding="utf-8") as f:
            json.dump({"accounts": accounts}, f, indent=2)
        return {"ok": True, "account_id": acc_id, "detail": f"Account added to KIMI auth pool (total: {len(accounts)})"}

    else:
        raise HTTPException(status_code=400, detail=f"Server {server_key} not supported for manual add")


@app.post("/api/accounts/{server_key}/rotate")
async def rotate_account(server_key: str):
    """Force rotate to next account for a server."""
    server_key = server_key.upper()
    if server_key == "QWEN":
        return _rotate_qwen_account()
    elif server_key == "DEEPSEEK":
        return _rotate_deepseek_account()
    elif server_key == "KIMI":
        return _rotate_kimi_account()
    else:
        raise HTTPException(status_code=400, detail=f"Server {server_key} does not support accounts")


def _rotate_qwen_account():
    """Rotate Qwen to next account by incrementing pointer."""
    import json as _json
    qwen_root = BASE_DIR / "QWEN"
    tokens_file = qwen_root / "session" / "tokens.json"
    pointer_file = qwen_root / "session" / "pointer.state"

    tokens = []
    if tokens_file.exists():
        try:
            with open(tokens_file, "r", encoding="utf-8") as f:
                tokens = _json.load(f)
        except Exception:
            pass

    if not tokens:
        return {"ok": False, "detail": "No accounts configured"}

    now = time.time()
    valid = [t for t in tokens if not t.get("invalid") and (not t.get("resetAt") or _parse_reset(t["resetAt"]) <= now)]
    if not valid:
        return {"ok": False, "detail": "No valid accounts available"}

    # Read current pointer
    pointer = 0
    if pointer_file.exists():
        try:
            with open(pointer_file, "r") as f:
                pointer = int(f.read().strip())
        except Exception:
            pointer = 0

    # Advance pointer
    pointer = (pointer + 1) % len(valid)
    try:
        with open(pointer_file, "w") as f:
            f.write(str(pointer))
    except Exception as e:
        return {"ok": False, "detail": f"Failed to write pointer: {e}"}

    new_current = valid[pointer].get("id")
    return {"ok": True, "new_current_id": new_current, "pointer": pointer}


def _rotate_deepseek_account():
    """Rotate DeepSeek account: advance round-robin pointer on the server and reset sessions."""
    try:
        port = SERVERS["DEEPSEEK"]["port"]
        # 1. Reload auth config to pick up any newly added accounts
        try:
            reload_resp = requests.post(f"http://127.0.0.1:{port}/reload-auth", timeout=5)
            if reload_resp.status_code == 200:
                reload_data = reload_resp.json()
                log.info(f"DeepSeek auth reload: {reload_data.get('accounts_after', '?')} account(s)")
        except Exception as e:
            log.warning(f"DeepSeek auth reload failed (non-critical): {e}")
        # 2. Advance round-robin pointer on the server
        try:
            rotate_resp = requests.post(f"http://127.0.0.1:{port}/rotate-account", timeout=5)
            rotate_data = rotate_resp.json() if rotate_resp.status_code == 200 else {}
        except Exception as e:
            log.warning(f"DeepSeek rotate-account failed (non-critical): {e}")
            rotate_data = {}
        # 3. Reset all sessions so new sessions pick up the new account
        resp = requests.post(f"http://127.0.0.1:{port}/reset-session?agent=all", timeout=5)
        if resp.status_code == 200:
            new_account = rotate_data.get("current_account", "?")
            return {"ok": True, "detail": f"Rotated. Next account: {new_account}", "current_account": new_account}
        else:
            return {"ok": False, "detail": f"Reset returned HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


def _rotate_kimi_account():
    """Rotate KIMI by reordering accounts in auth.json (move first to end).
    Since KIMI's AccountManager uses round-robin selection, changing the order
    effectively rotates which account is picked next."""
    try:
        auth_file = SERVERS["KIMI"]["accounts_path"]
        if not auth_file.exists():
            return {"ok": False, "detail": "auth.json not found"}
        with open(auth_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("accounts"), list):
            accounts = data["accounts"]
        elif isinstance(data, list):
            accounts = data
        else:
            return {"ok": False, "detail": "No accounts array found in auth.json"}
        if len(accounts) <= 1:
            return {"ok": False, "detail": "Need at least 2 accounts to rotate"}
        # Rotate: move first account to end
        first = accounts.pop(0)
        accounts.append(first)
        # Write back
        if isinstance(data, dict) and "accounts" in data:
            data["accounts"] = accounts
        else:
            data = accounts
        with open(auth_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return {"ok": True, "detail": f"Rotated KIMI accounts. Next account: {accounts[0].get('id', 'unknown')}"}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


# === Router 3270 Detail Page & API ===

@app.get("/api/router/models")
async def api_router_models():
    """Return virtual models config from router's config.json."""
    try:
        virtual_models = get_router_config()
        return JSONResponse(content=virtual_models)
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"api_router_models error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/router/usage")
async def api_router_usage():
    """Return token usage per role from router's /status."""
    try:
        usage = get_role_usage()
        return JSONResponse(content=usage)
    except Exception as e:
        log.error(f"api_router_usage error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/servers/{server_key}/stats/reset")
async def reset_server_stats(server_key: str):
    """Reset statistics for any server.
    For ROUTER — calls /reset-stats on the router and clears log files.
    For others — clears log files so token parser shows zero counts."""
    server_key = server_key.upper()
    if server_key not in SERVERS:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_key}")
    try:
        cfg = SERVERS[server_key]
        # For ROUTER: also call the router's own /reset-stats
        if server_key == "ROUTER":
            port = cfg.get("port", 3270)
            resp = requests.post(f"http://127.0.0.1:{port}/reset-stats", timeout=5)
            if resp.status_code != 200:
                raise HTTPException(status_code=500, detail=f"Router returned HTTP {resp.status_code}")
        # Clear log files for all servers
        base = BASE_DIR / server_key
        log_out = cfg.get("log_out", f"{server_key.lower()}-server.out.log")
        log_err = cfg.get("log_err", f"{server_key.lower()}-server.err.log")
        for log_name in (log_out, log_err):
            log_path = base / log_name
            try:
                if log_path.exists():
                    log_path.write_text("", encoding="utf-8")
                    log.info(f"Cleared {log_path}")
            except Exception as log_err:
                log.warning(f"Could not clear {log_path}: {log_err}")
        return JSONResponse(content={"ok": True, "message": f"{server_key} stats reset"})
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"reset_server_stats [{server_key}] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/detail-3270")
async def detail_3270():
    """Serve the Router 3270 detail page."""
    html_path = FRONTEND_DIR / "detail-3270.html"
    if html_path.exists():
        return FileResponse(html_path, media_type="text/html")
    return HTMLResponse(
        content=f"<html><body><h2>⚠️ detail-3270.html not found</h2>"
                f"<p>Expected at: {html_path}</p></body></html>",
        status_code=404,
    )


@app.get("/3270")
async def detail_3270_short():
    """Serve the Router 3270 detail page via short URL /3270."""
    return await detail_3270()


if __name__ == "__main__":
    # Disable default uvicorn logging config which expects a TTY; this avoids
    # AttributeError: 'NoneType' object has no attribute 'isatty' when the
    # process is started from a non-interactive environment (e.g., via the
    # Hermes executor). Setting `log_config=None` makes uvicorn fall back to a
    # minimal console logger that works everywhere.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_config=None)


# === Dashboard log endpoint ===
@app.get("/log")
def get_dashboard_log():
    """Return the dashboard log file as plain text."""
    if LOG_FILE.exists():
        return FileResponse(LOG_FILE, media_type="text/plain", headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        })
    return JSONResponse(content={"error": "Log file not found", "path": str(LOG_FILE)}, status_code=404)
