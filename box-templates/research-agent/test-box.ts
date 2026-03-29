import { Box } from '@upstash/box';

async function main() {
  try {
    const boxes = await Box.list();
    console.log('Active boxes:', boxes.length);
    for (const b of boxes) {
      console.log(' -', b.id, b.status);
    }
  } catch(e: any) {
    console.log('Error listing:', e.message);
  }
}
main();
