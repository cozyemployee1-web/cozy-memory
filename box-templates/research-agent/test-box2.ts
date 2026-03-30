import { Box, Agent, OpenCodeModel, OpenRouterModel } from "@upstash/box";

async function main() {
  const box = await Box.get("choice-robin-05555");

  console.log("=== TEST 9: Native box agent run with openrouter model ===");
  const r1 = await box.agent.run({
    prompt: "Reply with exactly: AGENT_OK"
  });
  console.log("Agent status:", r1.status);
  console.log("Agent result:", r1.result);

  console.log("\n=== TEST 10: Install pydantic-monty ===");
  const r2 = await box.exec.command("pip install pydantic-monty 2>&1 | tail -5");
  console.log(r2.result);

  console.log("\n=== TEST 11: Test monty after install ===");
  const r3 = await box.exec.command("python3 -c \"import pydantic_monty; print('monty version:', pydantic_monty.__version__ if hasattr(pydantic_monty, '__version__') else 'installed OK')\" 2>&1");
  console.log(r3.result);

  console.log("\n=== TEST 12: Run monty code execution ===");
  const r4 = await box.exec.command(`python3 -c "
import pydantic_monty
m = pydantic_monty.Monty('x * 2', inputs=['x'])
result = m.run(inputs={'x': 21})
print('Monty result:', result)
" 2>&1`);
  console.log(r4.result);

  console.log("\n=== TEST 13: Upstash SDKs available? ===");
  const r5 = await box.exec.command("pip install upstash-redis upstash-vector qstash 2>&1 | tail -5");
  console.log(r5.result);

  console.log("\n=== TEST 14: Test schedule creation ===");
  const sched = await box.schedule.exec({
    cron: "59 23 31 12 0", // near-never: Dec 31 11:59pm Sunday
    command: ["bash", "-c", "echo test-schedule-ok >> /workspace/home/sched.log"],
  });
  console.log("Schedule created:", JSON.stringify(sched));

  console.log("\n=== TEST 15: List schedules after creation ===");
  const schedules = await box.schedule.list();
  console.log("Schedules:", JSON.stringify(schedules, null, 2));

  // cleanup test schedule
  await box.schedule.delete(sched.id);
  console.log("Schedule deleted:", sched.id);
}

main().catch(console.error);
