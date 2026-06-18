import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const serverSource = path.join(root, 'ROUTER', 'server.js');
const tmpRoot = path.join(root, '.tmp-router-guard-tests');

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function readJsonResponse(response) {
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : null;
  } catch {
    return { raw: text };
  }
}

async function startStub(port, queue, records) {
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const raw = Buffer.concat(chunks).toString('utf8');
    let body = null;
    try { body = raw ? JSON.parse(raw) : null; } catch { body = raw; }
    records.push({ method: req.method, url: req.url, body });
    const item = queue.shift() ?? { status: 200, body: okBody(body?.model ?? 'fallback') };
    for (const [key, value] of Object.entries(item.headers ?? {})) res.setHeader(key, value);
    res.writeHead(item.status, { 'content-type': 'application/json', ...(item.headers ?? {}) });
    res.end(JSON.stringify(item.body));
  });
  await new Promise(resolve => server.listen(port, '127.0.0.1', resolve));
  return server;
}

function okBody(model) {
  return {
    id: `chatcmpl-test-${Date.now()}`,
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{ index: 0, message: { role: 'assistant', content: 'OK' }, finish_reason: 'stop' }],
    usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 }
  };
}

async function waitForRouter(child) {
  let output = '';
  child.stdout.on('data', chunk => { output += chunk.toString(); });
  child.stderr.on('data', chunk => { output += chunk.toString(); });
  const started = Date.now();
  while (!output.includes('listening at')) {
    if (Date.now() - started > 5000) throw new Error(`router did not start; output=${output}`);
    await sleep(50);
  }
}

async function withRouter(name, options, fn) {
  const routerPort = options.routerPort;
  const stubPort = options.stubPort;
  const tmp = path.join(tmpRoot, name);
  await fs.rm(tmp, { recursive: true, force: true });
  await fs.mkdir(tmp, { recursive: true });
  await fs.copyFile(serverSource, path.join(tmp, 'server.js'));
  const config = {
    port: routerPort,
    host: '127.0.0.1',
    title: `Guard Test ${name}`,
    openRouterKeyFile: path.join(tmp, 'openrouter.txt'),
    openRouterBaseUrl: `http://127.0.0.1:${stubPort}/v1`,
    requestTimeoutMs: options.requestTimeoutMs ?? 2000,
    maxFallbackAttempts: options.maxFallbackAttempts ?? 1,
    maxConcurrentRequests: 1,
    rateLimitWindowMs: options.rateLimitWindowMs ?? 60000,
    maxRequestsPerWindow: options.maxRequestsPerWindow ?? 100,
    minRequestIntervalMs: options.minRequestIntervalMs ?? 0,
    minDelayBetweenUpstreamRequestsMs: 0,
    rateLimitCooldownMs: 600000,
    providerErrorCooldownMs: 1000,
    timeoutCooldownMs: 1000,
    emptyResponseCooldownMs: 1000,
    roleRetryCooldownMs: options.roleRetryCooldownMs ?? 60000,
    maxCompletionTokens: options.maxCompletionTokens ?? 4096,
    maxEstimatedPromptTokens: options.maxEstimatedPromptTokens ?? 90000,
    responseCacheTtlMs: 0,
    responseCacheMaxEntries: 0,
    fallbackOnRateLimit: false,
    preferLastSuccessful: true,
    virtualModels: {
      Test: options.candidates ?? [
        { provider: 'openrouter', model: 'first' },
        { provider: 'openrouter', model: 'second' }
      ]
    }
  };
  await fs.writeFile(path.join(tmp, 'openrouter.txt'), 'dummy-key\n', 'utf8');
  await fs.writeFile(path.join(tmp, 'config.json'), JSON.stringify(config, null, 2), 'utf8');
  const records = [];
  const stub = await startStub(stubPort, options.queue ?? [], records);
  const child = spawn(process.execPath, ['server.js'], { cwd: tmp, stdio: ['ignore', 'pipe', 'pipe'] });
  try {
    await waitForRouter(child);
    const base = `http://127.0.0.1:${routerPort}`;
    const post = (content, extra = {}) => fetch(`${base}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model: 'Test', messages: [{ role: 'user', content }], ...extra })
    });
    await fn({ base, post, records });
  } finally {
    child.kill('SIGTERM');
    await new Promise(resolve => child.once('exit', resolve));
    await new Promise(resolve => stub.close(resolve));
  }
}

async function testGetEndpointsNoUpstream() {
  await withRouter('get-endpoints', { routerPort: 39871, stubPort: 39870 }, async ({ base, records }) => {
    for (const route of ['/health', '/config', '/status', '/v1/models']) {
      const response = await fetch(`${base}${route}`);
      assert(response.status === 200, `${route} status ${response.status}`);
    }
    assert(records.length === 0, `GET endpoints made upstream calls: ${records.length}`);
    const status = await readJsonResponse(await fetch(`${base}/status`));
    assert(status.upstreamRequests === 0, `status.upstreamRequests=${status.upstreamRequests}`);
  });
}

async function testClampMaxTokens() {
  await withRouter('clamp', {
    routerPort: 39873,
    stubPort: 39872,
    queue: [{ status: 200, body: okBody('first') }]
  }, async ({ post, records }) => {
    const response = await post('clamp me', { max_tokens: 65536 });
    assert(response.status === 200, `clamp response status ${response.status}`);
    assert(records.length === 1, `expected one upstream, got ${records.length}`);
    assert(records[0].body.max_tokens === 4096, `max_tokens not clamped: ${records[0].body.max_tokens}`);
  });
}

async function testNoCascadeAfter429AndRoleCooldown() {
  await withRouter('no-cascade-429', {
    routerPort: 39875,
    stubPort: 39874,
    queue: [{ status: 429, headers: { 'retry-after': '2' }, body: { error: { message: 'rate limit' } } }]
  }, async ({ post, records }) => {
    const first = await post('first failure');
    const firstBody = await readJsonResponse(first);
    assert(first.status === 429, `first status ${first.status}: ${JSON.stringify(firstBody)}`);
    assert(records.length === 1, `429 cascaded to fallback; upstream records=${records.length}`);
    const second = await post('immediate retry');
    const secondBody = await readJsonResponse(second);
    assert(second.status === 429, `second status ${second.status}: ${JSON.stringify(secondBody)}`);
    assert(records.length === 1, `role cooldown did not block retry; upstream records=${records.length}`);
  });
}

async function testMinIntervalRejectsWithoutUpstream() {
  await withRouter('min-interval', {
    routerPort: 39877,
    stubPort: 39876,
    minRequestIntervalMs: 15000,
    queue: [
      { status: 200, body: okBody('first') },
      { status: 200, body: okBody('second') }
    ]
  }, async ({ post, records }) => {
    const first = await post('one');
    assert(first.status === 200, `first status ${first.status}`);
    const second = await post('two');
    const secondBody = await readJsonResponse(second);
    assert(second.status === 429, `second status ${second.status}: ${JSON.stringify(secondBody)}`);
    assert(records.length === 1, `min interval allowed extra upstream; records=${records.length}`);
  });
}

async function testSkipToolUnsupportedCandidate() {
  await withRouter('skip-tools', {
    routerPort: 39879,
    stubPort: 39878,
    candidates: [
      { provider: 'openrouter', model: 'toolless', supportsTools: false },
      { provider: 'openrouter', model: 'tool-capable' }
    ],
    queue: [{ status: 200, body: okBody('tool-capable') }]
  }, async ({ post, records }) => {
    const response = await post('use tool', {
      tools: [{ type: 'function', function: { name: 'noop', description: 'noop', parameters: { type: 'object', properties: {} } } }]
    });
    const body = await readJsonResponse(response);
    assert(response.status === 200, `tool response status ${response.status}: ${JSON.stringify(body)}`);
    assert(records.length === 1, `expected one upstream, got ${records.length}`);
    assert(records[0].body.model === 'tool-capable', `did not skip unsupported candidate: ${records[0].body.model}`);
    assert(body.fallback.skippedUnsupported?.[0]?.model === 'openrouter:toolless', 'missing skippedUnsupported metadata');
  });
}

const tests = [
  testGetEndpointsNoUpstream,
  testClampMaxTokens,
  testNoCascadeAfter429AndRoleCooldown,
  testMinIntervalRejectsWithoutUpstream,
  testSkipToolUnsupportedCandidate
];

for (const test of tests) {
  await test();
  console.log(`PASS ${test.name}`);
}

console.log('All router guard tests passed without calling OpenRouter.');
