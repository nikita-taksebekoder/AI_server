# PIPELINE — Hermes Multi-Model Development Pipeline

**Статус:** проектная концепция / operating model
**Среда:** Hermes Agent

## Что это

Концепция организации слаженной работы нескольких моделей внутри Hermes для разработки сайтов, интеграций, Windows-приложений, UI/UX, архитектуры, ревью и отладки.

## Архитектура: Pipeline-controlled Swarm

```
User / Hermes Chat / Telegram
    ↓
AI ROUTER 3270 — Orchestrator
    ↓
Hermes Kanban Board
    ↓
Kanban Dispatcher
    ↓
Worker Profiles
    ├── qwen-builder (LM Studio :1234)
    ├── gemini-planner (Google API)
    ├── router-reviewer (Router 3270)
    ├── codex-senior (OpenAI Codex)
    └── router-senior (Router 3270)
```

## Принципы

- **Pipeline first, swarm second** — pipeline задаёт порядок, swarm подключается внутри этапов
- **Fat engine, thin skill** — детерминистическая логика в конфиге/коде, не в prose-prompts
- **Kanban is the bus** — Kanban хранит задачи, зависимости, статусы и результаты

## Роли моделей

| Компонент | Роль | Частота | Писать код? |
|---|---|---|---|
| AI ROUTER 3270 | Orchestrator | часто | иногда |
| Local Qwen 35B | Main builder | часто | да |
| Gemini Flash Light | Planner/UX/Summary | умеренно | простой |
| Router Review Models | Swarm review | часто | иногда |
| Codex Plus | Senior/Debug/Final | редко | сложное |

## Kanban lifecycle

```
Backlog → Spec → Architecture → Design → Implementation
    → Local Verification → Swarm Review → Fixes
    → Senior Gate → Final Verification → Done
```

## Политика автономности

- В рабочей папке проекта воркеры имеют полную автономность
- Красные линии: не вредить системе, не ломать окружение, не останавливать AI Router
- 1 writer at a time, 2-3 reviewers in parallel, Senior only on escalation

## Подробная документация

- `PIPELINE/Hermes_Multi_Model_Pipeline.md` — полная концепция
- `PIPELINE/CREATION_TODO.md` — план реализации
