import { Box } from '@upstash/box';

const SNAPSHOT_ID = 'f517dfbd-31cc-4d0d-81ab-e640f73306e4';

async function main() {
  console.log('Creating box from snapshot...');
  try {
    const box = await Box.fromSnapshot(SNAPSHOT_ID, { timeout: 120_000 } as any);
    console.log('✅ Box created:', box.id);
    
    // Quick test
    const run = await box.exec.command('echo "hello from box"');
    console.log('Exec result:', run.result);
    
    await box.delete();
    console.log('✅ Box deleted');
  } catch(e: any) {
    console.log('❌ Failed:', e.message);
    console.log('Status code:', e.statusCode);
    
    // Clean up if box was partially created
    const boxes = await Box.list();
    for (const b of boxes) {
      if (b.status === 'creating' || b.status === 'idle') {
        try {
          const box = await Box.get(b.id);
          await box.delete();
          console.log('Cleaned up orphan:', b.id);
        } catch {}
      }
    }
  }
}

main();
