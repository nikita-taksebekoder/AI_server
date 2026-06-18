import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const configPath = path.join(__dirname, "config.json");
const config = JSON.parse(fs.readFileSync(configPath, "utf8"));

const OPENROUTER_BASE_URL = process.env.OPENROUTER_BASE_URL || config.openRouterBaseUrl || "https://openrouter.ai/api/v1";
const SERVER_TITLE = config.title || "AI Router Fallback Proxy";

// ── Graceful shutdown state ──────────────────────────────────────────
let shuttingDown = false;
const activeUpstreamControllers = new AbortController();

function gracefulShutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  log(`Received ${signal}, starting graceful shutdown…`);
  // Abort any in-flight upstream fetches
  activeUpstreamControllers.abort();
  // Stop accepting new connections
  server.close(() => {
    log("HTTP server closed. Bye!");
    process.exit(0);
  });
  // Force-exit after 10 s if something hangs
  setTimeout(() => {
    log("Forced exit after timeout");
    process.exit(1);
  }, 10_000).unref();
}

process.on("SIGINT", () => gracefulShutdown("SIGINT"));
process.on("SIGTERM", () => gracefulShutdown("SIGTERM"));
process.on("SIGHUP", () => gracefulShutdown("SIGHUP"));

// Catch unhandled rejections / exceptions so the process doesn't die silently
process.on("unhandledRejection", (reason) => {
  log(`UNHANDLED REJECTION: ${reason}`);
});
process.on("uncaughtException", (err) => {
  log(`UNCAUGHT EXCEPTION: ${err?.message || err}`);
});

const DEFAULTS = {
  requestTimeoutMs: 90000,
  maxFallbackAttempts: 4,
  maxConcurrentRequests: 1,
  rateLimitWindowMs: 60000,
  maxRequestsPerWindow: 5,
  minRequestIntervalMs: 5000,
  minDelayBetweenUpstreamRequestsMs: 2000,
  rateLimitCooldownMs: 2 * 60 * 1000,
  authCooldownMs: 60 * 60 * 1000,
  badRequestCooldownMs: 60 * 60 * 1000,
  providerErrorCooldownMs: 60 * 1000,
  timeoutCooldownMs: 60 * 1000,
  emptyResponseCooldownMs: 30 * 1000,
  roleRetryCooldownMs: 30 * 1000,
  maxCompletionTokens: 4096,
  maxEstimatedPromptTokens: 90000,
  responseCacheTtlMs: 30 * 1000,
  responseCacheMaxEntries: 50,
  fallbackOnRateLimit: true,
  preferLastSuccessful: true
};

const runtimeState = {
  startedAt: new Date().toISOString(),
  // Accepted OpenAI-compatible chat completion requests from clients.
  // Health/model/config/status reads are intentionally excluded.
  totalRequests: 0,
  chatRequests: 0,
  successfulRequests: 0,
  failedRequests: 0,
  cacheServedRequests: 0,
  // Real upstream POST attempts sent to model providers.
  upstreamRequests: 0,
  upstreamSuccesses: 0,
  upstreamFailures: 0,
  usage: {
    prompt: 0,
    completion: 0,
    total: 0,
    byRole: {},
    byCandidate: {}
  },
  localRejects: {
    rateLimited: 0,
    tooFrequent: 0,
    roleCooldown: 0,
    busy: 0,
    noCandidate: 0,
    badRequest: 0,
    promptTooLarge: 0
  },
  cache: {
    hits: 0,
    stores: 0,
    evictions: 0
  },
  roles: {},
  candidates: {}
};

const activeByRole = new Map();
const requestWindowsByRole = new Map();
const lastUpstreamAtByRole = new Map();
const responseCacheByKey = new Map();
let lastResetAt = 0;

function cfgNumber(name, fallback) {
  const value = Number(config[name]);
  return Number.isFinite(value) ? value : fallback;
}

function cfgBool(name, fallback) {
  if (typeof config[name] === "boolean") return config[name];
  return fallback;
}

function nowIso() {
  return new Date().toISOString();
}

function log(message) {
  console.log(`${nowIso()} ${message}`);
}

function truncate(value, maxLength = 500) {
  const text = String(value ?? "");
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}…`;
}

function readFirstUsableLine(filePath) {
  if (!filePath || typeof filePath !== "string") return "";
  try {
    return fs.readFileSync(filePath, "utf8")
      .split(String.fromCharCode(10))
      .map(line => line.trim())
      .find(line => line && !line.startsWith("#")) || "";
  } catch {
    return "";
  }
}

function cloneJson(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function readOpenRouterKey() {
  const envName = typeof config.openRouterApiKeyEnv === "string" ? config.openRouterApiKeyEnv.trim() : "";
  if (envName) {
    const fromSpecificEnv = process.env[envName]?.trim();
    if (fromSpecificEnv) return fromSpecificEnv;
  }

  const fromFile = readFirstUsableLine(config.openRouterKeyFile);
  if (fromFile) return fromFile;

  // Global fallback is intentionally last. Otherwise one inherited
  // OPENROUTER_API_KEY can silently make all router roles burn the same quota.
  const fromGlobalEnv = process.env.OPENROUTER_API_KEY?.trim();
  if (fromGlobalEnv) return fromGlobalEnv;

  return "";
}

function describeOpenRouterKeySource() {
  const envName = typeof config.openRouterApiKeyEnv === "string" ? config.openRouterApiKeyEnv.trim() : "";
  if (envName && process.env[envName]?.trim()) return `env:${envName}`;
  if (readFirstUsableLine(config.openRouterKeyFile)) return `file:${path.basename(config.openRouterKeyFile)}`;
  if (process.env.OPENROUTER_API_KEY?.trim()) return "env:OPENROUTER_API_KEY";
  return "missing";
}

function json(res, status, body, extraHeaders = {}) {
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "content-type, authorization",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    ...extraHeaders
  });
  res.end(JSON.stringify(body, null, 2));
}

function candidateLabel(candidate) {
  return `${candidate.provider}:${candidate.model}`;
}

function zeroUsage() {
  return { prompt: 0, completion: 0, total: 0 };
}

function activeRequestsObject() {
  return Object.fromEntries(activeByRole.entries());
}

function publicCandidateState() {
  const now = Date.now();
  const result = {};
  for (const [label, state] of Object.entries(runtimeState.candidates)) {
    result[label] = {
      successes: state.successes,
      failures: state.failures,
      attempts: state.attempts,
      usage: cloneJson(state.usage || zeroUsage()),
      tokens: cloneJson(state.usage || zeroUsage()),
      lastStatus: state.lastStatus,
      lastError: state.lastError,
      lastSuccessAt: state.lastSuccessAt,
      lastFailureAt: state.lastFailureAt,
      cooldownUntil: state.cooldownUntil ? new Date(state.cooldownUntil).toISOString() : null,
      cooldownMsRemaining: Math.max(0, (state.cooldownUntil || 0) - now),
      cooldownReason: state.cooldownReason || null
    };
  }
  return result;
}

function publicConfig() {
  const virtualModels = {};
  for (const [name, candidatesRaw] of Object.entries(config.virtualModels ?? {})) {
    const arr = Array.isArray(candidatesRaw) ? candidatesRaw : (candidatesRaw?.models ?? []);
    virtualModels[name] = arr.map(candidateLabel);
  }
  return {
    title: SERVER_TITLE,
    host: config.host,
    port: config.port,
    requestTimeoutMs: cfgNumber("requestTimeoutMs", DEFAULTS.requestTimeoutMs),
    maxFallbackAttempts: cfgNumber("maxFallbackAttempts", DEFAULTS.maxFallbackAttempts),
    maxConcurrentRequests: cfgNumber("maxConcurrentRequests", DEFAULTS.maxConcurrentRequests),
    rateLimitWindowMs: cfgNumber("rateLimitWindowMs", DEFAULTS.rateLimitWindowMs),
    maxRequestsPerWindow: cfgNumber("maxRequestsPerWindow", DEFAULTS.maxRequestsPerWindow),
    minRequestIntervalMs: cfgNumber("minRequestIntervalMs", DEFAULTS.minRequestIntervalMs),
    minDelayBetweenUpstreamRequestsMs: cfgNumber("minDelayBetweenUpstreamRequestsMs", DEFAULTS.minDelayBetweenUpstreamRequestsMs),
    rateLimitCooldownMs: cfgNumber("rateLimitCooldownMs", DEFAULTS.rateLimitCooldownMs),
    roleRetryCooldownMs: cfgNumber("roleRetryCooldownMs", DEFAULTS.roleRetryCooldownMs),
    maxCompletionTokens: cfgNumber("maxCompletionTokens", DEFAULTS.maxCompletionTokens),
    maxEstimatedPromptTokens: cfgNumber("maxEstimatedPromptTokens", DEFAULTS.maxEstimatedPromptTokens),
    responseCacheTtlMs: cfgNumber("responseCacheTtlMs", DEFAULTS.responseCacheTtlMs),
    responseCacheMaxEntries: cfgNumber("responseCacheMaxEntries", DEFAULTS.responseCacheMaxEntries),
    fallbackOnRateLimit: cfgBool("fallbackOnRateLimit", DEFAULTS.fallbackOnRateLimit),
    preferLastSuccessful: cfgBool("preferLastSuccessful", DEFAULTS.preferLastSuccessful),
    openRouterKeySource: describeOpenRouterKeySource(),
    virtualModels
  };
}

function lastUpstreamAtObject() {
  return Object.fromEntries([...lastUpstreamAtByRole.entries()].map(([role, timestamp]) => [
    role,
    timestamp ? new Date(timestamp).toISOString() : null
  ]));
}

function publicStatus() {
  return {
    title: SERVER_TITLE,
    startedAt: runtimeState.startedAt,
    requests: {
      total: runtimeState.totalRequests,
      chat: runtimeState.chatRequests,
      successful: runtimeState.successfulRequests,
      failed: runtimeState.failedRequests,
      cacheServed: runtimeState.cacheServedRequests,
      upstream: runtimeState.upstreamRequests,
      upstreamSuccesses: runtimeState.upstreamSuccesses,
      upstreamFailures: runtimeState.upstreamFailures
    },
    totalRequests: runtimeState.totalRequests,
    chatRequests: runtimeState.chatRequests,
    successfulRequests: runtimeState.successfulRequests,
    failedRequests: runtimeState.failedRequests,
    cacheServedRequests: runtimeState.cacheServedRequests,
    upstreamRequests: runtimeState.upstreamRequests,
    upstreamSuccesses: runtimeState.upstreamSuccesses,
    upstreamFailures: runtimeState.upstreamFailures,
    usage: cloneJson(runtimeState.usage),
    tokens: cloneJson(runtimeState.usage),
    localRejects: runtimeState.localRejects,
    cache: {
      ...runtimeState.cache,
      entries: responseCacheByKey.size
    },
    activeRequests: activeRequestsObject(),
    lastUpstreamAt: lastUpstreamAtObject(),
    roles: runtimeState.roles,
    candidates: publicCandidateState()
  };
}

function resetRuntimeState() {
  runtimeState.totalRequests = 0;
  runtimeState.chatRequests = 0;
  runtimeState.successfulRequests = 0;
  runtimeState.failedRequests = 0;
  runtimeState.cacheServedRequests = 0;
  runtimeState.upstreamRequests = 0;
  runtimeState.upstreamSuccesses = 0;
  runtimeState.upstreamFailures = 0;
  runtimeState.usage = { prompt: 0, completion: 0, total: 0, byRole: {}, byCandidate: {} };
  runtimeState.roles = {};
  runtimeState.localRejects = {
    rateLimited: 0, tooFrequent: 0, roleCooldown: 0,
    busy: 0, noCandidate: 0, badRequest: 0, promptTooLarge: 0
  };
  runtimeState.cache = { hits: 0, stores: 0, evictions: 0 };
  responseCacheByKey.clear();
  activeByRole.clear();
  requestWindowsByRole.clear();
  lastUpstreamAtByRole.clear();
  runtimeState.candidates = {};
  log("Runtime state fully reset");
}

function normalizeUsage(usage) {
  const prompt = Number(usage?.prompt_tokens ?? usage?.prompt ?? usage?.input_tokens ?? usage?.input ?? 0) || 0;
  const completion = Number(usage?.completion_tokens ?? usage?.completion ?? usage?.output_tokens ?? usage?.output ?? 0) || 0;
  const total = Number(usage?.total_tokens ?? usage?.total ?? 0) || (prompt + completion);
  return { prompt, completion, total };
}

function addUsage(target, usage) {
  target.prompt = (Number(target.prompt) || 0) + usage.prompt;
  target.completion = (Number(target.completion) || 0) + usage.completion;
  target.total = (Number(target.total) || 0) + usage.total;
  return target;
}

function recordUsage(virtualModel, candidateLabelValue, usage) {
  addUsage(runtimeState.usage, usage);
  runtimeState.usage.byRole[virtualModel] ??= zeroUsage();
  addUsage(runtimeState.usage.byRole[virtualModel], usage);
  runtimeState.usage.byCandidate[candidateLabelValue] ??= zeroUsage();
  addUsage(runtimeState.usage.byCandidate[candidateLabelValue], usage);

  runtimeState.roles[virtualModel] ??= {};
  runtimeState.roles[virtualModel].usage ??= zeroUsage();
  addUsage(runtimeState.roles[virtualModel].usage, usage);
  runtimeState.roles[virtualModel].tokens = cloneJson(runtimeState.roles[virtualModel].usage);
  runtimeState.roles[virtualModel].modelTokens ??= {};
  runtimeState.roles[virtualModel].modelTokens[candidateLabelValue] ??= zeroUsage();
  addUsage(runtimeState.roles[virtualModel].modelTokens[candidateLabelValue], usage);

  const candidate = ensureCandidateState(candidateLabelValue);
  candidate.usage ??= zeroUsage();
  addUsage(candidate.usage, usage);
}

function hasUsefulContent(response) {
  const choice = response?.choices?.[0];
  if (!choice) return false;
  const message = choice.message;
  if (!message) return false;
  const hasContent = typeof message.content === "string" && message.content.trim().length > 0;
  const hasToolCalls = Array.isArray(message.tool_calls) && message.tool_calls.length > 0;
  return hasContent || hasToolCalls;
}

function providerBaseUrl(candidate) {
  if (candidate.provider === "openrouter") return OPENROUTER_BASE_URL;
  if (candidate.provider === "local") return candidate.baseUrl;
  throw new Error(`Unknown provider: ${candidate.provider}`);
}

function readCandidateKey(candidate) {
  if (candidate.apiKey && typeof candidate.apiKey === "string") {
    return candidate.apiKey.trim();
  }

  if (candidate.apiKeyEnv && typeof candidate.apiKeyEnv === "string") {
    const fromEnv = process.env[candidate.apiKeyEnv]?.trim();
    if (fromEnv) return fromEnv;
  }

  if (candidate.apiKeyFile && typeof candidate.apiKeyFile === "string") {
    try {
      return fs.readFileSync(candidate.apiKeyFile, "utf8")
        .split(/\r?\n/)
        .map(line => line.trim())
        .find(line => line && !line.startsWith("#")) || "";
    } catch {
      return "";
    }
  }

  return "dummy-key";
}

function providerHeaders(candidate) {
  if (candidate.provider === "openrouter") {
    const key = readOpenRouterKey();
    if (!key) throw Object.assign(new Error("OpenRouter API key is missing"), { status: 401 });
    return {
      authorization: `Bearer ${key}`,
      "content-type": "application/json",
      "http-referer": `http://${config.host}:${config.port}`,
      "x-title": SERVER_TITLE
    };
  }

  const key = readCandidateKey(candidate);
  return {
    ...(key ? { authorization: `Bearer ${key}` } : {}),
    "content-type": "application/json"
  };
}

function ensureCandidateState(label) {
  runtimeState.candidates[label] ??= {
    successes: 0,
    failures: 0,
    attempts: 0,
    cooldownUntil: 0,
    cooldownReason: null,
    lastStatus: null,
    lastError: null,
    lastSuccessAt: null,
    lastFailureAt: null,
    usage: zeroUsage()
  };
  return runtimeState.candidates[label];
}

function parseRetryAfterMs(value) {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const timestamp = Date.parse(value);
  if (!Number.isNaN(timestamp)) return Math.max(0, timestamp - Date.now());
  return null;
}

function cooldownForError(error) {
  if (error?.name === "AbortError") {
    return {
      ms: cfgNumber("timeoutCooldownMs", DEFAULTS.timeoutCooldownMs),
      reason: "timeout"
    };
  }

  if (error?.emptyResponse) {
    return {
      ms: cfgNumber("emptyResponseCooldownMs", DEFAULTS.emptyResponseCooldownMs),
      reason: "empty-response"
    };
  }

  const status = Number(error?.status) || 0;
  if (status === 429) {
    const configuredCooldown = cfgNumber("rateLimitCooldownMs", DEFAULTS.rateLimitCooldownMs);
    const retryAfterMs = parseRetryAfterMs(error.retryAfter);
    return {
      // Be conservative with free OpenRouter models: Retry-After can be absent
      // or too small for account-level free-tier limits. Never cool down less
      // than our configured guard window.
      ms: Math.max(configuredCooldown, retryAfterMs ?? 0),
      reason: "upstream-429"
    };
  }

  if ([401, 402, 403].includes(status)) {
    return {
      ms: cfgNumber("authCooldownMs", DEFAULTS.authCooldownMs),
      reason: `upstream-${status}`
    };
  }

  if ([400, 404].includes(status)) {
    return {
      ms: cfgNumber("badRequestCooldownMs", DEFAULTS.badRequestCooldownMs),
      reason: `upstream-${status}`
    };
  }

  if (status >= 500 || status === 408 || status === 409) {
    return {
      ms: cfgNumber("providerErrorCooldownMs", DEFAULTS.providerErrorCooldownMs),
      reason: `upstream-${status || "error"}`
    };
  }

  return {
    ms: cfgNumber("providerErrorCooldownMs", DEFAULTS.providerErrorCooldownMs),
    reason: status ? `upstream-${status}` : "upstream-error"
  };
}

function shouldTryNextCandidate(error) {
  const status = Number(error?.status) || 0;
  // These usually mean a shared key/config/payload problem. Trying every
  // fallback immediately just burns OpenRouter quota and can trigger blocks.
  if ([400, 401, 402, 403, 404, 413].includes(status)) return false;

  // Free OpenRouter limits are often account-wide or provider-wide. By default
  // a 429 becomes a circuit-breaker signal, not a reason to immediately hit the
  // next free model and risk cascading rate limits. Set fallbackOnRateLimit=true
  // in config only if you explicitly want cross-model failover on 429.
  if (status === 429 && !cfgBool("fallbackOnRateLimit", DEFAULTS.fallbackOnRateLimit)) return false;

  // Timeouts and empty responses are also poor signals for immediate free-model
  // fan-out: the first provider may still count the request, and the retry often
  // arrives while the original request is still consuming capacity.
  if (error?.name === "AbortError" || error?.emptyResponse) return false;

  return true;
}

function markCandidateAttempt(label) {
  const state = ensureCandidateState(label);
  state.attempts += 1;
}

function markCandidateSuccess(label) {
  const state = ensureCandidateState(label);
  state.successes += 1;
  state.cooldownUntil = 0;
  state.cooldownReason = null;
  state.lastStatus = 200;
  state.lastError = null;
  state.lastSuccessAt = nowIso();
}

function markCandidateFailure(label, error) {
  const state = ensureCandidateState(label);
  const cooldown = cooldownForError(error);
  state.failures += 1;
  state.lastStatus = error?.name === "AbortError" ? "timeout" : (error?.status || "error");
  state.lastError = truncate(error?.message || "request failed");
  state.lastFailureAt = nowIso();
  if (cooldown.ms > 0) {
    state.cooldownUntil = Date.now() + cooldown.ms;
    state.cooldownReason = cooldown.reason;
  }
  return state;
}

function cooldownView(label, candidate) {
  const state = ensureCandidateState(label);
  return {
    model: label,
    until: state.cooldownUntil ? new Date(state.cooldownUntil).toISOString() : null,
    msRemaining: Math.max(0, (state.cooldownUntil || 0) - Date.now()),
    reason: state.cooldownReason,
    lastStatus: state.lastStatus,
    lastError: state.lastError,
    candidate
  };
}

function requestUsesTools(body) {
  return (Array.isArray(body?.tools) && body.tools.length > 0) ||
    (Array.isArray(body?.functions) && body.functions.length > 0) ||
    body?.tool_choice ||
    body?.function_call;
}

function candidateSupportsRequest(candidate, body) {
  if (requestUsesTools(body) && candidate.supportsTools === false) {
    return { supported: false, reason: "tools-not-supported" };
  }
  return { supported: true, reason: null };
}

function getRoleCooldown(virtualModel) {
  const role = runtimeState.roles[virtualModel];
  const until = role?.cooldownUntil || 0;
  const retryAfterMs = Math.max(0, until - Date.now());
  if (retryAfterMs <= 0) return null;
  return {
    until: new Date(until).toISOString(),
    retryAfterMs,
    reason: role.cooldownReason || "role-cooldown"
  };
}

function setRoleCooldown(virtualModel, error) {
  const retryAfterMs = parseRetryAfterMs(error?.retryAfter);
  const fallbackMs = cfgNumber("roleRetryCooldownMs", DEFAULTS.roleRetryCooldownMs);
  const ms = Math.max(0, retryAfterMs ?? fallbackMs);
  if (ms <= 0) return null;
  runtimeState.roles[virtualModel] ??= {};
  runtimeState.roles[virtualModel].cooldownUntil = Date.now() + ms;
  runtimeState.roles[virtualModel].cooldownReason = error?.name === "AbortError"
    ? "timeout"
    : (error?.status ? `upstream-${error.status}` : "upstream-error");
  return getRoleCooldown(virtualModel);
}

function clearRoleCooldown(virtualModel) {
  if (!runtimeState.roles[virtualModel]) return;
  runtimeState.roles[virtualModel].cooldownUntil = 0;
  runtimeState.roles[virtualModel].cooldownReason = null;
}

function normalizeRequestBody(body) {
  const normalized = { ...body, stream: false };
  const maxCompletionTokens = cfgNumber("maxCompletionTokens", DEFAULTS.maxCompletionTokens);
  if (maxCompletionTokens > 0) {
    let hasExplicitLimit = false;
    for (const field of ["max_tokens", "max_completion_tokens"]) {
      const value = Number(normalized[field]);
      if (Number.isFinite(value)) {
        hasExplicitLimit = true;
        if (value > maxCompletionTokens) normalized[field] = maxCompletionTokens;
      }
    }
    if (!hasExplicitLimit) normalized.max_tokens = maxCompletionTokens;
  }
  return normalized;
}

function estimatePromptTokens(body) {
  const promptPayload = {
    messages: body.messages ?? [],
    tools: body.tools ?? [],
    functions: body.functions ?? []
  };
  return Math.ceil(Buffer.byteLength(JSON.stringify(promptPayload), "utf8") / 4);
}

function ensurePromptWithinBudget(body) {
  const estimatedPromptTokens = estimatePromptTokens(body);
  const maxEstimatedPromptTokens = cfgNumber("maxEstimatedPromptTokens", DEFAULTS.maxEstimatedPromptTokens);
  if (maxEstimatedPromptTokens > 0 && estimatedPromptTokens > maxEstimatedPromptTokens) {
    const error = new Error(`Estimated prompt is too large for guarded OpenRouter routing: ~${estimatedPromptTokens} tokens > limit ${maxEstimatedPromptTokens}`);
    error.status = 413;
    error.estimatedPromptTokens = estimatedPromptTokens;
    error.maxEstimatedPromptTokens = maxEstimatedPromptTokens;
    throw error;
  }
  return estimatedPromptTokens;
}

function orderCandidates(virtualModel, candidates, requestBody) {
  const now = Date.now();
  const available = [];
  const skippedCooldown = [];
  const skippedUnsupported = [];

  for (const candidate of candidates) {
    const label = candidateLabel(candidate);
    const support = candidateSupportsRequest(candidate, requestBody);
    if (!support.supported) {
      skippedUnsupported.push({ model: label, reason: support.reason });
      continue;
    }

    const state = ensureCandidateState(label);
    if ((state.cooldownUntil || 0) > now) {
      skippedCooldown.push(cooldownView(label, candidate));
    } else {
      available.push({ label, candidate });
    }
  }

  const lastSelected = runtimeState.roles[virtualModel]?.selected;
  if (cfgBool("preferLastSuccessful", DEFAULTS.preferLastSuccessful) && lastSelected) {
    const index = available.findIndex(item => item.label === lastSelected);
    if (index > 0) {
      const [preferred] = available.splice(index, 1);
      available.unshift(preferred);
    }
  }

  const maxAttempts = Math.max(1, cfgNumber("maxFallbackAttempts", DEFAULTS.maxFallbackAttempts));
  return {
    candidates: available.slice(0, maxAttempts),
    skippedCooldown,
    skippedUnsupported,
    maxAttempts
  };
}

function validateRequestBody(body) {
  if (!body || typeof body !== "object") {
    const error = new Error("Request body must be a JSON object");
    error.status = 400;
    throw error;
  }
  if (!body.model || typeof body.model !== "string") {
    const error = new Error("Field 'model' is required and must be a string");
    error.status = 400;
    throw error;
  }
  if (!Array.isArray(body.messages)) {
    const error = new Error("Field 'messages' is required and must be an array");
    error.status = 400;
    throw error;
  }
}

function checkLocalRateLimit(virtualModel) {
  const windowMs = cfgNumber("rateLimitWindowMs", DEFAULTS.rateLimitWindowMs);
  const maxRequests = cfgNumber("maxRequestsPerWindow", DEFAULTS.maxRequestsPerWindow);
  const minIntervalMs = cfgNumber("minRequestIntervalMs", DEFAULTS.minRequestIntervalMs);
  const now = Date.now();
  const window = (requestWindowsByRole.get(virtualModel) ?? []).filter(ts => now - ts < windowMs);

  if (minIntervalMs > 0 && window.length > 0) {
    const elapsed = now - window[window.length - 1];
    if (elapsed < minIntervalMs) {
      requestWindowsByRole.set(virtualModel, window);
      return { allowed: false, retryAfterMs: Math.max(1000, minIntervalMs - elapsed), reason: "min-interval" };
    }
  }

  if (maxRequests > 0 && window.length >= maxRequests) {
    requestWindowsByRole.set(virtualModel, window);
    const retryAfterMs = Math.max(1000, windowMs - (now - window[0]));
    return { allowed: false, retryAfterMs, reason: "window" };
  }

  window.push(now);
  requestWindowsByRole.set(virtualModel, window);
  return { allowed: true };
}

function requestCacheKey(body) {
  const normalized = { ...body, stream: false };
  return stableStringify(normalized);
}

function getCachedResponse(cacheKey) {
  const ttlMs = cfgNumber("responseCacheTtlMs", DEFAULTS.responseCacheTtlMs);
  if (ttlMs <= 0) return null;

  const entry = responseCacheByKey.get(cacheKey);
  if (!entry) return null;

  if (Date.now() >= entry.expiresAt) {
    responseCacheByKey.delete(cacheKey);
    return null;
  }

  runtimeState.cache.hits += 1;
  const response = cloneJson(entry.response);
  response.fallback = {
    ...(response.fallback || {}),
    cacheHit: true
  };
  return response;
}

function storeCachedResponse(cacheKey, response) {
  const ttlMs = cfgNumber("responseCacheTtlMs", DEFAULTS.responseCacheTtlMs);
  const maxEntries = Math.max(0, cfgNumber("responseCacheMaxEntries", DEFAULTS.responseCacheMaxEntries));
  if (ttlMs <= 0 || maxEntries <= 0) return;

  while (responseCacheByKey.size >= maxEntries) {
    const oldestKey = responseCacheByKey.keys().next().value;
    if (!oldestKey) break;
    responseCacheByKey.delete(oldestKey);
    runtimeState.cache.evictions += 1;
  }

  responseCacheByKey.set(cacheKey, {
    expiresAt: Date.now() + ttlMs,
    response: cloneJson(response)
  });
  runtimeState.cache.stores += 1;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForUpstreamPace(virtualModel) {
  const minDelayMs = cfgNumber("minDelayBetweenUpstreamRequestsMs", DEFAULTS.minDelayBetweenUpstreamRequestsMs);
  if (minDelayMs <= 0) {
    lastUpstreamAtByRole.set(virtualModel, Date.now());
    return;
  }

  const lastStartedAt = lastUpstreamAtByRole.get(virtualModel) || 0;
  const elapsedMs = Date.now() - lastStartedAt;
  const waitMs = Math.max(0, minDelayMs - elapsedMs);

  if (waitMs > 0) {
    runtimeState.roles[virtualModel] = {
      ...(runtimeState.roles[virtualModel] ?? {}),
      pacingDelayMs: waitMs,
      updatedAt: nowIso()
    };
    log(`[${virtualModel}] pacing upstream request for ${waitMs}ms`);
    await sleep(waitMs);
  }

  lastUpstreamAtByRole.set(virtualModel, Date.now());
}

function incrementActive(virtualModel) {
  const maxConcurrent = cfgNumber("maxConcurrentRequests", DEFAULTS.maxConcurrentRequests);
  const current = activeByRole.get(virtualModel) || 0;
  if (maxConcurrent > 0 && current >= maxConcurrent) {
    const error = new Error(`Router is busy for ${virtualModel}; local concurrency limit ${maxConcurrent} reached`);
    error.status = 429;
    error.retryAfterMs = 5000;
    throw error;
  }
  activeByRole.set(virtualModel, current + 1);
}

function decrementActive(virtualModel) {
  const current = activeByRole.get(virtualModel) || 0;
  if (current <= 1) {
    activeByRole.delete(virtualModel);
  } else {
    activeByRole.set(virtualModel, current - 1);
  }
}

async function callCandidate(candidate, requestBody) {
  const label = candidateLabel(candidate);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), cfgNumber("requestTimeoutMs", DEFAULTS.requestTimeoutMs));

  const body = {
    ...requestBody,
    model: candidate.model,
    stream: false
  };

  markCandidateAttempt(label);
  runtimeState.upstreamRequests += 1;

  // If shutting down, abort immediately
  if (shuttingDown) {
    clearTimeout(timeout);
    const error = new Error("Router is shutting down");
    error.status = 503;
    throw error;
  }

  // Tie into the global abort for graceful shutdown
  const onGlobalAbort = () => controller.abort();
  activeUpstreamControllers.signal.addEventListener("abort", onGlobalAbort, { once: true });

  try {
    const response = await fetch(`${providerBaseUrl(candidate)}/chat/completions`, {
      method: "POST",
      headers: providerHeaders(candidate),
      body: JSON.stringify(body),
      signal: controller.signal
    });

    const text = await response.text();
    let parsed = null;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      parsed = { raw: text };
    }

    if (!response.ok) {
      const message = parsed?.error?.message || parsed?.message || text || response.statusText;
      const error = new Error(truncate(message));
      error.status = response.status;
      error.retryAfter = response.headers.get("retry-after");
      error.body = parsed;
      throw error;
    }

    if (!hasUsefulContent(parsed)) {
      const error = new Error("Model returned empty response (no content and no tool_calls)");
      error.status = 502;
      error.emptyResponse = true;
      throw error;
    }

    runtimeState.upstreamSuccesses += 1;
    return parsed;
  } catch (error) {
    runtimeState.upstreamFailures += 1;
    throw error;
  } finally {
    clearTimeout(timeout);
    activeUpstreamControllers.signal.removeEventListener("abort", onGlobalAbort);
  }
}

function toSseResponse(res, upstreamResponse, virtualModel) {
  const message = upstreamResponse?.choices?.[0]?.message ?? {};
  const content = message.content ?? "";
  const toolCalls = message.tool_calls ?? [];
  const id = upstreamResponse?.id || `chatcmpl-router-${Date.now()}`;
  const created = Math.floor(Date.now() / 1000);

  res.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache",
    connection: "keep-alive",
    "access-control-allow-origin": "*"
  });

  res.write(`data: ${JSON.stringify({
    id,
    object: "chat.completion.chunk",
    created,
    model: virtualModel,
    choices: [{ index: 0, delta: { role: "assistant" }, finish_reason: null }]
  })}\n\n`);

  if (content) {
    res.write(`data: ${JSON.stringify({
      id,
      object: "chat.completion.chunk",
      created,
      model: virtualModel,
      choices: [{ index: 0, delta: { content }, finish_reason: null }]
    })}\n\n`);
  }

  for (let i = 0; i < toolCalls.length; i++) {
    const tc = toolCalls[i];
    res.write(`data: ${JSON.stringify({
      id,
      object: "chat.completion.chunk",
      created,
      model: virtualModel,
      choices: [{
        index: 0,
        delta: {
          tool_calls: [{
            index: i,
            id: tc.id,
            type: tc.type || "function",
            function: tc.function
          }]
        },
        finish_reason: null
      }]
    })}\n\n`);
  }

  res.write(`data: ${JSON.stringify({
    id,
    object: "chat.completion.chunk",
    created,
    model: virtualModel,
    choices: [{ index: 0, delta: {}, finish_reason: "stop" }]
  })}\n\n`);
  res.write("data: [DONE]\n\n");
  res.end();
}

function initRoleState(virtualModel) {
  runtimeState.roles[virtualModel] = {
    ...(runtimeState.roles[virtualModel] ?? {}),
    requests: (runtimeState.roles[virtualModel]?.requests ?? 0) + 1,
    selected: runtimeState.roles[virtualModel]?.selected ?? null,
    processing: true,
    attempts: [],
    skippedCooldown: [],
    skippedUnsupported: [],
    error: null,
    updatedAt: nowIso()
  };
}

function finishRoleState(virtualModel, patch = {}) {
  runtimeState.roles[virtualModel] = {
    ...(runtimeState.roles[virtualModel] ?? {}),
    processing: false,
    updatedAt: nowIso(),
    ...patch
  };
}

async function completeWithFallback(body) {
  validateRequestBody(body);

  const virtualModel = body.model;
  const candidatesRaw = config.virtualModels?.[virtualModel];
  const candidates = Array.isArray(candidatesRaw) ? candidatesRaw : (candidatesRaw?.models ?? []);
  if (!Array.isArray(candidates) || candidates.length === 0) {
    const known = Object.keys(config.virtualModels ?? {});
    const error = new Error(`Unknown virtual model: ${virtualModel}. Known models: ${known.join(", ")}`);
    error.status = 404;
    throw error;
  }

  const requestBody = normalizeRequestBody(body);
  runtimeState.totalRequests += 1;
  runtimeState.chatRequests += 1;
  initRoleState(virtualModel);

  try {
    const estimatedPromptTokens = ensurePromptWithinBudget(requestBody);
    runtimeState.roles[virtualModel] = {
      ...runtimeState.roles[virtualModel],
      estimatedPromptTokens
    };
  } catch (error) {
    runtimeState.localRejects.promptTooLarge += 1;
    runtimeState.failedRequests += 1;
    finishRoleState(virtualModel, {
      error: error.message,
      estimatedPromptTokens: error.estimatedPromptTokens,
      maxEstimatedPromptTokens: error.maxEstimatedPromptTokens
    });
    throw error;
  }

  const cacheKey = requestCacheKey(requestBody);
  const cachedResponse = getCachedResponse(cacheKey);
  if (cachedResponse) {
    runtimeState.cacheServedRequests += 1;
    runtimeState.successfulRequests += 1;
    finishRoleState(virtualModel, {
      cacheHit: true,
      selected: cachedResponse?.fallback?.selected ?? runtimeState.roles[virtualModel]?.selected ?? null,
      attempts: [],
      error: null
    });
    log(`[${virtualModel}] cache hit; no upstream request`);
    return cachedResponse;
  }

  const activeCooldown = getRoleCooldown(virtualModel);
  if (activeCooldown) {
    runtimeState.localRejects.roleCooldown += 1;
    const error = new Error(`Local router cooldown active for ${virtualModel}: ${activeCooldown.reason}`);
    error.status = 429;
    error.retryAfterMs = activeCooldown.retryAfterMs;
    runtimeState.failedRequests += 1;
    finishRoleState(virtualModel, { error: error.message });
    throw error;
  }

  const rateLimit = checkLocalRateLimit(virtualModel);
  if (!rateLimit.allowed) {
    if (rateLimit.reason === "min-interval") runtimeState.localRejects.tooFrequent += 1;
    else runtimeState.localRejects.rateLimited += 1;
    const error = new Error(rateLimit.reason === "min-interval"
      ? `Local router minimum interval reached for ${virtualModel}`
      : `Local router rate limit reached for ${virtualModel}`);
    error.status = 429;
    error.retryAfterMs = rateLimit.retryAfterMs;
    runtimeState.failedRequests += 1;
    finishRoleState(virtualModel, { error: error.message });
    throw error;
  }

  try {
    incrementActive(virtualModel);
  } catch (error) {
    runtimeState.localRejects.busy += 1;
    runtimeState.failedRequests += 1;
    finishRoleState(virtualModel, { error: error.message });
    throw error;
  }

  try {
    const plan = orderCandidates(virtualModel, candidates, requestBody);
    const attempts = [];
    runtimeState.roles[virtualModel] = {
      ...runtimeState.roles[virtualModel],
      skippedCooldown: plan.skippedCooldown.map(({ candidate, ...rest }) => rest),
      skippedUnsupported: plan.skippedUnsupported,
      maxAttempts: plan.maxAttempts
    };

    if (plan.candidates.length === 0) {
      runtimeState.localRejects.noCandidate += 1;
      runtimeState.failedRequests += 1;
      const reason = plan.skippedCooldown.length > 0
        ? `All candidates for ${virtualModel} are cooling down; no upstream request sent`
        : `No compatible candidates for ${virtualModel}; no upstream request sent`;
      const error = new Error(reason);
      error.status = 503;
      error.cooldowns = plan.skippedCooldown.map(({ candidate, ...rest }) => rest);
      error.unsupported = plan.skippedUnsupported;
      finishRoleState(virtualModel, {
        attempts,
        skippedCooldown: error.cooldowns,
        skippedUnsupported: plan.skippedUnsupported,
        error: error.message
      });
      throw error;
    }

    for (const { candidate, label } of plan.candidates) {
      try {
        log(`[${virtualModel}] trying ${label}`);
        await waitForUpstreamPace(virtualModel);
        const response = await callCandidate(candidate, requestBody);
        response.model = virtualModel;
        response.fallback = {
          selected: label,
          attempts,
          skippedCooldown: plan.skippedCooldown.map(({ candidate: _candidate, ...rest }) => rest),
          skippedUnsupported: plan.skippedUnsupported,
          cacheHit: false
        };
        const usage = normalizeUsage(response?.usage);
        response.usage = {
          ...(response.usage || {}),
          prompt_tokens: usage.prompt,
          completion_tokens: usage.completion,
          total_tokens: usage.total
        };
        markCandidateSuccess(label);
        recordUsage(virtualModel, label, usage);
        clearRoleCooldown(virtualModel);
        runtimeState.successfulRequests += 1;
        finishRoleState(virtualModel, {
          selected: label,
          attempts,
          error: null,
          lastUsage: usage,
          usage: cloneJson(runtimeState.roles[virtualModel]?.usage || zeroUsage()),
          tokens: cloneJson(runtimeState.roles[virtualModel]?.usage || zeroUsage()),
          modelTokens: cloneJson(runtimeState.roles[virtualModel]?.modelTokens || {}),
          cacheHit: false,
          pacingDelayMs: 0
        });
        storeCachedResponse(cacheKey, response);
        log(`[${virtualModel}] success ${label} (${usage.prompt} in / ${usage.completion} out / ${usage.total} total)`);
        return response;
      } catch (error) {
        const status = error.name === "AbortError" ? "timeout" : error.status || "error";
        const message = error.name === "AbortError" ? "request timed out" : error.message;
        const candidateState = markCandidateFailure(label, error);
        const roleCooldown = setRoleCooldown(virtualModel, error);
        attempts.push({
          model: label,
          status,
          message: truncate(message),
          cooldownUntil: candidateState.cooldownUntil ? new Date(candidateState.cooldownUntil).toISOString() : null,
          cooldownReason: candidateState.cooldownReason || null,
          roleCooldownUntil: roleCooldown?.until || null,
          roleCooldownReason: roleCooldown?.reason || null
        });
        runtimeState.roles[virtualModel] = {
          ...runtimeState.roles[virtualModel],
          attempts,
          updatedAt: nowIso()
        };
        log(`[${virtualModel}] failed ${label}: ${status} ${truncate(message, 200)}`);
        if (!shouldTryNextCandidate(error)) break;
      }
    }

    const error = new Error("All attempted fallback models failed");
    const retryCooldown = getRoleCooldown(virtualModel);
    error.status = retryCooldown ? 429 : 502;
    error.retryAfterMs = retryCooldown?.retryAfterMs;
    error.attempts = attempts;
    runtimeState.failedRequests += 1;
    finishRoleState(virtualModel, { attempts, error: error.message });
    throw error;
  } finally {
    decrementActive(virtualModel);
  }
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks).toString("utf8");
}

const server = http.createServer(async (req, res) => {
  try {
    // Reject new requests during shutdown
    if (shuttingDown) {
      json(res, 503, { error: { message: "Router is shutting down" } });
      return;
    }

    if (req.method === "OPTIONS") {
      res.writeHead(204, {
        "access-control-allow-origin": "*",
        "access-control-allow-headers": "content-type, authorization",
        "access-control-allow-methods": "GET, POST, OPTIONS"
      });
      res.end();
      return;
    }

    const parsedUrl = new URL(req.url, `http://${config.host}:${config.port}`);
    const pathname = parsedUrl.pathname;

    if (req.method === "GET" && (pathname === "/" || pathname === "/health")) {
      json(res, 200, {
        ok: true,
        service: SERVER_TITLE,
        endpoint: `http://${config.host}:${config.port}/v1`,
        models: Object.keys(config.virtualModels ?? {}),
        startedAt: runtimeState.startedAt
      });
      return;
    }

    if (req.method === "GET" && pathname === "/config") {
      json(res, 200, publicConfig());
      return;
    }

    if (req.method === "GET" && pathname === "/status") {
      json(res, 200, publicStatus());
      return;
    }

    if (req.method === "POST" && pathname === "/reset-stats") {
      const now = Date.now();
      if (now - lastResetAt < 5000) {
        json(res, 429, { ok: false, message: "Reset cooldown: wait 5 seconds" });
        return;
      }
      lastResetAt = now;
      resetRuntimeState();
      json(res, 200, { ok: true, message: "Statistics reset", startedAt: runtimeState.startedAt });
      return;
    }

    if (req.method === "GET" && (pathname === "/v1/models" || pathname === "/v1/model" || pathname === "/models")) {
      const data = Object.keys(config.virtualModels ?? {}).map((id) => {
        const entry = config.virtualModels[id];
        const ctxLen = (entry && typeof entry === 'object' && !Array.isArray(entry))
          ? entry.contextLength
          : null;
        return {
          id,
          object: "model",
          created: 0,
          owned_by: "ai-router",
          context_length: ctxLen ?? cfgNumber("maxEstimatedPromptTokens", DEFAULTS.maxEstimatedPromptTokens)
        };
      });
      json(res, 200, { object: "list", data });
      return;
    }

    if (req.method === "POST" && pathname === "/v1/chat/completions") {
      const raw = await readBody(req);
      const body = raw ? JSON.parse(raw) : {};
      const wantsStream = body.stream === true;
      const response = await completeWithFallback(body);

      if (wantsStream) {
        toSseResponse(res, response, body.model);
      } else {
        json(res, 200, response);
      }
      return;
    }

    json(res, 404, { error: { message: "Endpoint not found" } });
  } catch (error) {
    if (error.status === 400) runtimeState.localRejects.badRequest += 1;
    const headers = {};
    if (error.retryAfterMs) {
      headers["retry-after"] = String(Math.ceil(error.retryAfterMs / 1000));
    }
    json(res, error.status || 500, {
      error: {
        message: error.message,
        attempts: error.attempts,
        cooldowns: error.cooldowns,
        unsupported: error.unsupported,
        retryAfterMs: error.retryAfterMs,
        estimatedPromptTokens: error.estimatedPromptTokens,
        maxEstimatedPromptTokens: error.maxEstimatedPromptTokens
      }
    }, headers);
  }
});

server.listen(config.port, config.host, () => {
  log(`${SERVER_TITLE} listening at http://${config.host}:${config.port}/v1`);
  log(`Virtual models: ${Object.keys(config.virtualModels ?? {}).join(", ")}`);
  log(`Guards: maxFallbackAttempts=${cfgNumber("maxFallbackAttempts", DEFAULTS.maxFallbackAttempts)}, maxConcurrentRequests=${cfgNumber("maxConcurrentRequests", DEFAULTS.maxConcurrentRequests)}, maxRequestsPerWindow=${cfgNumber("maxRequestsPerWindow", DEFAULTS.maxRequestsPerWindow)}/${cfgNumber("rateLimitWindowMs", DEFAULTS.rateLimitWindowMs)}ms, minRequestIntervalMs=${cfgNumber("minRequestIntervalMs", DEFAULTS.minRequestIntervalMs)}, minDelayBetweenUpstreamRequestsMs=${cfgNumber("minDelayBetweenUpstreamRequestsMs", DEFAULTS.minDelayBetweenUpstreamRequestsMs)}, maxCompletionTokens=${cfgNumber("maxCompletionTokens", DEFAULTS.maxCompletionTokens)}`);
});
