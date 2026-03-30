import { Box } from "@upstash/box";

async function main() {
  console.log("=== TEST 1: Get box status ===");
  const box = await Box.get("choice-robin-05555");
  const status = await box.getStatus();
  console.log("Status:", JSON.stringify(status));
  console.log("Network policy:", JSON.stringify(box.networkPolicy));
  console.log("Model config:", JSON.stringify(box.modelConfig));

  console.log("\n=== TEST 2: Python version + pydantic packages ===");
  const r1 = await box.exec.command("python3 --version 2>&1 && pip list 2>/dev/null | grep -iE 'pydantic|upstash|openai|monty|httpx' || echo 'no matches'");
  console.log(r1.result);

  console.log("\n=== TEST 3: All installed packages ===");
  const r2 = await box.exec.command("pip list 2>/dev/null");
  console.log(r2.result);

  console.log("\n=== TEST 4: Schedules ===");
  const schedules = await box.schedule.list();
  console.log("Schedules:", JSON.stringify(schedules, null, 2));

  console.log("\n=== TEST 5: Workspace layout ===");
  const r3 = await box.exec.command("ls -la /workspace/ && df -h /workspace 2>/dev/null | tail -1");
  console.log(r3.result);

  console.log("\n=== TEST 6: Test pydantic-ai import ===");
  const r4 = await box.exec.command("python3 -c \"import pydantic_ai; print('pydantic-ai version:', pydantic_ai.__version__)\" 2>&1 || echo 'pydantic-ai NOT installed'");
  console.log(r4.result);

  console.log("\n=== TEST 7: Test pydantic-monty import ===");
  const r5 = await box.exec.command("python3 -c \"import pydantic_monty; print('monty OK')\" 2>&1 || echo 'monty NOT installed'");
  console.log(r5.result);

  console.log("\n=== TEST 8: Test OpenRouter via pydantic-ai ===");
  const r6 = await box.exec.command("python3 -c \"\nfrom pydantic_ai import Agent\nagent = Agent('openrouter:stepfun/step-3.5-flash:free', instructions='Reply in one word.')\nresult = agent.run_sync('Say hello')\nprint('OpenRouter result:', result.output)\n\" 2>&1");
  console.log(r6.result);
}

main().catch(console.error);
