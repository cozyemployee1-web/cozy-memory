import { Box } from "@upstash/box";

const API_KEY = "box_6fb6f959eb95508873f14b3d827ffa1ce31c0da9b58f105cdf1d28e030713596";
process.env.UPSTASH_BOX_API_KEY = API_KEY;

async function main() {
  // Connect to existing box
  const box = await Box.getByName("warm-tapir-51346");
  console.log(`Connected to box: ${box.id}`);

  // Check status
  const { status } = await box.getStatus();
  console.log(`Status: ${status}`);

  // Run Python commands
  const ver = await box.exec.command("python3 --version");
  console.log(`Python: ${ver.stdout}`);

  // Install pydantic-ai
  console.log("\nInstalling pydantic-ai...");
  const install = await box.exec.command("pip install pydantic-ai openai httpx 2>&1 | tail -3");
  console.log(install.stdout);

  // Write a test script
  await box.files.write({
    path: "/workspace/home/test_agent.py",
    content: `import sys
print(f"Hello from Box! Python {sys.version}")
print("Pydantic AI agent ready to go!")
`,
  });

  // Run it
  const result = await box.exec.command("python3 /workspace/home/test_agent.py");
  console.log(`\nScript output:\n${result.stdout}`);

  // Check what's installed
  const pip = await box.exec.command("pip list 2>/dev/null | grep -i pydantic");
  console.log(`Pydantic packages: ${pip.stdout}`);

  console.log("\n✅ Box is ready for Pydantic AI agents!");
}

main().catch(console.error);
