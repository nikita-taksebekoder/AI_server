# AI Server Dashboard — Документация

**Версия:** 4.0 (Source-Linked Launcher)
**Дата:** 2026-06-18

## Обзор

FastAPI-приложение для мониторинга и управления AI-серверами:
- **QWEN** — Qwen API-совместимый сервер (порт 3264)
- **DEEPSEEK** — DeepSeek API-совместимый сервер (порт 9655)
- **ROUTER** — AI Router 3270 с виртуальными моделями (порт 3270)
- **KIMI** — Kimi API-совместимый сервер (порт 3265)

## Архитектура запуска (v4.0)

DashboardLauncher.exe читает `config.json` с `source_dir` и запускает `backend.py` напрямую из указанной папки. Никакого копирования файлов.

```
DashboardLauncher.exe
  ├── Автозапуск AI-серверов (QWEN, DEEPSEEK, ROUTER, KIMI)
  ├── Запуск backend.py из source_dir (через config.json)
  ├── Ожидание готовности backend на порту 8000
  └── Открытие браузера на http://127.0.0.1:8000
```

### Структура

```
AI_server/Dashboard/          ← source (разработка)
├── backend.py                ← FastAPI backend — правишь здесь
├── launcher.py               ← тонкий лаунчер → PyInstaller (собирается один раз)
├── config.json               ← {"source_dir": "C:\\Users\\Forestsnow\\workspace\\AI_server\\Dashboard"}
├── frontend/
│   ├── index.html            ← правишь здесь
│   └── detail-3270.html
├── assets/icon.ico
└── dist/DashboardLauncher/   ← готовый лаунчер
    ├── DashboardLauncher.exe ← собран один раз
    ├── _internal/            ← Python runtime (не трогать)
    └── config.json           ← копия с source_dir
```

> **Примечание:** `backend.py` и `frontend/` НЕ копируются в dist/. Launcher запускает их напрямую из source-папки.

## Способы запуска

### 1. Основной: DashboardLauncher.exe
```
C:\Users\Forestsnow\workspace\AI_server\Dashboard\dist\DashboardLauncher\DashboardLauncher.exe
```

### 2. Ручной запуск (для разработки)
```bash
cd C:\Users\Forestsnow\workspace\AI_server\Dashboard
python backend.py
# или
uvicorn backend:app --host 127.0.0.1 --port 8000
```

### Автозапуск Windows
Добавить exe в автозапуск через **WinToys**.

## Как вносить правки

### Backend или Frontend
1. Отредактировать файл в source-папке
2. Перезапустить DashboardLauncher.exe
3. Всё — копировать ничего не нужно

### Перенос source-папки
1. Открыть `config.json` рядом с .exe
2. Поменять `source_dir` на новый путь
3. Перезапустить .exe

### Launcher (только при изменении логики запуска)
```bash
cd C:\Users\Forestsnow\workspace\AI_server\Dashboard
taskkill /f /im DashboardLauncher.exe
pyinstaller --onedir -y --name DashboardLauncher launcher.py
cp config.json dist/DashboardLauncher/
```

## API Endpoints

### Главная страница
| Метод | Путь | Описание |
|---|---|---|
| GET | `/` | Главная страница дашборда |
| GET | `/log` | Лог дашборда (text/plain) |

### Управление серверами
| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/servers` | Статус всех серверов |
| POST | `/api/servers/all/start` | Запустить все серверы |
| POST | `/api/servers/all/stop` | Остановить все серверы |
| POST | `/api/servers/{key}/start` | Запустить один сервер |
| POST | `/api/servers/{key}/stop` | Остановить один сервер |
| GET | `/api/servers/{key}/logs` | Логи сервера |
| GET | `/api/servers/{key}/info` | Информация о сервере |
| GET | `/api/servers/{key}/tokens` | Токены сервера |
| POST | `/api/servers/{key}/stats/reset` | Сброс статистики |

### Router 3270
| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/router/models` | Список виртуальных моделей |
| GET | `/api/router/usage` | Токены и запросы по ролям |
| GET | `/detail-3270` | Детальная страница |

### Аккаунты
| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/accounts/{key}` | Список аккаунтов |
| POST | `/api/accounts/{key}/add` | Добавить аккаунт |
| POST | `/api/accounts/{key}/add-manual` | Добавить вручную |
| POST | `/api/accounts/{key}/rotate` | Ротация аккаунта |
| POST | `/api/rotate-key/{key}` | Ротация ключа |

### Отладка
| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/debug/paths` | Диагностика путей |

## Конфигурация серверов (в backend.py)

| Сервер | Порт | Launcher | Health endpoint |
|---|---|---|---|
| QWEN | 3264 | QWEN/QwenServerLauncher.exe | /models |
| DEEPSEEK | 9655 | DEEPSEEK/DeepseekServerLauncher.exe | /models |
| ROUTER | 3270 | ROUTER/RouterServerLauncher.exe | /models |
| KIMI | 3265 | KIMI/kimi-launcher.exe | /health |

## Порты

| Порт | Сервис |
|---|---|
| 8000 | Dashboard (FastAPI) |
| 3264 | QWEN |
| 9655 | DEEPSEEK |
| 3270 | ROUTER |
| 3265 | KIMI |

## Логи и диагностика

- **Backend log:** `Dashboard/logs/dashboard.log`
- **Launcher log:** `Dashboard/dist/DashboardLauncher/logs/launcher.log`
- **В браузере:** кнопка "📋 LOG" → `/log`
- **Debug paths:** `http://127.0.0.1:8000/api/debug/paths`

## Чеклист после изменений

```bash
# Проверка backend синтаксиса
python -m py_compile backend.py

# Проверка портов
netstat -ano | grep -E "LISTENING.*:(8000|3264|9655|3270|3265) "

# Проверка API
curl -s http://127.0.0.1:8000/api/servers

# Проверка frontend
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/
```

## Типовые ошибки

| Симптом | Решение |
|---|---|
| `FileNotFoundError: backend.py not found` | Проверить `source_dir` в `config.json` |
| Порт 8000 занят | Если работает — открыть в браузере. Если нужен рестарт — убить процесс |
| Frontend не обновился | Ctrl+Shift+R или incognito |

## Что нельзя делать

- Нельзя редактировать файлы в `_internal/` — это Python runtime
- Нельзя убивать процессы вслепую — сначала определить какой процесс держит порт
- Нельзя менять порты без синхронного обновления launcher.py и backend.py

## Безопасность

- CORS открыт для всех источников (`*`)
- Секреты маскируются в логах
- Доступ только с localhost (127.0.0.1)
