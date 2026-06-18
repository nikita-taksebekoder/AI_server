# Dashboard — Bugs & Known Issues

## Решённые

### DashboardLauncher.exe использовал старую версию backend
**Проблема:** `.exe` содержал упакованную внутри старую версию `backend.py`. После изменений в source — запускалась старая версия.
**Решение:** v4.0 — source-linked launcher. `backend.py` читается напрямую из source-папки через `config.json`.

### Копирование backend.py в dist после каждого изменения
**Проблема:** При каждом изменении нужно было копировать `backend.py` и `frontend/` в `dist/DashboardLauncher/`.
**Решение:** v4.0 — копирование не нужно. Правишь source → перезапускаешь `.exe`.

## Известные ограничения

### Пересборка exe при изменении launcher.py
Если меняется логика запуска (`launcher.py`), нужно пересобрать exe:
```bash
cd AI_server/dashboard
taskkill /f /im DashboardLauncher.exe
pyinstaller --onedir -y --name DashboardLauncher launcher.py
cp config.json dist/DashboardLauncher/
```

### Файлы заблокированы запущенным процессом
При пересборке exe нужно сначала убить `DashboardLauncher.exe`, иначе файлы заблокированы.

### Frontend кэшируется браузером
После изменения `index.html` — hard-refresh (Ctrl+Shift+R) или incognito.
