import { test } from "@playwright/test";
import { mfgJson } from "./mfg-helpers";
import { setupM6 } from "./m6-helpers";
test("probe", async ({ request }) => {
  test.setTimeout(300_000);
  const d = await setupM6(request);
  const ot = await mfgJson<unknown>(request, `/aps/runs/${d.publishedRunId}/overtime`);
  console.log("OT", JSON.stringify(ot).slice(0, 800));
  const run = await mfgJson<{ summary: unknown; policy: string }>(request, `/aps/runs/${d.publishedRunId}`);
  console.log("RUN", run.policy, JSON.stringify(run.summary).slice(0, 600));
  const ap = await mfgJson<unknown>(request, `/approvals`);
  console.log("APPR", JSON.stringify(ap).slice(0, 600));
});
