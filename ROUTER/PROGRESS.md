# ROUTER — Progress

## 2026-06-17: Anti-rate-limit guards

Настроены защиты от расхода квоты OpenRouter:
- `maxFallbackAttempts: 1` — один upstream-кандидат на запрос
- `fallbackOnRateLimit: false` — 429 останавливает сразу
- `maxRequestsPerWindow: 3/min`, `minRequestIntervalMs: 15000`
- `maxCompletionTokens: 4096`, `maxEstimatedPromptTokens: 90000`
- `roleRetryCooldownMs: 60000`

Добавлен регрессионный тест: `node scripts/test_router_guards.mjs` (без расхода квоты).
