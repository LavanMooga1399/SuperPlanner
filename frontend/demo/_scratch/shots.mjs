import { chromium } from "@playwright/test";
const out = process.env.OUT ?? "/tmp/claude-0/-home-user-superplanner/55e48de5-ecbb-5aa3-99fb-117d7229c1a7/scratchpad/shots";
import * as fs from "node:fs"; fs.mkdirSync(out, { recursive: true });
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 810 } });
for (const [name, url] of process.argv.slice(2).map((a) => a.split("="))) {
  await p.goto("http://127.0.0.1:5183" + url);
  await p.waitForLoadState("networkidle").catch(() => {});
  await p.waitForTimeout(2500);
  await p.screenshot({ path: `${out}/${name}.png` });
  console.log(name, p.url());
}
await b.close();
