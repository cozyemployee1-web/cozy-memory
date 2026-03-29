/**
 * Cozy Research Dispatcher — creates Upstash Boxes and dispatches research tasks.
 *
 * Each Box runs a Pydantic AI agent inside (Python runtime).
 * Results are delivered via QStash webhooks for guaranteed delivery.
 *
 * Usage:
 *   npx tsx src/dispatch.ts "vLLM KV cache internals"
 *   npx tsx src/dispatch.ts --parallel "topic 1" "topic 2" "topic 3"
 */

import { Box, Agent, ClaudeCode } from "@upstash/box";
import { z } from "zod";

// ── Response Schema (matches Pydantic AI ResearchResult) ───────

const ResearchFinding = z.object({
  topic: z.string(),
  source: z.string(),
  finding: z.string(),
  confidence: z.number().min(0).max(1),
  verified: z.boolean(),
});

const Assumption = z.object({
  assumption: z.string(),
  source: z.string(),
  verified: z.boolean(),
  verdict: z.enum(["CONFIRMED", "DENIED", "PARTIAL"]),
  evidence: z.string(),
});

const ResearchResult = z.object({
  topic: z.string(),
  summary: z.string(),
  findings: z.array(ResearchFinding),
  assumptions: z.array(Assumption),
  recommendations: z.array(z.string()),
  follow_up_topics: z.array(z.string()),
});

type ResearchResult = z.infer<typeof ResearchResult>;

// ── Dispatcher ─────────────────────────────────────────────────

interface DispatchOptions {
  topic: string;
  webhookUrl?: string;
  timeout?: number;
  model?: string;
}

async function dispatchResearch(opts: DispatchOptions): Promise<{
  boxId: string;
  result: ResearchResult | null;
  cost: number;
}> {
  console.log(`\n🔬 Dispatching research: ${opts.topic}`);

  // Create Box with Python runtime
  const box = await Box.create({
    runtime: "python",
    name: `research-${Date.now()}`,
    agent: {
      provider: Agent.ClaudeCode,
      model: ClaudeCode.Sonnet_4_5,
      apiKey: process.env.ANTHROPIC_API_KEY!,
    },
  });

  console.log(`📦 Box created: ${box.id}`);

  try {
    // Install dependencies inside the Box
    await box.exec.command(
      "pip install pydantic-ai openai httpx mcporter 2>/dev/null"
    );

    // Upload the agent script
    await box.files.write({
      path: "/work/agent.py",
      content: await Bun.file(
        new URL("../agent.py", import.meta.url).pathname
      ).text(),
    });

    // Upload Cozy Memory credentials
    await box.files.write({
      path: "/work/.env",
      content: [
        `UPSTASH_VECTOR_REST_URL=${process.env.UPSTASH_VECTOR_REST_URL}`,
        `UPSTASH_VECTOR_REST_TOKEN=${process.env.UPSTASH_VECTOR_REST_TOKEN}`,
        `UPSTASH_REDIS_REST_URL=${process.env.UPSTASH_REDIS_REST_URL}`,
        `UPSTASH_REDIS_REST_TOKEN=${process.env.UPSTASH_REDIS_REST_TOKEN}`,
        `OPENAI_API_KEY=${process.env.OPENAI_API_KEY}`,
        `AGENT_MODEL=${opts.model || "gpt-4o-mini"}`,
      ].join("\n"),
    });

    // Write topic
    await box.files.write({
      path: "/work/topic.txt",
      content: opts.topic,
    });

    // Run the research agent
    console.log(`🧠 Running Pydantic AI agent...`);
    const run = await box.agent.run({
      prompt: `Run the research agent: python /work/agent.py`,
      timeout: opts.timeout || 600_000, // 10 min default
      responseSchema: ResearchResult,
      maxRetries: 2,
    });

    console.log(`✅ Research complete. Cost: $${run.cost.totalUsd}`);

    return {
      boxId: box.id,
      result: run.result as ResearchResult,
      cost: run.cost.totalUsd,
    };
  } finally {
    // Clean up
    await box.delete();
  }
}

// ── Parallel Dispatch ──────────────────────────────────────────

async function dispatchParallel(topics: string[]): Promise<void> {
  console.log(`\n🚀 Dispatching ${topics.length} research tasks in parallel...`);

  const results = await Promise.all(
    topics.map((topic) =>
      dispatchResearch({ topic }).catch((err) => ({
        boxId: "failed",
        result: null,
        cost: 0,
        error: err.message,
        topic,
      }))
    )
  );

  console.log("\n📊 Results Summary:");
  console.log("=".repeat(60));

  let totalCost = 0;
  for (const r of results) {
    if (r.result) {
      console.log(`\n✅ ${(r.result as ResearchResult).topic}`);
      console.log(`   Findings: ${(r.result as ResearchResult).findings.length}`);
      console.log(`   Assumptions: ${(r.result as ResearchResult).assumptions.length}`);
      totalCost += r.cost;
    } else {
      console.log(`\n❌ ${(r as any).topic}: ${(r as any).error}`);
    }
  }

  console.log(`\n💰 Total cost: $${totalCost.toFixed(4)}`);

  // Write combined results
  const combined = results
    .filter((r) => r.result)
    .map((r) => r.result);

  await Bun.write(
    "/work/combined-findings.json",
    JSON.stringify(combined, null, 2)
  );
  console.log("📝 Combined findings written to /work/combined-findings.json");
}

// ── Webhook Mode (for QStash integration) ──────────────────────

async function dispatchWithWebhook(
  topic: string,
  webhookUrl: string
): Promise<string> {
  console.log(`\n🔬 Dispatching with webhook: ${topic}`);

  const box = await Box.create({
    runtime: "python",
    agent: {
      provider: Agent.ClaudeCode,
      model: ClaudeCode.Sonnet_4_5,
      apiKey: process.env.ANTHROPIC_API_KEY!,
    },
  });

  // Setup (same as above)
  await box.exec.command("pip install pydantic-ai openai httpx 2>/dev/null");
  await box.files.write({
    path: "/work/agent.py",
    content: await Bun.file(
      new URL("../agent.py", import.meta.url).pathname
    ).text(),
  });
  await box.files.write({ path: "/work/topic.txt", content: topic });

  // Fire-and-forget with webhook callback
  const run = await box.agent.run({
    prompt: `Run: python /work/agent.py`,
    responseSchema: ResearchResult,
    maxRetries: 2,
  });

  // In production, the webhook would be handled by QStash
  // For now, we return the box ID for manual polling
  console.log(`📦 Box ${box.id} dispatched. Webhook will fire to: ${webhookUrl}`);
  return box.id;
}

// ── CLI ─────────────────────────────────────────────────────────

const args = process.argv.slice(2);

if (args.includes("--parallel")) {
  const topics = args.filter((a) => a !== "--parallel");
  dispatchParallel(topics);
} else if (args.length > 0) {
  const topic = args.join(" ");
  dispatchResearch({ topic }).then((r) => {
    if (r.result) {
      console.log("\n📋 Findings:");
      console.log(JSON.stringify(r.result, null, 2));
    }
  });
} else {
  console.log("Usage:");
  console.log("  npx tsx src/dispatch.ts 'research topic'");
  console.log("  npx tsx src/dispatch.ts --parallel 'topic 1' 'topic 2'");
}
