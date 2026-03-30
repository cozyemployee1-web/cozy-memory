import { Box } from '@upstash/box';

process.env.UPSTASH_BOX_API_KEY = process.env.UPSTASH_BOX_API_KEY;

async function main() {
  console.log('Listing boxes...');
  const boxes = await Box.list();
  console.log('Active boxes:', boxes.length);
  for (const b of boxes) {
    console.log(`  - ${b.id} (${b.status})`);
  }
}

main().catch(e => console.error('Error:', e.message));
