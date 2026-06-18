# ROUTER — AI Orchestrator & Fallback Proxy

**Port:** `3270`
**Type:** Node.js HTTP server

## Что это

Локальный OpenAI-compatible fallback proxy для виртуальных ролей:
- **Orchestrator** — оркестрация и планирование
- **Reviewer** — ревью/проверка
- **Router Senior** — senior fallback / сложные случаи

Роутер принимает запросы в формате OpenAI API и перенаправляет их в OpenRouter с автоматической ротацией моделей (fallback) при ошибках.

## Быстрый старт

```bash
cd C:\Users\Forestsnow\workspace\AI_server\ROUTER
npm start
```

Ключ OpenRouter: `C:\Users\Forestsnow\workspace\AI_server\openrouter.txt`

## Проверка (без расхода квоты)

```bash
curl http://127.0.0.1:3270/health
curl http://127.0.0.1:3270/v1/models
curl http://127.0.0.1:3270/config
curl http://127.0.0.1:3270/status
```

## Live smoke test (расходует 1 запрос)

```bash
curl -X POST http://127.0.0.1:3270/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Orchestrator","messages":[{"role":"user","content":"Reply exactly: OK"}],"max_tokens":8,"temperature":0}'
```

## Виртуальные модели

| Роль | Назначение |
|---|---|
| `Orchestrator` | главный оркестратор процесса |
| `Reviewer` | review council / критика / риски |
| `Router Senior` | economy/fallback Senior |

## Порядок моделей (Orchestrator)

1. `openrouter/owl-alpha` — основная (платная, стабильная)
2. `openai/gpt-oss-120b:free` — fallback #1
3. `nvidia/nemotron-3-super-120b-a12b:free` — fallback #2
4. `nousresearch/hermes-3-llama-3.1-405b:free` — fallback #3 (без tools)

## Anti-rate-limit guards

- `/health`, `/config`, `/status`, `/v1/models` — не вызывают OpenRouter
- Только `POST /v1/chat/completions` создаёт upstream-запросы
- `maxFallbackAttempts: 1` — один кандидат на запрос
- `fallbackOnRateLimit: false` — 429 останавливает сразу
- `maxRequestsPerWindow: 3` в минуту, `minRequestIntervalMs: 15000`
- `maxCompletionTokens: 4096`, `maxEstimatedPromptTokens: 90000`
- `roleRetryCooldownMs: 60000`
- `responseCacheTtlMs: 30000` — кэш идентичных запросов

## Логи

- `router.out.log` — stdout
- `router.err.log` — stderr

## Авто-перезапуск

Лаунчер (`router_launcher.py`) автоматически перезапускает сервер при падении (до 10 раз за 5 минут).

## Подключение в Hermes

```
Provider: custom
Base URL: http://127.0.0.1:3270/v1
Model: Orchestrator
```

## Регрессионный тест

```bash
cd C:\Users\Forestsnow\workspace\AI_server\ROUTER
node scripts/test_router_guards.mjs
```

## Частые вопросы

**Q: Owl Alpha напрямую через OpenRouter — стабильнее?**
A: Да. Рекомендация: Owl Alpha напрямую как основной провайдер, роутер — как запасной.

**Q: Зачем роутер если есть платная модель?**
A: Страховка — автоматический fallback при лимите или недоступности.

**Q: Spend Limit 0$ при наличии 12$?**
A: Не рекомендуется — платные модели перестанут работать (402). Лучше лимит 1-2$/мес.
