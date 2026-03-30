/**
 * CozyEmployee Practice — Exercise all DPN/REN patterns against a live Box.
 * Box: choice-robin-05555 (stepfun/step-3.5-flash:free)
 * 
 * Resilient version: catches failures, continues, reports results.
 */

import { Box } from '@upstash/box';
import { z } from 'zod';

process.env.UPSTASH_BOX_API_KEY = process.env.UPSTASH_BOX_API_KEY;

const box = await Box.getByName('choice-robin-05555');
console.log(`📦 Connected: ${box.id}\n`);

const results = [];

async function runPattern(name, type, fn) {
  console.log('═'.repeat(60));
  console.log(`${type === 'dpn' ? '🧠' : type === 'ren' ? '⚡' : '🔗'} ${name}`);
  console.log('═'.repeat(60));
  const start = Date.now();
  try {
    const r = await fn();
    const ms = Date.now() - start;
    console.log(`✅ (${ms}ms)\n`);
    results.push({ name, type, status: 'ok', ms, ...r });
    return r;
  } catch (e) {
    const ms = Date.now() - start;
    console.log(`❌ ${e.message} (${ms}ms)\n`);
    results.push({ name, type, status: 'fail', ms, error: e.message });
    return null;
  }
}

// ─────────────────────────────────────────────────────────────
// PATTERN 1: Simple DPN — Basic Reasoning (free-form)
// ─────────────────────────────────────────────────────────────
await runPattern('PATTERN 1: DPN — Basic Reasoning', 'dpn', async () => {
  const r = await box.agent.run({
    prompt: `You are a pragmatic engineer. Explain the trade-offs between 
microservices and monoliths for a team of 5 developers building an MVP. 
Be concise — 3 bullet points max.`,
    timeout: 30000,
  });
  console.log(r.result);
  return { output: r.result };
});

// ─────────────────────────────────────────────────────────────
// PATTERN 2: DPN with Structured Output (simpler schema)
// ─────────────────────────────────────────────────────────────
await runPattern('PATTERN 2: DPN — Structured Output', 'dpn', async () => {
  // Use a simpler schema that's easier for free models
  const Review = z.object({
    language: z.string(),
    issues: z.array(z.string()),
    score: z.number(),
  });

  const r = await box.agent.run({
    prompt: `Return a JSON object reviewing this Python code. Include: language ("python"), 
issues (list of strings describing problems), score (1-10).

Code:
def process(users):
    results = []
    for u in users:
        query = f"INSERT INTO users (name) VALUES ('{u['name']}')"
        db.execute(query)
        results.append(u)
    return results

Return ONLY valid JSON, no markdown.`,
    responseSchema: Review,
    timeout: 30000,
  });
  console.log(JSON.stringify(r.result, null, 2));
  return { output: r.result };
});

// ─────────────────────────────────────────────────────────────
// PATTERN 3: DPN — Architecture Decision (free-form, reliable)
// ─────────────────────────────────────────────────────────────
await runPattern('PATTERN 3: DPN — Architecture Decision', 'dpn', async () => {
  const r = await box.agent.run({
    prompt: `We need real-time notifications. Stack: Express + PostgreSQL + Redis.
Users: 10K DAU. Budget: minimal.

Choose between: SSE, WebSocket/Socket.IO, Polling+Redis pub/sub, or managed Pusher.

Reply in EXACTLY this format (no extra text):
WINNER: <name>
REASON: <one sentence>
RISK: <one sentence>`,
    timeout: 30000,
  });
  console.log(r.result);
  return { output: r.result };
});

// ─────────────────────────────────────────────────────────────
// PATTERN 4: REN — Deterministic Computation (no LLM)
// ─────────────────────────────────────────────────────────────
await runPattern('PATTERN 4: REN — Deterministic Compute', 'ren', async () => {
  await box.files.write({
    path: '/work/analyze.py',
    content: `import json, statistics

times = [45, 52, 38, 120, 41, 55, 39, 200, 43, 48, 51, 37, 42, 180, 44, 50]
mean = statistics.mean(times)
stdev = statistics.stdev(times)
outliers = [t for t in times if t > mean + 2 * stdev]

print(json.dumps({
    "count": len(times),
    "mean_ms": round(mean, 2),
    "p95_ms": sorted(times)[int(len(times) * 0.95)],
    "outliers": outliers,
    "healthy": len(outliers) <= 2
}, indent=2))`
  });
  const r = await box.exec.command('python3 /work/analyze.py');
  console.log(r.stdout);
  return { output: JSON.parse(r.stdout) };
});

// ─────────────────────────────────────────────────────────────
// PATTERN 5: REN — File Processing Pipeline
// ─────────────────────────────────────────────────────────────
await runPattern('PATTERN 5: REN — File Pipeline', 'ren', async () => {
  // Write raw CSV-like data
  await box.files.write({
    path: '/work/employees.csv',
    content: `name,dept,salary,years
Alice,Engineering,120000,5
Bob,Engineering,95000,2
Carol,Sales,85000,3
Dave,Sales,110000,7
Eve,Engineering,140000,8
Frank,Sales,72000,1`
  });
  
  // Write processing script
  await box.files.write({
    path: '/work/process.py',
    content: `import json, csv
from collections import defaultdict

with open('/work/employees.csv') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

depts = defaultdict(lambda: {"people": [], "total_salary": 0})
for r in rows:
    d = depts[r["dept"]]
    d["people"].append(r["name"])
    d["total_salary"] += int(r["salary"])

result = {dept: {
    "headcount": len(info["people"]),
    "avg_salary": round(info["total_salary"] / len(info["people"])),
    "people": info["people"]
} for dept, info in depts.items()}

print(json.dumps(result, indent=2))`
  });

  const r = await box.exec.command('python3 /work/process.py');
  console.log(r.stdout);
  return { output: JSON.parse(r.stdout) };
});

// ─────────────────────────────────────────────────────────────
// PATTERN 6: Hybrid — DPN Plans, REN Executes
// ─────────────────────────────────────────────────────────────
await runPattern('PATTERN 6: Hybrid DPN→REN', 'hybrid', async () => {
  // Step 1: DPN generates transformation code
  const plan = await box.agent.run({
    prompt: `Write a complete Python script that:
1. Reads this JSON: [{"x": 1, "y": 10}, {"x": 2, "y": 20}, {"x": 3, "y": 30}, {"x": 4, "y": 40}]
2. Computes linear regression (slope and intercept)
3. Predicts y for x=5 and x=10
4. Prints JSON with keys: slope, intercept, predictions

Return ONLY the Python code, no explanation, no markdown fences.`,
    timeout: 30000,
  });

  let code = String(plan.result).replace(/```python?\n?/g, '').replace(/```\n?/g, '').trim();
  console.log(`DPN generated ${code.length} chars of code`);

  // Step 2: REN executes
  await box.files.write({ path: '/work/regression.py', content: code });
  const exec = await box.exec.command('python3 /work/regression.py 2>&1');
  console.log(`REN output:\n${exec.stdout}`);

  try {
    return { output: JSON.parse(exec.stdout), dpn_ms: plan.cost.computeMs };
  } catch {
    return { output: exec.stdout, dpn_ms: plan.cost.computeMs };
  }
});

// ─────────────────────────────────────────────────────────────
// PATTERN 7: Fan-Out — Parallel DPN Analysis (same box, sequential API calls)
// ─────────────────────────────────────────────────────────────
await runPattern('PATTERN 7: Fan-Out Parallel Perspectives', 'dpn', async () => {
  const problem = `Should we migrate from REST to GraphQL?
Current: 50 endpoints, 3 frontends, 4 devs. Pain: over-fetching, multiple round trips.`;

  const start = Date.now();
  const [eng, arch, biz] = await Promise.all([
    box.agent.run({
      prompt: `You are a backend engineer. One paragraph: should we migrate to GraphQL? Focus on implementation. End with RECOMMEND: YES or NO.`,
      timeout: 30000,
    }),
    box.agent.run({
      prompt: `You are a systems architect. One paragraph: should we migrate to GraphQL? Focus on scalability. End with RECOMMEND: YES or NO.`,
      timeout: 30000,
    }),
    box.agent.run({
      prompt: `You are a product manager. One paragraph: should we migrate to GraphQL? Focus on business impact. End with RECOMMEND: YES or NO.`,
      timeout: 30000,
    }),
  ]);
  const totalMs = Date.now() - start;

  console.log(`👷 Engineer: ${eng.result}\n`);
  console.log(`🏗️ Architect: ${arch.result}\n`);
  console.log(`💼 Product: ${biz.result}\n`);
  console.log(`⏱️ Parallel wall time: ${totalMs}ms`);

  return { 
    engineer: eng.result, 
    architect: arch.result, 
    product: biz.result,
    parallel_ms: totalMs 
  };
});

// ─────────────────────────────────────────────────────────────
// PATTERN 8: Knowledge Extraction — DPN parses unstructured data
// ─────────────────────────────────────────────────────────────
await runPattern('PATTERN 8: DPN — Knowledge Extraction', 'dpn', async () => {
  const logs = `
[2026-03-29 03:26] Started E2B Desktop agent exploration
[2026-03-29 03:45] Found: CLI-first approach (commands.run + xdotool) >> SDK mouse/keyboard
[2026-03-29 04:00] Bug: get_window_title() needs window_id parameter
[2026-03-29 04:15] Decision: Use Vast.ai for prototyping, RunPod for eval, Modal for production
[2026-03-29 04:30] Failed: RunPod pod deployment - CUDA version mismatch
[2026-03-29 04:45] Lesson: Always test on target hardware before committing to GPU provider
[2026-03-29 05:00] Built DesktopAgent class at e2b-desktop-agent.py`;

  const r = await box.agent.run({
    prompt: `Extract structured knowledge from these log entries. Return EXACTLY this format (no extra text):

DECISIONS:
- <what was decided and why>
LESSONS:
- <what was learned>
ANTI_PATTERNS:
- <what to avoid>
OPEN:
- <unresolved questions>

Logs:
${logs}`,
    timeout: 30000,
  });
  console.log(r.result);
  return { output: r.result };
});

// ─────────────────────────────────────────────────────────────
// SUMMARY
// ─────────────────────────────────────────────────────────────
console.log('\n' + '═'.repeat(60));
console.log('📊 PRACTICE RESULTS');
console.log('═'.repeat(60));

let totalMs = 0, passed = 0, failed = 0;
for (const r of results) {
  const icon = r.status === 'ok' ? '✅' : '❌';
  console.log(`${icon} ${r.name.padEnd(45)} ${String(r.ms).padStart(6)}ms  [${r.type}]`);
  totalMs += r.ms;
  if (r.status === 'ok') passed++; else failed++;
}

console.log(`\n📈 ${passed} passed, ${failed} failed | ⏱️ ${totalMs}ms total | 💰 $0.00`);
console.log(`📦 Box: choice-robin-05555 (stepfun/step-3.5-flash:free)\n`);
