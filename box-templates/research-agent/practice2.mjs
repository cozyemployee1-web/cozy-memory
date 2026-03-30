/**
 * CozyEmployee Practice — Round 2 (fixed paths + timeouts)
 * Box: choice-robin-05555 (stepfun/step-3.5-flash:free)
 */

import { Box } from '@upstash/box';
import { z } from 'zod';

process.env.UPSTASH_BOX_API_KEY = process.env.UPSTASH_BOX_API_KEY;

const box = await Box.getByName('choice-robin-05555');
const WORK = '/workspace/home';
console.log(`📦 Connected: ${box.id}, work dir: ${WORK}\n`);

const results = [];

async function run(name, type, fn) {
  console.log('─'.repeat(50));
  console.log(`${type === 'dpn' ? '🧠' : type === 'ren' ? '⚡' : '🔗'} ${name}`);
  console.log('─'.repeat(50));
  const start = Date.now();
  try {
    const r = await fn();
    const ms = Date.now() - start;
    console.log(`✅ (${ms}ms)\n`);
    results.push({ name, type, ok: true, ms });
    return r;
  } catch (e) {
    const ms = Date.now() - start;
    console.log(`❌ ${e.message} (${ms}ms)\n`);
    results.push({ name, type, ok: false, ms, error: e.message });
    return null;
  }
}

// ─── PATTERN 4: REN — Deterministic Compute ───────────────
await run('PATTERN 4: REN — Deterministic Compute', 'ren', async () => {
  await box.files.write({
    path: `${WORK}/analyze.py`,
    content: `import json, statistics
times = [45, 52, 38, 120, 41, 55, 39, 200, 43, 48, 51, 37, 42, 180, 44, 50]
mean = statistics.mean(times)
stdev = statistics.stdev(times)
outliers = [t for t in times if t > mean + 2 * stdev]
print(json.dumps({
    "count": len(times), "mean_ms": round(mean, 2),
    "p95_ms": sorted(times)[int(len(times) * 0.95)],
    "outliers": outliers, "healthy": len(outliers) <= 2
}, indent=2))`
  });
  const r = await box.exec.command(`python3 ${WORK}/analyze.py`);
  console.log(r.stdout);
  return JSON.parse(r.stdout);
});

// ─── PATTERN 5: REN — File Pipeline ───────────────────────
await run('PATTERN 5: REN — CSV Pipeline', 'ren', async () => {
  await box.files.write({
    path: `${WORK}/employees.csv`,
    content: `name,dept,salary,years
Alice,Engineering,120000,5
Bob,Engineering,95000,2
Carol,Sales,85000,3
Dave,Sales,110000,7
Eve,Engineering,140000,8
Frank,Sales,72000,1`
  });
  await box.files.write({
    path: `${WORK}/pipeline.py`,
    content: `import json, csv
from collections import defaultdict
with open('${WORK}/employees.csv') as f:
    rows = list(csv.DictReader(f))
depts = defaultdict(lambda: {"people": [], "total": 0})
for r in rows:
    depts[r["dept"]]["people"].append(r["name"])
    depts[r["dept"]]["total"] += int(r["salary"])
result = {d: {"headcount": len(i["people"]), 
              "avg_salary": round(i["total"]/len(i["people"])),
              "people": i["people"]} for d,i in depts.items()}
print(json.dumps(result, indent=2))`
  });
  const r = await box.exec.command(`python3 ${WORK}/pipeline.py`);
  console.log(r.stdout);
  return JSON.parse(r.stdout);
});

// ─── PATTERN 6: Hybrid DPN→REN ────────────────────────────
await run('PATTERN 6: Hybrid DPN→REN', 'hybrid', async () => {
  const plan = await box.agent.run({
    prompt: `Write a Python script that computes mean, median, and standard deviation 
of [12, 15, 18, 22, 25, 28, 30, 35, 40, 45]. Return ONLY raw Python code, 
no markdown, no explanation. Start with "import"`,
    timeout: 60000,
  });
  let code = String(plan.result).replace(/```python?\n?/g, '').replace(/```\n?/g, '').trim();
  // Ensure it starts with import
  if (!code.startsWith('import')) {
    const idx = code.indexOf('import');
    if (idx >= 0) code = code.slice(idx);
  }
  console.log(`DPN generated code (${code.length} chars)`);
  
  await box.files.write({ path: `${WORK}/gen.py`, content: code });
  const exec = await box.exec.command(`python3 ${WORK}/gen.py 2>&1`);
  console.log(`Output:\n${exec.stdout}`);
  return { code_length: code.length, output: exec.stdout };
});

// ─── PATTERN 7: Fan-Out (sequential to avoid rate limit) ──
await run('PATTERN 7: Sequential Multi-Perspective', 'dpn', async () => {
  const problem = `Should we migrate REST to GraphQL? 50 endpoints, 3 frontends, 4 devs. Pain: over-fetching.`;

  // Run sequentially to avoid free model rate limiting
  console.log('  👷 Engineer...');
  const eng = await box.agent.run({
    prompt: `You are a backend engineer. In 2 sentences: should we migrate to GraphQL? End with RECOMMEND: YES or NO.`,
    timeout: 60000,
  });
  console.log(`  ${eng.result}\n`);

  console.log('  🏗️ Architect...');
  const arch = await box.agent.run({
    prompt: `You are a systems architect. In 2 sentences: should we migrate to GraphQL? Focus on caching. End with RECOMMEND: YES or NO.`,
    timeout: 60000,
  });
  console.log(`  ${arch.result}\n`);

  console.log('  💼 Product...');
  const biz = await box.agent.run({
    prompt: `You are a product manager. In 2 sentences: should we migrate to GraphQL? Focus on velocity. End with RECOMMEND: YES or NO.`,
    timeout: 60000,
  });
  console.log(`  ${biz.result}`);

  return { eng: eng.result, arch: arch.result, biz: biz.result };
});

// ─── PATTERN 8: Knowledge Extraction ──────────────────────
await run('PATTERN 8: DPN — Knowledge Extraction', 'dpn', async () => {
  const logs = `[03:26] Started E2B Desktop exploration
[03:45] Found: CLI-first (xdotool) >> SDK mouse/keyboard
[04:00] Bug: get_window_title() needs window_id
[04:15] Decision: Vast.ai for prototype, RunPod for eval, Modal for production
[04:30] Failed: RunPod deployment - CUDA version mismatch
[04:45] Lesson: Always test on target hardware before committing
[05:00] Built DesktopAgent class`;

  const r = await box.agent.run({
    prompt: `Extract from these logs. Reply in EXACTLY this format:

DECISIONS:
- <decision>
LESSONS:
- <lesson>
BUGS:
- <bug>

Logs:
${logs}`,
    timeout: 60000,
  });
  console.log(r.result);
  return r.result;
});

// ─── PATTERN 9: Data Validation (REN) ─────────────────────
await run('PATTERN 9: REN — Data Validation', 'ren', async () => {
  await box.files.write({
    path: `${WORK}/validate.py`,
    content: `import json, re

records = [
    {"name": "Alice", "email": "alice@example.com", "age": 30},
    {"name": "", "email": "bad-email", "age": -5},
    {"name": "Carol", "email": "carol@test.co", "age": 25},
    {"name": "Dave", "email": "dave@", "age": 200},
    {"name": "Eve", "email": "eve@work.io", "age": 28},
]

email_re = re.compile(r'^[\\w.+-]+@[\\w-]+\\.[a-zA-Z]{2,}$')
valid, errors = [], []

for i, r in enumerate(records):
    errs = []
    if not r.get("name"): errs.append("empty name")
    if not email_re.match(r.get("email", "")): errs.append(f"invalid email: {r['email']}")
    age = r.get("age", 0)
    if not (0 < age < 150): errs.append(f"invalid age: {age}")
    if errs:
        errors.append({"row": i, "record": r, "errors": errs})
    else:
        valid.append(r)

print(json.dumps({"valid_count": len(valid), "error_count": len(errors),
                   "errors": errors, "valid_records": valid}, indent=2))`
  });
  const r = await box.exec.command(`python3 ${WORK}/validate.py`);
  console.log(r.stdout);
  return JSON.parse(r.stdout);
});

// ─── PATTERN 10: DPN Code Gen + REN Verify ────────────────
await run('PATTERN 10: Hybrid — Code Gen + Verify', 'hybrid', async () => {
  // DPN: generate a function
  const gen = await box.agent.run({
    prompt: `Write a Python function called "fizzbuzz" that takes n and returns a list of strings.
Rules: divisible by 3→"Fizz", by 5→"Buzz", both→"FizzBuzz", else number as string.
Return ONLY raw Python code with the function. No markdown, no explanation.`,
    timeout: 60000,
  });
  
  let code = String(gen.result).replace(/```python?\n?/g, '').replace(/```\n?/g, '').trim();
  
  // Add a test harness
  const fullCode = `${code}

# Verify
result = fizzbuzz(15)
assert result[2] == "Fizz", f"Expected Fizz at 2, got {result[2]}"
assert result[4] == "Buzz", f"Expected Buzz at 4, got {result[4]}"
assert result[14] == "FizzBuzz", f"Expected FizzBuzz at 14, got {result[14]}"
assert result[0] == "1", f"Expected 1 at 0, got {result[0]}"
print(json.dumps({"passed": True, "output": result}))
import json`;

  await box.files.write({ path: `${WORK}/fizzbuzz.py`, content: fullCode });
  const verify = await box.exec.command(`python3 ${WORK}/fizzbuzz.py 2>&1`);
  console.log(`Generated code verified:\n${verify.stdout}`);
  return { verified: 'passed' in verify.stdout };
});

// ─── SUMMARY ───────────────────────────────────────────────
console.log('\n' + '═'.repeat(60));
console.log('📊 ROUND 2 RESULTS');
console.log('═'.repeat(60));

let totalMs = 0, passed = 0, failed = 0;
for (const r of results) {
  const icon = r.ok ? '✅' : '❌';
  console.log(`${icon} ${r.name.padEnd(45)} ${String(r.ms).padStart(6)}ms  [${r.type}]`);
  totalMs += r.ms;
  r.ok ? passed++ : failed++;
}
console.log(`\n📈 ${passed}/${passed+failed} passed | ⏱️ ${(totalMs/1000).toFixed(1)}s total | 💰 $0.00`);
