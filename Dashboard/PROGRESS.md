# Dashboard — Progress

## 2026-06-18: Source-Linked Launcher v4.0

### Концепция
`.exe` читает `config.json` с `source_dir` и запускает `backend.py` напрямую из указанной папки. Никакого копирования файлов.

### Ключевые изменения
1. **`launcher.py` v4.0** — читает `config.json`, запускает `backend.py` из `source_dir`
2. **`config.json`** — `{"source_dir": "C:\\Users\\Forestsnow\\workspace\\AI_server\\dashboard"}`
3. **Нет копирования** — `backend.py` и `frontend/` не копируются в `dist/`
4. **Перенос папки** — поменять `source_dir` в `config.json`

### Структура
```
AI_server/dashboard/          ← source (разработка)
├── backend.py                ← правишь здесь
├── launcher.py               ← собирается в exe один раз
├── config.json               ← source_dir
├── frontend/
│   ├── index.html
│   └── detail-3270.html
└── dist/DashboardLauncher/   ← готовый лаунчер
    ├── DashboardLauncher.exe ← собран один раз
    ├── _internal/            ← Python runtime
    └── config.json           ← копия с source_dir
```

## 2026-06-17: Auth-pool интеграция

- DEEPSEEK: поддержка auth-pool в Dashboard
- KIMI: добавление аккаунтов и ротация через Dashboard
- QWEN: чипы аккаунтов, кнопки "+Add" и "🔄 Rotate"

## 2026-06-17: Перенос в AI_server/

Dashboard перенесён из `workspace/dashboard/` в `workspace/AI_server/Dashboard/`.
`config.json` обновлён с новым `source_dir`.
