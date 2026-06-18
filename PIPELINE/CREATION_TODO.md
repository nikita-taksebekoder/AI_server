# CREATION_TODO.md — Hermes Full Kanban Dispatcher Multi-Model Pipeline

**Статус:** план реализации
**Режим:** сначала планирование и диагностика, затем настройка только после явного разрешения
**Цель:** собрать в Hermes полноценную dispatcher-based multi-model систему разработки: Orchestrator + Kanban + worker profiles + reviewers + switchable Senior escalation.

---

## 0. Финальная целевая архитектура

```
User / Hermes Chat / Telegram
        ↓
orchestrator-router-3270
        ↓
Hermes Kanban Board
        ↓
Kanban Dispatcher
        ↓
Worker Profiles
        ├── qwen-builder
        ├── gemini-planner
        ├── router-reviewer
        ├── codex-senior
        └── router-senior
        ↓
Result / Review / Fix / Senior Gate / Done
```

Главные принципы:

```
Pipeline first, swarm second.
Fat engine, thin skill.
Kanban is the bus and audit log.
```

- pipeline управляет порядком работы;
- Kanban хранит задачи, зависимости, статусы и результаты;
- dispatcher запускает нужные профили;
- один writer пишет код;
- reviewers могут работать параллельно;
- Senior подключается по правилам эскалации;
- Codex можно заменить на Router Senior для экономии;
- пользователь получает уведомления при senior gate, лимитах и критических ошибках;
- детерминированная логика должна жить в конфиге/engine-коде, а не только в prose-prompts;
- role prompts должны быть тонкими: модель принимает judgment-решения, но не переизобретает pipeline каждый запуск.

---

## 1. Согласованные provider/model имена

### 1.1. AI Router Orchestrator

```
Profile: orchestrator-router-3270
Provider: LOCAL
Endpoint: 127.0.0.1:3270
Model: Orchestrator
Role: главный оркестратор процесса
```

### 1.2. AI Router Reviewer

```
Profile: router-reviewer
Provider: LOCAL
Endpoint: 127.0.0.1:3270
Model: Reviewer
Role: review council / критика / риски / альтернативы
Status: будет создан на AI Router server позже
```

### 1.3. AI Router Senior

```
Profile: router-senior
Provider: LOCAL
Endpoint: 127.0.0.1:3270
Model: Router Senior
Role: запасной Senior / economy Senior вместо Codex
Status: будет создан на AI Router server позже
```

### 1.4. LM Studio / Qwen Builder Models

```
Provider: LM STUDIO
Endpoint: http://127.0.0.1:1234
Role: локальные builder-модели, переключаемые Orchestrator по цели задачи
```

Согласованные модели:

```
Fast Builder:
qwen/qwen3.5-9b Q6_K
Role: qwen-builder-fast
Use: быстрые правки, компоненты, CSS/Tailwind, простые фиксы, docs, быстрые циклы.

Main / Smart Builder:
qwen/qwen3.6-35b-a3b Q4_K_M
Role: qwen-builder-main
Use: основная разработка, сложные фичи, интеграции, reasoning, refactor, локальный debug.
```

Правило:

```
Orchestrator может переключать локальную модель в LM Studio в зависимости от цели задачи.
Быстрая задача → qwen3.5-9b Q6_K.
Сложная/важная задача → qwen3.6-35b-a3b Q4_K_M.
Если локальные модели не справились → Router Senior / Codex Senior по Senior Gate policy.
```

### 1.5. Gemini Planner

```
Profile: gemini-planner
Provider: GOOGLE
Model: Gemini 3.1 flash light
Role: planner / UX / summary / checklist / lightweight review
```

### 1.6. Codex Senior

```
Profile: codex-senior
Provider: OPENAI CODEX
Model: GPT-5.5
Role: premium Senior Engineer / debugger / final gate
```

На первом этапе: `Codex через Hermes provider`
Будущий этап: `Codex CLI для сложного реального coding/debugging`

---

## 2. Основные профили Hermes

Нужно создать и настроить следующие Hermes profiles:

```
orchestrator-router-3270
qwen-builder
gemini-planner
router-reviewer
codex-senior
router-senior
```

### 2.1. `orchestrator-router-3270`

Роль:
- принимает задачи пользователя;
- формирует brief;
- разбивает работу на Kanban tasks;
- назначает worker-профили;
- контролирует pipeline;
- запускает review;
- отслеживает лимиты;
- решает, когда нужен Senior Gate;
- выбирает Codex Senior или Router Senior;
- отправляет уведомления в Hermes Chat и Telegram.

### 2.2. `qwen-builder`

Роль:
- основной writer;
- пишет код;
- запускает проверки;
- исправляет ошибки;
- не меняет scope без причины;
- после 2 неудачных циклов помечает задачу как blocked/escalation-needed.

### 2.3. `gemini-planner`

Роль:
- делает product brief;
- UX-flow;
- acceptance criteria;
- checklist;
- documentation review;
- лёгкий sanity-check.

### 2.4. `router-reviewer`

Роль:
- technical review;
- architecture review;
- security/edge-case critique;
- поиск противоречий;
- actionable recommendations;
- классификация проблем: critical / major / minor.

### 2.5. `codex-senior`

Роль:
- premium Senior Engineer;
- сложный debugging;
- final gate;
- production-critical fixes;
- auth/security/payment review;
- многофайловые исправления.

### 2.6. `router-senior`

Роль:
- economy/fallback Senior;
- используется вместо Codex при экономии;
- используется если Codex недоступен;
- может быть первым Senior в economy pipeline.

---

## 3. Pipeline presets

### 3.1. Premium Codex Pipeline

Для важных задач и production-critical изменений.

```
User task → AI Router Orchestrator → Kanban decomposition → Gemini spec/checklist
→ Qwen implementation → Local verification → Gemini + Router Reviewer review
→ Qwen fix cycles → Senior Gate → Codex Senior → Final verification → Done
```

Senior backend: Primary: Codex GPT-5.5, Fallback: Router Senior

### 3.2. Economy Router Senior Pipeline

Для экономии Codex.

```
User task → AI Router Orchestrator → Kanban decomposition → Gemini spec/checklist
→ Qwen implementation → Local verification → Gemini + Router Reviewer review
→ Qwen fix cycles → Router Senior first → Codex only if still blocked and user approves
→ Final verification → Done
```

Senior backend: Primary: Router Senior, Fallback: Codex GPT-5.5 after approval

### 3.3. Manual Senior Selection Pipeline

Для максимального контроля.

```
At Senior Gate user chooses:
  1. Codex Senior
  2. Router Senior
  3. Qwen retry x1
  4. Qwen retry x2
  5. Stop / change strategy
```

### 3.4. Economy Fully Autonomous Pipeline

Для автономной работы без участия пользователя до лимита.

```
User task → AI Router Orchestrator → Kanban decomposition → Gemini spec/checklist
→ Qwen implementation → Verification → Reviewer review
→ Qwen / Router Senior fix cycles → Up to 6 autonomous cycles
→ If solved → Done → If not solved → Human Gate
```

После 6 циклов система спрашивает пользователя:
```
Задача не решена за 6 циклов. Что делать?
1. Передать GPT Codex Senior
2. Сделать ещё 6 автономных циклов
3. Остановиться
4. Изменить стратегию / дать новые инструкции
```

---

## 4. Политика автономности

### 4.1. Базовое правило

```
В указанной рабочей папке проекта воркеры имеют полную автономность.
```

Они могут: читать/создавать/редактировать/удалять файлы, запускать install/build/test/lint/dev-команды, устанавливать зависимости, работать без постоянного approval.

### 4.2. Глобальные команды вне рабочей папки

Разрешены: проверка версий, установка CLI, проверка портов/сети, git, подготовка окружения.

### 4.3. Красные линии

```
Не вредить системе. Не ломать окружение. Не удалять пользовательские данные.
Не останавливать AI Router. Не убивать интернет.
```

---

## 5. Параллельность

Стартовая политика: `1 writer at a time, 2–3 reviewers in parallel, Senior only on escalation`

Запрещено: параллельное редактирование одних файлов, несколько writers в одной области, хаотичные изменения без Kanban task.

Разрешено: параллельное review, параллельная подготовка brief/checklist, последовательные fix cycles.

---

## 6. Kanban lifecycle

```
Backlog → Spec → Architecture → Design → Implementation
→ Local Verification → Swarm Review → Fixes
→ Senior Gate / Escalation → Final Verification → Done
```

Минимальный operational status set:
```
TODO → READY → IN_PROGRESS → REVIEW → FIXES → BLOCKED
→ SENIOR_GATE → SENIOR_IN_PROGRESS → FINAL_VERIFICATION → DONE → CANCELLED
```

---

## 7. Типы Kanban-задач

| Тип | Исполнители |
|---|---|
| `spec` | Orchestrator, Gemini, Qwen |
| `architecture` | Orchestrator, Review Council, Qwen, Codex (production-critical) |
| `design` | Gemini, Qwen, Review Council |
| `implementation` | Qwen first, Codex при сложности |
| `integration` | Qwen draft, Router/Gemini review, Codex (security/OAuth/payment) |
| `test` | Qwen, Codex при сложной логике |
| `review` | Gemini, Review Council, Codex (финальное) |
| `debug` | Qwen first, Codex if unresolved |

---

## 8. Шаблон Kanban-карточки

```markdown
# Task: <краткое название>

## Type
spec / architecture / design / implementation / integration / test / review / debug / advisor-review

## Goal
Что нужно сделать.

## Acceptance Criteria
- [ ] Критерий 1
- [ ] Критерий 2

## Dependencies
- Зависит от: <task_id>

## Notes
Дополнительные заметки.
```

---

## 9. Advisor Trio integration

**Цель:** добавить экологичный слой советников DeepSeek + Qwen Web + Kimi/GLM для сложных решений, архитектуры, review conflict и Senior Gate.

```text
Advisor Trio = DeepSeek Advisor + Qwen Web Advisor + Kimi/GLM Advisor
```

### 9.1. Назначение

Trio Advisors не являются основными worker-кодерами. Они используются как независимые советники:

- найти риски;
- предложить альтернативы;
- сравнить подходы;
- помочь перед Senior Gate;
- помочь после 6 неудачных автономных циклов;
- сформировать гибридное решение из лучших идей.

### 9.2. Advisor roles

```text
DeepSeek Advisor:
  models: deepseek-reasoner / deepseek-r1 / deepseek-v4-pro / deepseek-reasoner-search
  role: reasoning, debug, risk analysis, hidden failure modes.

Qwen Web Advisor:
  models: qwen3.7-max / qwen3.7-plus / qwen3-coder-plus
  role: practical implementation, code patterns, frontend/backend, integrations.

Kimi/GLM Advisor:
  models: kimi-k2.5-thinking / glm-5-thinking / glm-5-deepresearch
  role: alternative architecture, long-context thinking, UX/product/research.
```

### 9.3. Где вызывать Trio

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

### 9.4. Eco usage policy

- [ ] Trio вызывается только для medium/high-risk задач.
- [ ] Не больше 1 раунда на decision point.
- [ ] Не отправлять полный репозиторий.
- [ ] Отправлять compact human-readable brief.
- [ ] Не отправлять секреты, токены, `.env`, auth-файлы, cookies.
- [ ] Не запускать спам/циклический опрос.
- [ ] Не использовать Trio для рутинной генерации кода.
- [ ] Orchestrator всегда делает final synthesis.
- [ ] Если один advisor недоступен — продолжать с оставшимися.

### 9.5. Жёсткий формат сообщения для Trio

Создать шаблон:

```text
PIPELINE/templates/trio-advisor-request.md
```

Требования:

- [ ] сообщение выглядит человечно;
- [ ] структурировано и понятно;
- [ ] без машинного мусора;
- [ ] без странных иероглифов;
- [ ] без огромного количества спецсимволов;
- [ ] без JSON, если это не нужно;
- [ ] без дампа внутренней Kanban/engine-служебки;
- [ ] похоже на нормальное человеческое ТЗ для сильного консультанта.

Базовый шаблон:

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

### 9.6. Graceful degradation

- [ ] Если один advisor лёг — Trio step продолжается с двумя мнениями.
- [ ] Если ответил только один advisor — использовать одно мнение как advisory input.
- [ ] Если все advisors легли — Trio step пропускается, pipeline продолжается.
- [ ] Не делать бесконечные retries.
- [ ] В Kanban фиксировать Advisor Availability.

Правило:

```text
Unavailable advisor не блокирует pipeline.
Все unavailable → пропустить Trio step и продолжить без advisory layer.
Critical task → перейти к Router Senior / Human Gate / Codex Senior по политике.
```

### 9.7. Retry / timeout policy

```text
1 короткая попытка на advisor.
1 optional retry только при transient network timeout.
Max 2 attempts per advisor.
Timeout: 30–90 seconds.
If failed: mark unavailable and continue.
```

### 9.8. Synthesis template

Создать шаблон:

```text
PIPELINE/templates/trio-advisor-synthesis.md
```

Содержание:

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

### 9.9. Kanban integration

- [ ] Добавить task type `advisor-review`.
- [ ] Хранить `Trio request summary`.
- [ ] Хранить summaries ответов DeepSeek/Qwen/Kimi.
- [ ] Хранить Advisor Availability.
- [ ] Хранить Orchestrator synthesis.
- [ ] Хранить Final decision.
- [ ] Длинные полные ответы хранить как artifact/log, а не перегружать Kanban comment.

### 9.10. Safe health/readiness checks

Read-only checks без расхода upstream-квоты:

```text
Dashboard: http://127.0.0.1:8000/api/servers
QWEN:      http://127.0.0.1:3264/api/health
DEEPSEEK:  http://127.0.0.1:9655/health
KIMI:      http://127.0.0.1:3265/health
```

Chat completion smoke tests расходуют web-chat/provider ресурс и должны запускаться только осознанно.

---

## 10. Final readiness additions

- [ ] Advisor Trio описан в `Hermes_Multi_Model_Pipeline.md`.
- [ ] `advisor-review` добавлен как task type.
- [ ] `trio-advisor-request.md` создан.
- [ ] `trio-advisor-synthesis.md` создан.
- [ ] Graceful degradation policy зафиксирована.
- [ ] Eco usage policy зафиксирована.
- [ ] Запрет на секреты в Trio prompt зафиксирован.
- [ ] Trio не блокирует pipeline при недоступности advisor.
- [ ] Для critical задач при недоступности Trio есть fallback: Router Senior / Human Gate / Codex Senior.

