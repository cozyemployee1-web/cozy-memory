import { Box } from '@upstash/box';

async function main() {
  console.log('Creating fresh box (no snapshot)...');
  try {
    const box = await Box.create({ timeout: 120_000 });
    console.log('✅ Box created:', box.id);
    
    // Quick test
    const run = await box.exec.command('echo "hello from fresh box" && python3 --version');
    console.log('Exec result:', run.result);
    
    await box.delete();
    console.log('✅ Box deleted');
  } catch(e: any) {
    console.log('❌ Failed:', e.message);
    console.log('Status code:', e.statusCode);
  }
}

main();
