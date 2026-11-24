import { chromium } from "@playwright/test";
const b = await chromium.launch();
const c = await b.newContext({ viewport: { width: 1440, height: 810 }, recordVideo: { dir: "/tmp/claude-0/-home-user-superplanner/55e48de5-ecbb-5aa3-99fb-117d7229c1a7/scratchpad/vt", size: { width: 1920, height: 1080 } } });
const p = await c.newPage();
await p.setContent("<div style='font:20px sans-serif;width:1440px;height:810px;background:linear-gradient(red,blue)'>hello corner</div>");
await p.waitForTimeout(1500);
const v = p.video(); await c.close(); console.log(await v.path()); await b.close();
