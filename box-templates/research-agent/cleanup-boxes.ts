import { Box } from '@upstash/box';

async function main() {
  // List and delete all boxes
  const boxes = await Box.list();
  console.log('Active boxes:', boxes.length);
  
  for (const b of boxes) {
    console.log(`Deleting ${b.id} (${b.status})...`);
    try {
      const box = await Box.get(b.id);
      await box.delete();
      console.log(`  ✅ Deleted`);
    } catch(e: any) {
      console.log(`  ❌ ${e.message}`);
    }
  }
  
  console.log('\nDone.');
}

main();
