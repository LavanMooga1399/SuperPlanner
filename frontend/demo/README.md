# Demo video recorder

`record-demo.mjs` records a captioned walkthrough of the real app on the fictional **meddev** sample
(`backend/superplanner/mfg/samples/meddev*.py`: a single-use medical-device plant, all names fictional).

```bash
backend/scripts/pg_dev_cluster.sh start          # PostgreSQL dev cluster on 127.0.0.1:54329
cd frontend
node demo/record-demo.mjs                        # writes docs/demo/superplanner-demo.{webm,mp4} + scenes.json
node demo/record-demo.mjs --only 3,4 --out /tmp/demo   # just some scenes, elsewhere
```

What it does:

1. Starts the API on a **fresh database** (`scripts/run_e2e_api.sh`, `APP_ENV=development`, `ASSISTANT_AI_DEMO=true`,
   single-user mode) on port 8010 and the Vite dev server on 5183 (`DEMO_API_PORT` / `DEMO_WEB_PORT`), like
   `e2e/playwright.config.ts` does; the database is dropped at the end.
2. Loads `meddev`, runs MRP and publishes a schedule (the dashboard reads them), all through the API.
3. Plays the scenes in one recorded browser context (viewport 1440x810), with a caption bar and title / end cards
   injected into the page (`lib.mjs`, app design tokens). A soft dot shows the pointer, which moves slowly.
4. Converts the `.webm` to H.264 `.mp4` scaled to 1920x1080 (`--out-size`) when `ffmpeg` with `libx264` is on PATH
   (Playwright's bundled ffmpeg cannot do this); otherwise the `.webm` is kept.

Options: `--out DIR`, `--only a,b` (scene names or their number prefix), `--pace 1.3` (longer holds),
`--width/--height` (viewport), `--keep-servers`. Set `PLAYWRIGHT_BROWSERS_PATH` if the installed Chromium build differs
from the Playwright version. A failing scene leaves `failed-<scene>.png` in the output folder.

Adding a scene: write `async function sceneX(page)` (navigate with `go`, narrate with `caption`, move with `glide`,
wait with `hold`) and add it to `SCENES` in order. Keep captions factual, one short sentence, sentence case, no
claims of regulatory compliance or validation.

Record from a clean checkout (for example a `git worktree` of a commit) when other work is in progress in the tree:
the dev server serves whatever is on disk.
