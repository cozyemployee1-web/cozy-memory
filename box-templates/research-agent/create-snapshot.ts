import { Box } from '@upstash/box';

async function main() {
  console.log('📦 Creating fresh base box...');
  const box = await Box.create({ runtime: 'python', timeout: 300_000 });
  console.log('✅ Box created:', box.id);

  // Install Python + deps
  console.log('\n📥 Installing Python and dependencies...');
  
  const installCmd = `pip install --quiet pydantic-ai-slim[openai] openai httpx logfire-api 2>&1 | tail -5 && echo "DONE"`;
  
  const run = await box.exec.command(installCmd);
  console.log('Install result:', run.result);
  
  if (!run.result.includes('DONE')) {
    console.log('❌ Install failed');
    await box.delete();
    return;
  }

  // Create snapshot
  console.log('\n📸 Creating snapshot...');
  const snapshot = await box.snapshot({ name: 'pydantic-ai-base-v2' });
  console.log('✅ Snapshot created:', snapshot.id);
  
  // Save snapshot ID
  const fs = await import('fs');
  fs.writeFileSync('/root/.openclaw/workspace/cozy-memory/box-templates/research-agent/snapshot-id.txt', snapshot.id);
  console.log('Saved snapshot ID to snapshot-id.txt');
  
  await box.delete();
  console.log('✅ Box deleted. Done!');
}

main().catch(e => {
  console.error('❌ Fatal:', e.message);
  process.exit(1);
});
