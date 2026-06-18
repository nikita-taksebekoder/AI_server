# AI Server — Quick Start

**Workspace:** `C:\Users\Forestsnow\workspace\AI_server\`

## Сервисы и порты

| Порт | Сервис | Тип | Папка |
|---|---|---|---|
| 8000 | **Dashboard** | FastAPI (Python) | `Dashboard/` |
| 3264 | **QWEN** | Node.js | `QWEN/` |
| 9655 | **DEEPSEEK** | Node.js | `DEEPSEEK/` |
| 3270 | **ROUTER** | Node.js | `ROUTER/` |
| 3265 | **KIMI** | Node.js | `KIMI/` |

## Запуск

### Основной способ: DashboardLauncher.exe

```
C:\Users\Forestsnow\workspace\AI_server\Dashboard\dist\DashboardLauncher\DashboardLauncher.exe
```

Лаунчер автоматически:
1. Проверяет порты серверов — не запускает повторно если уже работают
2. Запускает `backend.py` из source-папки (через config.json)
3. Ждёт готовности порта 8000
4. Открывает браузер на `http://127.0.0.1:8000`

### Ручной запуск (для разработки)

```bash
# Dashboard
cd C:\Users\Forestsnow\workspace\AI_server\Dashboard
python backend.py
# или
uvicorn backend:app --host 127.0.0.1 --port 8000
```

### Автозапуск Windows

Добавить `DashboardLauncher.exe` в автозапуск через **WinToys**.

## Проверка

```bash
# Все порты
netstat -ano | grep -E "LISTENING.*:(8000|3264|9655|3270|3265) "

# Dashboard API
curl -s http://127.0.0.1:8000/api/servers

# Отдельные сервисы
curl http://127.0.0.1:3264/api/health      # QWEN
curl http://127.0.0.1:9655/health          # DEEPSEEK
curl http://127.0.0.1:3270/health          # ROUTER
curl http://127.0.0.1:3265/health          # KIMI
```

## Остановка

```bash
taskkill /f /im DashboardLauncher.exe
taskkill /f /im python.exe
taskkill /f /im node.exe
```

## Документация по сервисам

| Сервис | README | Progress | Bugs |
|---|---|---|---|
| Dashboard | `Dashboard/README.md` | `Dashboard/PROGRESS.md` | `Dashboard/BUGS.md` |
| DEEPSEEK | `DEEPSEEK/README.md` | `DEEPSEEK/PROGRESS.md` | `DEEPSEEK/BUGS.md` |
| QWEN | `QWEN/README.md` | `QWEN/PROGRESS.md` | `QWEN/BUGS.md` |
| ROUTER | `ROUTER/README.md` | `ROUTER/PROGRESS.md` | `ROUTER/BUGS.md` |
| KIMI | `KIMI/README.md` | `KIMI/PROGRESS.md` | `KIMI/BUGS.md` |
| Pipeline | `PIPELINE/README.md` | `PIPELINE/PROGRESS.md` | `PIPELINE/BUGS.md` |

## Архитектура

```
User / Telegram
    ↓
Hermes Agent (gateway)
    ↓
AI ROUTER 3270 (Orchestrator)
    ↓
Local Qwen (LM Studio :1234) — main builder
    ↓
Free models (QWEN, DEEPSEEK, KIMI) — web proxies
```

## Ключевые файлы

- `Dashboard/backend.py` — FastAPI backend (source)
- `Dashboard/launcher.py` — лаунчер (собирается в exe)
- `Dashboard/config.json` — `source_dir` для source-linked launcher
- `Dashboard/frontend/index.html` — UI дашборда
- `ROUTER/config.json` — конфигурация роутера (модели, лимиты)
- `DEEPSEEK/auth-pool/` — пул аккаунтов DeepSeek
- `Hermes gateway settings/gateway_config.md` — конфигурация Hermes gateway

## Hermes Gateway

Gateway работает как Scheduled Task `Hermes_Gateway` (автозапуск при входе).

```bash
hermes gateway install    # установить
hermes gateway start      # запустить
hermes gateway stop       # остановить
hermes gateway restart    # перезапустить
hermes gateway status     # статус
```

Конфигурация:
- `.env`: `C:\Users\Forestsnow\AppData\Local\hermes\.env`
- `config.yaml`: `C:\Users\Forestsnow\AppData\Local\hermes\config.yaml`
- Логи: `C:\Users\Forestsnow\AppData\Local\hermes\logs\gateway.log`

## Router quota-safety baseline

- ROUTER 1 (3270) — Orchestrator
- Safe diagnostics: `/health`, `/config`, `/status`, `/v1/models` — не расходуют квоту
- Upstream только на `POST /v1/chat/completions`
- Guards: `maxFallbackAttempts=1`, `fallbackOnRateLimit=false`, `maxRequestsPerWindow=3/min`, `minRequestIntervalMs=15000`, `roleRetryCooldownMs=60000`, `maxCompletionTokens=4096`, `maxEstimatedPromptTokens=90000`
