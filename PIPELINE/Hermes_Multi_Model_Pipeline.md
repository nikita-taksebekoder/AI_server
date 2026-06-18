# Hermes Multi-Model Development Pipeline

**Статус:** восстановленная чистая структурированная версия  
**Среда:** Hermes Agent  
**Цель:** организовать слаженную работу нескольких моделей внутри Hermes для разработки сайтов, интеграций, Windows-приложений, UI/UX, архитектуры, ревью, отладки и доведения кода до рабочего состояния.

---

## 0. Краткая формула

```text
AI ROUTER 3270 / Orchestrator
+ Hermes Kanban Dispatcher
+ LM Studio local builders
+ Gemini planner/reviewer
+ Router reviewer
+ Router Senior fallback
+ Codex Senior premium escalation
+ Telegram/Hermes notifications
```

Главные принципы:

```text
Pipeline first, swarm second.
Fat engine, thin skill.
Kanban is the bus and audit log.
One writer at a time.
Real verification over model claims.
```

То есть:

- pipeline управляет порядком работы;
- swarm помогает на review/architecture/design этапах;
- Kanban хранит задачи, статусы, зависимости, комментарии и историю;
- dispatcher запускает нужные worker-профили;
- код одновременно пишет один назначенный writer;
- reviewers могут работать параллельно;
- Senior подключается только по правилам эскалации;
- Codex можно заменить на Router Senior для экономии;
- пользователь получает уведомления при Senior Gate, лимитах и критических ошибках.

---

## 1. Исходные ресурсы

### 1.1. AI ROUTER 3270 — Orchestrator

```text
Provider: LOCAL
Endpoint: 127.0.0.1:3270
Model: Orchestrator
Profile: orchestrator-router-3270
Role: главный оркестратор процесса
```

AI Router 3270 используется как главный управляющий слой. Внутри роутера могут быть сильные модели в ротации, а состав моделей можно менять со временем.

Основные задачи:

- принимать задачу пользователя;
- формировать brief и acceptance criteria;
- декомпозировать работу в Kanban;
- назначать worker-профили;
- выбирать fast/main builder;
- запускать review fan-out;
- принимать decision после review fan-in;
- следить за лимитами и ошибками;
- управлять Senior Gate;
- решать, использовать Codex Senior или Router Senior.

---

### 1.2. LM Studio — локальные builder-модели

```text
Provider: LM STUDIO
Endpoint: http://127.0.0.1:1234
Hardware: RTX 5080 16 GB VRAM, 32 GB DDR5
Role: локальный исполнительский слой
```

Согласованные модели:

```text
Fast Builder:
qwen/qwen3.5-9b Q6_K
Size: около 8.28 GB
Profile: qwen-builder-fast
Use: быстрые задачи, UI-компоненты, CSS/Tailwind, простые фиксы, docs, быстрые циклы.

Main / Smart Builder:
qwen/qwen3.6-35b-a3b Q4_K_M
Size: около 22.07 GB
Profile: qwen-builder-main
Use: основная разработка, сложные фичи, интеграции, reasoning, refactor, локальный debug.
```

Правило выбора:

```text
Простая задача / быстрый fix / UI / CSS / docs
→ qwen-builder-fast

Обычная разработка / сложная фича / интеграция / refactor / debug
→ qwen-builder-main

Fast builder не справился
→ повторить на qwen-builder-main

Main builder не справился в пределах retry budget
→ Senior Gate: Router Senior или Codex Senior
```

---

### 1.3. Gemini Planner

```text
Provider: GOOGLE
Model: Gemini 3.1 flash light
Profile: gemini-planner
Role: planner / UX / summary / checklist / lightweight review
```

Лимиты Google AI Studio Free Tier:

```text
15 RPM
1 500 RPD
1 млн TPM
```

Задачи Gemini:

- product brief;
- UX-flow;
- acceptance criteria;
- чеклисты;
- лёгкое ревью;
- documentation review;
- summary состояния Kanban;
- подготовка компактного brief для других моделей.

---

### 1.4. AI Router Reviewer

```text
Provider: LOCAL
Endpoint: 127.0.0.1:3270
Model: Reviewer
Profile: router-reviewer
Role: review council / technical critique / risk analysis
Status: модель создаётся на AI Router server отдельно
```

Задачи:

- architecture review;
- technical review;
- security/edge-case critique;
- поиск противоречий;
- альтернативные решения;
- классификация проблем: critical / major / minor.

Reviewer не должен хаотично переписывать код. Его задача — находить проблемы и давать actionable feedback.

---

### 1.5. Router Senior

```text
Provider: LOCAL
Endpoint: 127.0.0.1:3270
Model: Router Senior
Profile: router-senior
Role: economy / fallback Senior
Status: модель создаётся на AI Router server отдельно
```

Используется если:

- экономим Codex;
- Codex недоступен;
- Codex-лимиты подходят к концу;
- задача сложная, но не требует premium Senior;
- включён economy pipeline.

---

### 1.6. Codex Senior

```text
Provider: OPENAI CODEX
Model: GPT-5.5
Profile: codex-senior
Role: premium Senior Engineer / debugger / final gate
```

Codex используется редко и экономно:

- production-critical изменения;
- сложный debugging;
- auth/security/payment;
- многофайловый refactor;
- финальный pre-merge/final gate;
- когда локальные модели и Router Senior не справились.

На первом этапе Codex используется через Hermes provider. Позже можно добавить Codex CLI для глубокого coding/debugging.

---

## 2. Целевая архитектура

```text
User / Hermes Chat / Telegram
        ↓
orchestrator-router-3270
        ↓
Hermes Kanban Board
        ↓
Kanban Dispatcher
        ↓
Worker Profiles
        ├── qwen-builder-fast
        ├── qwen-builder-main
        ├── gemini-planner
        ├── router-reviewer
        ├── router-senior
        └── codex-senior
        ↓
Result / Review / Fix / Senior Gate / Done
```

Kanban — единый источник правды. Worker-профили не должны координироваться через хаотичный чат; они читают и обновляют карточки.

---

## 3. Hermes profiles

Рекомендуемые профили:

```text
orchestrator-router-3270
qwen-builder-fast
qwen-builder-main
gemini-planner
router-reviewer
router-senior
codex-senior
```

### 3.1. `orchestrator-router-3270`

- provider: LOCAL;
- model: Orchestrator;
- управляет pipeline;
- создаёт Kanban tasks;
- выбирает worker;
- запускает review;
- управляет Senior Gate;
- отправляет уведомления.

### 3.2. `qwen-builder-fast`

- provider: LM STUDIO;
- model: `qwen/qwen3.5-9b Q6_K`;
- быстрые low-risk задачи;
- простые UI/CSS/docs/fix tasks;
- быстрые итерации.

### 3.3. `qwen-builder-main`

- provider: LM STUDIO;
- model: `qwen/qwen3.6-35b-a3b Q4_K_M`;
- основная разработка;
- сложные фичи;
- интеграции;
- reasoning/debug/refactor.

### 3.4. `gemini-planner`

- provider: GOOGLE;
- model: Gemini 3.1 flash light;
- brief, UX, checklist, lightweight review.

### 3.5. `router-reviewer`

- provider: LOCAL;
- model: Reviewer;
- technical/architecture/security review.

### 3.6. `router-senior`

- provider: LOCAL;
- model: Router Senior;
- economy/fallback Senior.

### 3.7. `codex-senior`

- provider: OPENAI CODEX;
- model: GPT-5.5;
- premium Senior/debug/final gate.

---

## 4. Основной workflow

```text
1. User request
2. AI ROUTER 3270 Orchestrator формирует задачу
3. Orchestrator создаёт Kanban-карточки
4. Gemini помогает с brief/checklist/UX, если нужно
5. Orchestrator выбирает qwen-builder-fast или qwen-builder-main
6. Qwen Builder выполняет реализацию
7. Hermes запускает реальные проверки
8. Qwen исправляет простые ошибки
9. Gemini + Router Reviewer делают parallel review
10. Review decision card ждёт все review tasks
11. Orchestrator принимает решение
12. Если всё хорошо → Final Verification → Done
13. Если blocked/critical → Senior Gate
14. Router Senior или Codex Senior решает сложную часть
15. Финальная проверка и отчёт
```

---

## 5. Pipeline presets

### 5.1. Premium Codex Pipeline

Для важных, production-critical задач.

```text
User task
  ↓
Orchestrator
  ↓
Kanban decomposition
  ↓
Gemini spec/checklist
  ↓
Qwen implementation
  ↓
Verification
  ↓
Gemini + Router Reviewer review
  ↓
Qwen fix cycles
  ↓
Senior Gate
  ↓
Codex Senior
  ↓
Final verification
  ↓
Done
```

Senior backend:

```text
Primary: Codex GPT-5.5
Fallback: Router Senior
```

---

### 5.2. Economy Router Senior Pipeline

Для экономии Codex.

```text
Qwen implementation
  ↓
Verification
  ↓
Review
  ↓
Qwen fixes
  ↓
Router Senior first
  ↓
Codex only if still blocked and user approves
```

Senior backend:

```text
Primary: Router Senior
Fallback: Codex after approval
```

---

### 5.3. Manual Senior Selection Pipeline

На Senior Gate пользователь выбирает:

```text
1. Передать Codex Senior
2. Передать Router Senior
3. Дать Qwen ещё 1 цикл
4. Дать Qwen ещё 2 цикла
5. Остановиться / изменить стратегию
```

---

### 5.4. Economy Fully Autonomous Pipeline

Для автономной работы без участия пользователя до лимита.

```text
Qwen / Router Senior cycles
  ↓
до решения задачи
  ↓
или до 6 автономных циклов
  ↓
Human Gate
```

После 6 циклов система спрашивает:

```text
Задача не решена за 6 циклов.
Что делать?
1. Передать GPT Codex Senior
2. Сделать ещё 6 автономных циклов
3. Остановиться
4. Изменить стратегию / дать новые инструкции
```

---

## 6. Senior Gate

Senior Gate срабатывает, если:

1. Qwen не справился после retry budget.
2. Economy autonomous pipeline дошёл до 6 циклов.
3. Reviewer нашёл critical issue.
4. Задача касается auth/security/payment.
5. Задача затрагивает много файлов и риск регрессии высокий.
6. Build/test/typecheck/lint стабильно падают.
7. Worker сам пометил задачу как blocked.
8. Orchestrator видит риск архитектурного слома.
9. Пользователь вручную отправил задачу Senior.

Режимы:

```text
senior_approval_mode:
  auto
  human_required

senior_backend:
  codex_first
  router_first
  manual

codex_economy_mode:
  on
  off

qwen_retry_budget:
  default: 2
  economy_autonomous: 6
  user_extend: +6 cycles
```

---

## 7. Senior Escalation Summary

Перед передачей Senior пользователь может получить summary в Hermes Chat и Telegram.

```markdown
# Senior Escalation Request

## Task
Какая задача.

## Current Status
Что сделано.

## Why Escalation
Почему Orchestrator считает, что нужен Senior.

## Attempts
Сколько циклов Qwen / Router Senior уже было.

## Failed Checks
Какие build/test/lint/typecheck упали.

## Verification Output
Краткий реальный output ошибок.

## Risk Level
low / medium / high / critical

## Recommended Senior
Codex Senior / Router Senior

## Options
1. APPROVE_CODEX
2. APPROVE_ROUTER_SENIOR
3. RETRY_QWEN_1
4. RETRY_QWEN_2
5. RUN_6_MORE_AUTONOMOUS_CYCLES
6. STOP
7. CHANGE_STRATEGY
```

---

## 8. Compact Codex Escalation Brief

Codex должен получать компактный пакет, а не всю историю.

```markdown
# Codex Escalation Brief

## Problem
Что не работает.

## Goal
Что должно быть исправлено.

## Repo Context
Краткое описание проекта и важных файлов.

## Relevant Files
- path/to/file1
- path/to/file2

## Actual Error Output
Реальная ошибка сборки/теста/логов.

## Attempts Already Made
Что уже пробовали Qwen / Orchestrator / Router Senior.

## Constraints
Что нельзя менять.

## Required Verification
Какие команды должны пройти.

## Expected Output
Патч / объяснение / тесты / финальный diff.
```

---

## 9. Kanban lifecycle

Рекомендуемые стадии:

```text
Backlog
  ↓
Spec
  ↓
Architecture
  ↓
Design
  ↓
Implementation
  ↓
Local Verification
  ↓
Swarm Review
  ↓
Fixes
  ↓
Senior Gate / Escalation
  ↓
Final Verification
  ↓
Done
```

Operational status set:

```text
TODO
READY
IN_PROGRESS
REVIEW
FIXES
BLOCKED
SENIOR_GATE
SENIOR_IN_PROGRESS
FINAL_VERIFICATION
DONE
CANCELLED
```

---

## 10. Kanban task template

```markdown
# Task: <short title>

## Type
spec / architecture / design / implementation / integration / test / review / debug / senior-escalation

## Pipeline Mode
premium_codex / economy_router_senior / manual_senior / economy_autonomous

## Goal
Что нужно сделать.

## Workspace
Рабочая папка проекта.

## Context
Проект, ограничения, ссылки на файлы, текущий стек.

## Acceptance Criteria
Что значит “готово”.

## Assigned Profile
orchestrator-router-3270 / qwen-builder-fast / qwen-builder-main / gemini-planner / router-reviewer / router-senior / codex-senior

## Writer Policy
single-writer / review-only / senior-only

## Model Preference
Orchestrator / Fast Qwen / Main Qwen / Gemini / Reviewer / Router Senior / Codex Senior

## Constraints
Что нельзя менять.

## Autonomy
Full autonomy in workspace. Global commands allowed when necessary for project implementation. Do not harm system, network, AI Router, or user data.

## Verification
Команды запуска, тесты, сборка, ручная проверка.

## Attempt Count
0 / 1 / 2 / ... / 6

## Result
Что сделано.

## Review Notes
Что нашли reviewers.

## Decision
Accepted / Needs Fix / Blocked / Senior Gate / Escalate to Codex / Escalate to Router Senior / Done.
```

---

## 11. Параллельность

Стартовая политика:

```text
1 writer at a time
2–3 reviewers in parallel
Senior only on escalation
```

Разрешено:

- parallel review;
- parallel brief/checklist;
- fan-out/fan-in через Kanban parent links;
- последовательные fix cycles.

Запрещено на старте:

- параллельное редактирование одних и тех же файлов;
- несколько writers в одной области проекта;
- хаотичные изменения без Kanban task;
- автоматическое подключение Codex без условий.

---

## 12. Полная автономность

### 12.1. В рабочей папке

```text
В указанной рабочей папке проекта воркеры имеют полную автономность.
```

Они могут:

- читать файлы;
- создавать файлы;
- редактировать файлы;
- удалять файлы, если это нужно для задачи;
- запускать install/build/test/lint/dev-команды;
- устанавливать зависимости;
- создавать локальные скрипты;
- выполнять команды, необходимые для реализации проекта;
- работать без постоянного approval на каждое действие.

### 12.2. Вне рабочей папки

Вне рабочей папки можно исполнять глобальные команды, если они нужны для реализации проекта:

- проверить версии Node/Python/Git/CLI tools;
- установить нужный CLI или зависимость;
- проверить доступность порта;
- проверить системную зависимость;
- использовать package manager;
- проверить сеть;
- работать с git;
- подготовить окружение проекта.

### 12.3. Красные линии

Абсолютное табу:

```text
Не вредить системе.
Не ломать окружение.
Не удалять пользовательские данные.
Не останавливать AI Router.
Не убивать интернет.
Не делать destructive system-level операции без явной необходимости.
```

Созидательный принцип:

```text
Наша задача — созидать и делать мир лучше классными проектами.
```

---

## 13. Pipeline для разработки сайта

```text
1. Product brief
2. Design exploration
3. Architecture decision
4. Implementation
5. Local verification
6. Swarm review
7. Fixes
8. Senior Gate, если нужно
9. Final verification
10. Done
```

Роли:

- Orchestrator — декомпозиция и управление;
- Gemini — UX/brief/checklist;
- qwen-builder-fast — быстрые UI/CSS/docs tasks;
- qwen-builder-main — основная реализация;
- Router Reviewer — technical/architecture review;
- Router Senior/Codex Senior — сложные блокеры.

---

## 14. Pipeline для интеграций

```text
API research
  ↓
Minimal working example
  ↓
Local mock
  ↓
Real API integration
  ↓
Error handling
  ↓
Secrets/env handling
  ↓
Test script
  ↓
Review
  ↓
Senior Gate for critical integrations
```

Codex/Router Senior особенно важны для:

- OAuth;
- auth;
- payments;
- webhooks;
- concurrency;
- filesystem operations;
- Windows-specific edge cases.

---

## 15. Pipeline для Windows-приложений

Возможные варианты:

- Tauri;
- Electron;
- Python + Qt/PySide;
- .NET / WPF / WinUI.

Роли:

- Orchestrator — выбор подхода;
- Gemini — UX/screens/user flow;
- qwen-builder-fast — простые UI pieces;
- qwen-builder-main — структура и код;
- Router Reviewer — сравнение технологий;
- Senior — packaging/debugging/сложные Windows issues.

---

## 16. Правила снижения ошибок

1. Маленькие Kanban-карточки.
2. Acceptance criteria перед кодом.
3. Реальная проверка вместо словесной уверенности модели.
4. Один writer на одну область проекта.
5. Review fan-out / decision fan-in.
6. Senior Gate только по условиям.
7. Codex получает компактный brief.
8. Финальный результат подтверждается build/tests/logs/API/browser check/diff.

Главное правило:

```text
Не верить словам модели о том, что код работает.
Верить только проверенному артефакту: build, tests, logs, browser/API check, diff.
```

---

## 17. Codex Budget Policy

### Level 0 — No Codex

Идеи, дизайн, boilerplate, простые компоненты, простые bugfixes.

### Level 1 — Codex Review Only

Codex получает краткое описание, diff, ошибки тестов и вопрос “что критично исправить?”.

### Level 2 — Codex Targeted Fix

Codex получает конкретный failing test/build error, список файлов и ограничения.

### Level 3 — Codex Autonomous Task

Только сложная фича, production bug, долгий debugging, multi-file refactor.

### Level 4 — Codex Final Gate

Security review, architecture review, production-readiness check перед важным релизом.

---

## 18. Telegram + Hermes notifications

Уведомления идут в:

```text
1. Hermes Chat
2. Telegram Bot / home channel
```

Уведомлять обязательно, если:

1. произошла критическая ошибка;
2. упали лимиты Gemini / Codex / AI Router / OpenRouter;
3. AI Router недоступен;
4. LM Studio недоступен;
5. Codex недоступен;
6. задача застряла;
7. превышено 6 автономных циклов;
8. dispatcher не может запустить worker;
9. worker repeatedly fails;
10. build/test/lint падают много раз подряд;
11. требуется Senior decision;
12. проектный сервер упал;
13. интернет/сеть недоступны;
14. есть риск повредить систему или выйти за безопасный scope.

---

## 19. Advisor Trio — DeepSeek + Qwen Web + Kimi/GLM

Advisor Trio — это экологичный advisory-layer из web-chat прокси, а не постоянные worker-писатели кода.

```text
Advisor Trio = DeepSeek Advisor + Qwen Web Advisor + Kimi/GLM Advisor
```

Цель Trio:

- получить независимые мнения по сложному решению;
- найти риски до реализации;
- сравнить архитектурные варианты;
- помочь при review conflict;
- помочь перед Senior Gate;
- сформировать гибридное решение из лучших идей.

### 19.1. Роли Trio

#### DeepSeek Advisor

Подходит для:

```text
reasoning
debug
risk analysis
алгоритмы
поиск скрытых проблем
почему решение может не сработать
```

Кандидаты:

```text
deepseek-reasoner
deepseek-r1
deepseek-v4-pro
deepseek-reasoner-search
```

#### Qwen Web Advisor

Подходит для:

```text
практическая реализация
кодовые паттерны
frontend/backend решения
tool-use / agentic coding идеи
интеграции
UI + code suggestions
```

Кандидаты:

```text
qwen3.7-max
qwen3.7-plus
qwen3-coder-plus
```

#### Kimi / GLM Advisor

Подходит для:

```text
альтернативная архитектура
длинный контекст
продуктовое мышление
UX-варианты
research/deepresearch
```

Кандидаты:

```text
kimi-k2.5-thinking
glm-5-thinking
glm-5-deepresearch
```

### 19.2. Где использовать Trio

Хорошие места:

```text
Spec / Architecture stage
Review conflict
Before Senior Gate
After 6 failed autonomous cycles
Complex integration design
Windows app architecture
Security/auth/payment design
Major refactor planning
```

Trio можно вставлять как optional stage:

```text
Spec → Advisor Trio → Architecture
Review conflict → Advisor Trio → Decision
Before Senior Gate → Advisor Trio → Senior Decision
After 6 failed cycles → Advisor Trio → Human Gate
```

### 19.3. Где Trio не использовать

Не использовать для:

```text
простых CSS-правок
маленьких README/docs задач
рутинных компонентов
каждого мелкого bugfix
массового кода
бесконечных циклов
полной передачи репозитория
секретов, токенов, .env, auth-файлов
```

Trio — это точечный совет, а не бесплатные вечные workers.

### 19.4. Экологичная политика использования

```text
1. Trio Advisors вызываются только для medium/high-risk задач.
2. Не больше 1 раунда на decision point.
3. Не отправлять полный репозиторий.
4. Отправлять только compact human-readable brief.
5. Не отправлять секреты, токены, .env, auth-файлы.
6. Не запускать спам/циклический опрос.
7. Не использовать Trio для рутинной генерации кода.
8. Ответы сохранять в Kanban comments или artifacts.
9. Orchestrator всегда делает final synthesis.
10. Если один advisor недоступен — продолжаем с оставшимися.
```

### 19.5. Жёсткое правило формата prompt для Trio

Инструкция/промпт для Trio Advisors должна выглядеть человечно.

Сообщение должно быть:

- понятным;
- структурированным;
- спокойным;
- человеческим;
- без машинного мусора;
- без огромного количества спецсимволов;
- без странных иероглифов;
- без перегруженных системных маркеров;
- без JSON, если это не нужно;
- без нечитаемых nested blocks;
- без дампа внутренней Kanban/engine-служебки.

Главная идея:

```text
Это должно выглядеть как нормальное человеческое ТЗ для сильного консультанта.
```

Orchestrator не должен формировать сообщение для Trio “как получится”. Он должен использовать жёсткий шаблон:

```text
templates/trio-advisor-request.md
```

### 19.6. Шаблон human-readable prompt для Trio

```markdown
# Нужен совет по реализации

Привет. Мы проектируем или реализуем задачу в Hermes-пайплайне.
Нужно независимое мнение: проверь план, найди риски и предложи более сильное решение.

## Задача

Коротко: что нужно сделать.

## Контекст

Кратко о проекте, без лишней внутренней служебной информации.

## Текущий план

Как мы собираемся реализовать задачу сейчас.

## Ограничения

Что нельзя менять или ломать.

## Вопросы к тебе

1. Насколько хороший этот план?
2. Где главные риски?
3. Что лучше изменить?
4. Какой минимальный план реализации ты предлагаешь?
5. Чего точно не стоит делать?

## Ответь, пожалуйста, в таком формате

1. Краткий вердикт
2. Главные риски
3. Лучший подход
4. Минимальный план реализации
5. Что не делать
```

### 19.7. Запреты для Trio prompt

Жёстко запрещено отправлять:

```text
API keys
tokens
cookies
auth.json
session/tokens.json
.env
passwords
private credentials
полные browser profiles
полные логи с секретами
полный репозиторий без необходимости
```

Если нужно упомянуть секрет или конфиг:

```text
заменить на [REDACTED]
```

### 19.8. Graceful degradation

Если один advisor недоступен:

```text
Trio step не падает целиком.
Orchestrator продолжает с двумя мнениями.
В synthesis отмечает, кто не ответил.
```

Если ответил только один advisor:

```text
Orchestrator использует одно мнение как advisory input.
Pipeline не блокируется.
Бесконечных retry нет.
```

Если все Trio Advisors недоступны:

```text
Advisor Trio step пропускается.
Pipeline продолжается без Trio.
Orchestrator пишет в Kanban comment:
"Trio Advisors unavailable, continuing without advisory layer."
```

Если задача critical, после полной недоступности Trio можно перейти к:

```text
Router Senior
Human Gate
Codex Senior, если разрешено политикой
```

### 19.9. Retry / timeout policy

```text
1 короткая попытка на advisor.
1 optional retry только если ошибка похожа на transient network timeout.
Не больше 2 попыток на advisor.
Нет бесконечных повторов.
Timeout: 30–90 секунд на advisor.
Если не ответил: mark unavailable and continue.
```

### 19.10. Trio synthesis template

После ответов Trio Orchestrator делает synthesis:

```markdown
# Trio Advisors Synthesis

## Advisor Availability

- DeepSeek: answered / unavailable
- Qwen: answered / unavailable
- Kimi/GLM: answered / unavailable

## Key Ideas

Кратко лучшие идеи каждого.

## Agreement

В чём советники совпали.

## Disagreement

Где мнения разошлись.

## Risks

Главные риски.

## Final Hybrid Decision

Что берём в итоговый план.

## What We Reject

Что не берём и почему.

## Next Step

qwen-builder-fast / qwen-builder-main / router-senior / codex-senior / human gate
```

### 19.11. Kanban integration

Добавить task type:

```text
advisor-review
```

В Kanban хранить:

```text
Trio request summary
DeepSeek answer summary
Qwen answer summary
Kimi/GLM answer summary
Orchestrator synthesis
Final decision
Advisor availability
```

Полные длинные ответы можно хранить как artifact/log, а в Kanban оставлять короткое summary.

---

## 20. Идеи из `tonbistudio/hermes-multi-agent-workflow`

Репозиторий был проанализирован как архитектурный reference:

```text
https://github.com/tonbistudio/hermes-multi-agent-workflow
```

Проверенный reference state:

```text
Commit inspected: fa4a9de
python -m cli.triage validate → OK
python -m unittest discover -s tests → 12 tests OK
```

Берём идеи:

- Fat engine, thin skill;
- Kanban is the bus and audit log;
- config as source of truth;
- role → profile mapping;
- TaskSpec abstraction;
- fan-out / fan-in через parent links;
- persistent workspace for coding tasks;
- human gate action handler pattern;
- validate/scaffold CLI;
- scope rails as Markdown;
- cost/limit gate concept;
- unit tests for deterministic pipeline logic.

Не берём напрямую:

- `sources → scouts → intake` как основной flow;
- triage/dedup/scoring как главный coding pipeline;
- прямой SQLite writer без проверки схемы Hermes Kanban;
- правило “never auto-approve” в чистом виде, потому что у нас есть economy autonomous mode до 6 циклов.

---

## 21. Будущий `pipeline.yaml`

В будущем pipeline должен быть конфигурируемым:

```yaml
name: hermes-dev-pipeline
board: ai-server-dev
workspace_root: C:/Users/Forestsnow/workspace/AI_server

roles:
  orchestrator: orchestrator-router-3270
  fast_builder: qwen-builder-fast
  main_builder: qwen-builder-main
  planner: gemini-planner
  reviewer: router-reviewer
  router_senior: router-senior
  codex_senior: codex-senior

senior:
  approval_mode: human_required
  backend: codex_first
  economy_mode: false
  qwen_retry_budget: 2
  autonomous_cycle_limit: 6
```

Цель:

```text
pipeline.yaml = source of truth
engine = deterministic logic
prompts = role behavior
rails = safety and scope
Kanban = bus/audit log
tests = protection from regressions
```

---

## 22. Future file layout

```text
PIPELINE/
  CREATION_TODO.md
  Hermes_Multi_Model_Pipeline.md
  pipeline.yaml
  engine/
    config.py
    task_specs.py
    pipeline_engine.py
    routing.py
    senior_gate.py
    kanban_adapter.py
  cli/
    pipeline.py
  rails/
    global-autonomy.md
    workspace-safety.md
    coding.md
    integration.md
    windows-app.md
    senior-escalation.md
  prompts/
    orchestrator.md
    qwen-builder-fast.md
    qwen-builder-main.md
    gemini-planner.md
    router-reviewer.md
    router-senior.md
    codex-senior.md
  templates/
    kanban-task.md
    senior-escalation-summary.md
    codex-brief.md
    final-report.md
  tests/
    test_config.py
    test_task_specs.py
    test_pipeline_engine.py
    test_senior_gate.py
```

---

## 23. Definition of Done

Задача считается готовой, если:

1. Есть acceptance criteria.
2. Код или артефакт реально создан.
3. Запущены применимые проверки.
4. Ошибки исправлены или явно задокументированы.
5. Review выполнен Orchestrator/Reviewer/Gemini или Senior.
6. Kanban-карточка обновлена.
7. Есть краткое описание результата.
8. Если задача critical — пройден Senior Gate или явно принято решение его не использовать.

---

## 24. Итоговая формула

```text
AI ROUTER 3270 = Orchestrator процесса
Hermes Kanban = единый источник правды
qwen/qwen3.5-9b Q6_K = fast local builder
qwen/qwen3.6-35b-a3b Q4_K_M = main smart local builder
Gemini = planner / UX / summary / checklist
Router Reviewer = критика / альтернативы / risks
Advisor Trio = DeepSeek + Qwen Web + Kimi/GLM advisory council
Router Senior = economy/fallback Senior
Codex Senior = premium/debug/final gate
Telegram + Hermes Chat = control plane
```

Главное:

```text
Один назначенный исполнитель пишет код.
Остальные помогают думать, проверять, критиковать и улучшать.
Код считается рабочим только после реальной проверки.
```
