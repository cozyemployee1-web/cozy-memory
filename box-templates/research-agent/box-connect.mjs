import { Box } from '@upstash/box';
import { z } from 'zod';

process.env.UPSTASH_BOX_API_KEY = process.env.UPSTASH_BOX_API_KEY;

async function main() {
  const box = await Box.getByName('choice-robin-05555');
  console.log(`Connected: ${box.id}`);

  // Check status
  const status = await box.getStatus();
  console.log(`Status: ${status.status}`);

  // Check what's on the box
  const ls = await box.exec.command('ls -la /work/ 2>/dev/null; echo "---"; python3 --version 2>&1; echo "---"; pip list 2>/dev/null | grep -iE "pydantic|openai|httpx|logfire|vllm|llama"');
  console.log(`Environment:\n${ls.stdout}`);

  // Try running a simple agent task
  console.log('\n--- Testing agent ---');
  try {
    const result = await box.agent.run({
      prompt: 'Say hello and tell me what model you are running. Be brief.',
      timeout: 30000,
    });
    console.log(`Agent response: ${JSON.stringify(result.result, null, 2)}`);
    console.log(`Cost: ${JSON.stringify(result.cost)}`);
  } catch(e) {
    console.log(`Agent error: ${e.message}`);
  }
}

main().catch(e => console.error('Error:', e.message));
