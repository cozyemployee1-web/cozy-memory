/**
 * Cozy Pipeline — Full E2E wiring: Trigger → Box → Agent → Results → Memory → Telegram
 *
 * Usage:
 *   npx tsx pipeline.ts "research topic"
 *   npx tsx pipeline.ts --parallel "topic 1" "topic 2" "topic 3"
 *   npx tsx pipeline.ts --from-cron  (reads topics from stdin)
 */

import { Box } from "@upstash/box";
import { z } from "zod";

// ── Config ─────────────────────────────────────────────────────

const API_KEY = process.env.UPSTASH_BOX_API_KEY!;
const SNAPSHOT_ID = "f517dfbd-31cc-4d0d-81ab-e640f73306e4"; // pydantic-ai-base
const WEBHOOK_URL = process.env.QSTASH_WEBHOOK_URL || "";

process.env.UPSTASH_BOX_API_KEY = API_KEY;

// ── Response Schema ────────────────────────────────────────────

const ResearchResult = z.object({
  topic: z.string(),
  summary: z.string(),
  findings: z.array(z.object({
    topic: z.string(),
    source: z.string(),
    finding: z.string(),
    confidence: z.number(),
    verified: z.boolean(),
  })),
  assumptions: z.array(z.object({
    assumption: z.string(),
    source: z.string(),
    verified: z.boolean(),
    verdict: z.enum(["CONFIRMED", "DENIED", "PARTIAL"]),
    evidence: z.string(),
  })),
  recommendations: z.array(z.string()),
  follow_up_topics: z.array(z.string()),
});

type ResearchResult = z.infer<typeof ResearchResult>;

// ── Agent Script (embedded) ────────────────────────────────────

const AGENT_SCRIPT = `
import asyncio, json, os, sys
from pathlib import Path

# Load env
env_file = Path("/work/.env")
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
import logfire

logfire.configure(send_to_logfire="if-token-present", token=os.environ.get("LOGFIRE_TOKEN", ""))

class ResearchFinding(BaseModel):
    topic: str
    source: str
    finding: str
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool

class Assumption(BaseModel):
    assumption: str
    source: str
    verified: bool
    verdict: str
    evidence: str

class ResearchResult(BaseModel):
    topic: str
    summary: str
    findings: list[ResearchFinding]
    assumptions: list[Assumption]
    recommendations: list[str]
    follow_up_topics: list[str]

class Deps:
    def __init__(self):
        self.working_dir = "/work"

model = OpenAIModel(
    model_name=os.environ.get("AGENT_MODEL", "gpt-4o-mini"),
    api_key=os.environ.get("OPENAI_API_KEY", ""),
)

agent = Agent(model, deps_type=Deps, output_type=ResearchResult, system_prompt="""You are a research agent. Deeply research the given topic.

Process:
1. Understand what needs to be researched
2. Search YouTube for expert explanations (use youtube_search tool)
3. Search the web for current information (use web_search tool)
4. Verify against official documentation (use lookup_docs tool)
5. Compile findings with confidence scores

Be thorough (5+ searches minimum). Verify claims against docs. Focus on actionable insights.
""")

@agent.tool
async def youtube_search(ctx: RunContext[Deps], query: str) -> str:
    import subprocess
    r = subprocess.run(["mcporter", "call", "openclaw-youtube.youtube_search", f"q:{query}"], capture_output=True, text=True, timeout=30)
    return r.stdout[:3000] if r.stdout else "No results"

@agent.tool
async def web_search(ctx: RunContext[Deps], query: str) -> str:
    import subprocess
    r = subprocess.run(["mcporter", "call", "openclaw-searchtool.google_ai_mode", f"q:{query}"], capture_output=True, text=True, timeout=30)
    return r.stdout[:3000] if r.stdout else "No results"

@agent.tool
async def lookup_docs(ctx: RunContext[Deps], library: str, query: str) -> str:
    import subprocess
    resolve = subprocess.run(["mcporter", "call", "context7.resolve-library-id", f"libraryName:{library}", f"query:{query}"], capture_output=True, text=True, timeout=30)
    if resolve.returncode != 0: return f"Could not resolve: {library}"
    try:
        resp = json.loads(resolve.stdout)
        lib_id = resp.get("result", [{}])[0].get("libraryId", "")
        if not lib_id: return f"No ID for {library}"
    except: return f"Parse error for {library}"
    docs = subprocess.run(["mcporter", "call", "context7.query-docs", f"libraryId:{lib_id}", f"query:{query}"], capture_output=True, text=True, timeout=30)
    return docs.stdout[:5000] if docs.stdout else "No docs"

async def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else Path("/work/topic.txt").read_text().strip()
    logfire.info("Starting research", topic=topic)

    with logfire.span("research", topic=topic) as span:
        result = await agent.run(f"Research: {topic}", deps=Deps())
        output = result.output

        span.set_attribute("findings_count", len(output.findings))
        span.set_attribute("assumptions_count", len(output.assumptions))

        # Write structured output
        Path("/work/findings.json").write_text(output.model_dump_json(indent=2))

        # Write markdown summary
        md = f"# {output.topic}\\n\\n{output.summary}\\n\\n"
        md += "## Findings\\n" + "\\n".join(f"- [{f.source}] {f.finding} (confidence: {f.confidence})" for f in output.findings)
        md += "\\n\\n## Assumptions\\n" + "\\n".join(f"- {a.assumption} → {a.verdict}" for a in output.assumptions)
        md += "\\n\\n## Recommendations\\n" + "\\n".join(f"- {r}" for r in output.recommendations)
        Path("/work/summary.md").write_text(md)

        print(output.model_dump_json())
        logfire.info("Research complete", topic=topic, findings=len(output.findings))

asyncio.run(main())
`;

// ── Pipeline Functions ─────────────────────────────────────────

interface PipelineResult {
  topic: string;
  boxId: string;
  result: ResearchResult | null;
  cost: number;
  error?: string;
}

async function runPipeline(topic: string): Promise<PipelineResult> {
  console.log(`\n${"═".repeat(60)}`);
  console.log(`🔬 Pipeline: ${topic}`);
  console.log(`${"═".repeat(60)}`);

  let box: Box | null = null;

  try {
    // Step 1: Create Box from snapshot
    console.log("\n📦 Step 1: Creating Box from snapshot...");
    box = await Box.fromSnapshot(SNAPSHOT_ID);
    console.log(`   Box created: ${box.id}`);

    // Step 2: Write agent script + topic + env
    console.log("\n📝 Step 2: Uploading agent...");
    await box.files.write({ path: "/work/agent.py", content: AGENT_SCRIPT });
    await box.files.write({ path: "/work/topic.txt", content: topic });

    // Upload env
    const envVars = [
      `UPSTASH_VECTOR_REST_URL=${process.env.UPSTASH_VECTOR_REST_URL || ""}`,
      `UPSTASH_VECTOR_REST_TOKEN=${process.env.UPSTASH_VECTOR_REST_TOKEN || ""}`,
      `UPSTASH_REDIS_REST_URL=${process.env.UPSTASH_REDIS_REST_URL || ""}`,
      `UPSTASH_REDIS_REST_TOKEN=${process.env.UPSTASH_REDIS_REST_TOKEN || ""}`,
      `OPENAI_API_KEY=${process.env.OPENAI_API_KEY || ""}`,
      `LOGFIRE_TOKEN=${process.env.LOGFIRE_TOKEN || ""}`,
      `AGENT_MODEL=${process.env.AGENT_MODEL || "gpt-4o-mini"}`,
    ].join("\n");
    await box.files.write({ path: "/work/.env", content: envVars });

    // Step 3: Run the agent
    console.log("\n🧠 Step 3: Running Pydantic AI agent...");
    const run = await box.agent.run({
      prompt: "Read /work/topic.txt and run: python /work/agent.py",
      responseSchema: ResearchResult,
      timeout: 600_000, // 10 min
      maxRetries: 2,
    });

    const result = run.result as ResearchResult;
    console.log(`   ✅ Agent complete. Findings: ${result.findings.length}, Cost: $${run.cost.totalUsd}`);

    // Step 4: Store to Cozy Memory (via file, since we're in Node)
    console.log("\n💾 Step 4: Storing results...");
    const findingsJson = JSON.stringify(result, null, 2);
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
    const fs = await import("fs");
    const findingsPath = `/root/.openclaw/workspace/research/box-${timestamp}.json`;
    fs.writeFileSync(findingsPath, findingsJson);
    console.log(`   Saved to: ${findingsPath}`);

    // Step 5: Format for Telegram
    console.log("\n📱 Step 5: Formatting notification...");
    const telegramMsg = formatTelegram(result, run.cost.totalUsd);
    const telegramPath = `/root/.openclaw/workspace/research/box-${timestamp}.md`;
    fs.writeFileSync(telegramPath, telegramMsg);
    console.log(`   Saved to: ${telegramPath}`);

    return { topic, boxId: box.id, result, cost: run.cost.totalUsd };
  } catch (err: any) {
    console.error(`   ❌ Pipeline failed: ${err.message}`);
    return { topic, boxId: box?.id || "unknown", result: null, cost: 0, error: err.message };
  } finally {
    // Step 6: ALWAYS delete the box
    if (box) {
      console.log(`\n🗑️  Step 6: Deleting Box ${box.id}...`);
      try {
        await box.delete();
        console.log("   ✅ Box deleted. No CPU burn.");
      } catch (e: any) {
        console.error(`   ⚠️  Delete failed: ${e.message}`);
      }
    }
  }
}

function formatTelegram(result: ResearchResult, cost: number): string {
  const lines = [`🔬 *${result.topic}*`, ""];

  if (result.summary) {
    lines.push(`_${result.summary.slice(0, 500)}_`, "");
  }

  if (result.findings.length > 0) {
    lines.push(`*Findings* (${result.findings.length}):`);
    for (const f of result.findings.slice(0, 5)) {
      const check = f.verified ? "✅" : "⚠️";
      lines.push(`  ${check} ${f.finding.slice(0, 120)}`);
    }
    lines.push("");
  }

  if (result.assumptions.length > 0) {
    const confirmed = result.assumptions.filter(a => a.verdict === "CONFIRMED").length;
    const denied = result.assumptions.filter(a => a.verdict === "DENIED").length;
    const partial = result.assumptions.filter(a => a.verdict === "PARTIAL").length;
    lines.push(`*Assumptions*: ${confirmed}✅ ${denied}❌ ${partial}⚠️`, "");
  }

  if (result.recommendations.length > 0) {
    lines.push("*Next Steps*:");
    for (const r of result.recommendations.slice(0, 3)) {
      lines.push(`  → ${r}`);
    }
    lines.push("");
  }

  lines.push(`💰 Cost: $${cost.toFixed(4)}`);
  return lines.join("\n");
}

// ── Parallel Execution ─────────────────────────────────────────

async function runParallel(topics: string[]): Promise<void> {
  console.log(`\n🚀 Parallel pipeline: ${topics.length} topics`);
  console.log(`📊 Free tier: 10 concurrent boxes, ~${topics.length * 3}min estimated CPU\n`);

  const results = await Promise.all(topics.map(t => runPipeline(t)));

  console.log("\n" + "═".repeat(60));
  console.log("📊 FINAL RESULTS");
  console.log("═".repeat(60));

  let totalCost = 0;
  let totalFindings = 0;

  for (const r of results) {
    if (r.result) {
      console.log(`\n✅ ${r.topic}`);
      console.log(`   Findings: ${r.result.findings.length} | Assumptions: ${r.result.assumptions.length} | Cost: $${r.cost.toFixed(4)}`);
      totalCost += r.cost;
      totalFindings += r.result.findings.length;
    } else {
      console.log(`\n❌ ${r.topic}: ${r.error}`);
    }
  }

  console.log(`\n💰 Total: $${totalCost.toFixed(4)} | 📝 ${totalFindings} findings | 📦 0 boxes running`);

  // Write combined results
  const combined = results.filter(r => r.result).map(r => ({
    topic: r.topic,
    result: r.result,
    cost: r.cost,
    boxId: r.boxId,
  }));

  const fs = await import("fs");
  fs.writeFileSync(
    "/root/.openclaw/workspace/research/combined-findings.json",
    JSON.stringify(combined, null, 2)
  );
  console.log("📝 Combined results saved.");
}

// ── CLI ─────────────────────────────────────────────────────────

const args = process.argv.slice(2);

if (args.length === 0) {
  console.log("Usage:");
  console.log("  npx tsx pipeline.ts 'research topic'");
  console.log("  npx tsx pipeline.ts --parallel 'topic 1' 'topic 2'");
  process.exit(1);
}

if (args[0] === "--parallel") {
  runParallel(args.slice(1));
} else {
  runPipeline(args.join(" ")).then(r => {
    if (!r.result) process.exit(1);
  });
}
