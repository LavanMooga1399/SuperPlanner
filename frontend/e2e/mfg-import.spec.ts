/**
 * WP-D (M1-DESIGN 15.4 mfg-import, 11.5): the import wizard end to end with an xlsx file written by an ERP-like
 * export (own headers, two sheets): upload -> suggested mapping -> preview with row errors (commit disabled,
 * errors CSV) -> "Fix the file and upload again" keeps the mapping -> commit -> re-import is a no-op. Also the
 * export download and an export -> wizard import round trip of a whole sample.
 */
import { test, expect, type Page } from "@playwright/test";
import * as fs from "node:fs";
import { expectClean, watch } from "./helpers";
import { findItem, gotoMfg, loadSample, mfgJson, resetMfg, uploadImportFile } from "./mfg-helpers";

// ---------------------------------------------------------------- minimal xlsx writer (stored zip, no packages)
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(b: Buffer): number {
  let c = 0xffffffff;
  for (const x of b) c = CRC_TABLE[(c ^ x) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function zip(files: Record<string, string>): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const [name, text] of Object.entries(files)) {
    const data = Buffer.from(text, "utf-8");
    const nameB = Buffer.from(name, "utf-8");
    const crc = crc32(data);
    const lh = Buffer.alloc(30);
    lh.writeUInt32LE(0x04034b50, 0);
    lh.writeUInt16LE(20, 4);
    lh.writeUInt16LE(0, 6);
    lh.writeUInt16LE(0, 8);
    lh.writeUInt32LE(0x00210000, 10); // 1980-01-01
    lh.writeUInt32LE(crc, 14);
    lh.writeUInt32LE(data.length, 18);
    lh.writeUInt32LE(data.length, 22);
    lh.writeUInt16LE(nameB.length, 26);
    lh.writeUInt16LE(0, 28);
    locals.push(lh, nameB, data);
    const ch = Buffer.alloc(46);
    ch.writeUInt32LE(0x02014b50, 0);
    ch.writeUInt16LE(20, 4);
    ch.writeUInt16LE(20, 6);
    ch.writeUInt32LE(0x00210000, 12);
    ch.writeUInt32LE(crc, 16);
    ch.writeUInt32LE(data.length, 20);
    ch.writeUInt32LE(data.length, 24);
    ch.writeUInt16LE(nameB.length, 28);
    ch.writeUInt32LE(offset, 42);
    centrals.push(ch, nameB);
    offset += 30 + nameB.length + data.length;
  }
  const cd = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(Object.keys(files).length, 8);
  end.writeUInt16LE(Object.keys(files).length, 10);
  end.writeUInt32LE(cd.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, cd, end]);
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
function col(i: number): string {
  return String.fromCharCode(65 + i);
}

/** Workbook with one sheet per entry; numbers become numeric cells, strings inline strings. */
function xlsx(sheets: Record<string, (string | number | null)[][]>): Buffer {
  const names = Object.keys(sheets);
  const files: Record<string, string> = {
    "[Content_Types].xml":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      names.map((_, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("") +
      "</Types>",
    "_rels/.rels":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
    "xl/workbook.xml":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
      names.map((n, i) => `<sheet name="${esc(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("") +
      "</sheets></workbook>",
    "xl/_rels/workbook.xml.rels":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      names.map((_, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join("") +
      "</Relationships>",
  };
  names.forEach((n, si) => {
    const rows = sheets[n]
      .map((r, ri) => {
        const cells = r
          .map((v, ci) => {
            const ref = `${col(ci)}${ri + 1}`;
            if (v === null) return "";
            if (typeof v === "number") return `<c r="${ref}"><v>${v}</v></c>`;
            return `<c r="${ref}" t="inlineStr"><is><t>${esc(v)}</t></is></c>`;
          })
          .join("");
        return `<row r="${ri + 1}">${cells}</row>`;
      })
      .join("");
    files[`xl/worksheets/sheet${si + 1}.xml`] =
      `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${rows}</sheetData></worksheet>`;
  });
  return zip(files);
}

function erpWorkbook(withErrors: boolean): Buffer {
  const items: (string | number | null)[][] = [
    ["Part No", "Description", "Make/Buy", "UoM", "Lead time"],
    ["E2E-ASSY", "E2E assembly", "make", "Nos", null],
    ["E2E-PCB", "E2E bare board", "B", "EA", 21],
    ["E2E-RES", "E2E resistor 10k", "purchased", "PCS", 28],
    ["E2E-WIRE", "E2E wire, red", "buy", "MTR", 14],
  ];
  const bom: (string | number | null)[][] = [
    ["Parent", "Find No", "Component", "Qty", "UoM", "Ref Des"],
    ["E2E-ASSY", "10", "E2E-PCB", 1, "EA", ""],
    ["E2E-ASSY", "20", "E2E-RES", 4, "EA", "R1-R4"],
    ["E2E-ASSY", "30", withErrors ? "E2E-NOPE" : "E2E-WIRE", 250, "MM", ""],
    ["E2E-ASSY", "40", "E2E-RES", withErrors ? "abc" : 2, "EA", withErrors ? "" : "R5-R6"],
  ];
  return xlsx({ Items: items, BOM: bom });
}

async function previewCounts(page: Page): Promise<Record<string, string>> {
  const rows = page.getByTestId("import-count-row");
  const out: Record<string, string> = {};
  for (const r of await rows.all()) out[(await r.getAttribute("data-sheet")) ?? ""] = (await r.innerText()).replace(/\s+/g, " ");
  return out;
}

test.beforeEach(async ({ request }) => {
  await resetMfg(request);
});

test("xlsx import wizard: mapping suggestions, row errors, fix and re-upload, commit, re-import is a no-op", async ({ page, request }) => {
  const problems = watch(page);
  // 1. upload the file with two bad rows
  await uploadImportFile(page, "erp-bom.xlsx", erpWorkbook(true));
  await expect(page).toHaveURL(/\/mfg\/import\/imp_[0-9a-f]{32}\?step=map$/);
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "map");
  const cards = page.getByTestId("import-sheet-card");
  await expect(cards).toHaveCount(2);
  await expect(page.locator('[data-testid="import-sheet-card"][data-sheet="Items"]').getByTestId("import-sheet-target")).toHaveValue("items");
  await expect(page.locator('[data-testid="import-sheet-card"][data-sheet="BOM"]').getByTestId("import-sheet-target")).toHaveValue("bom_lines");
  const pn = page.locator('[data-testid="import-sheet-card"][data-sheet="Items"] [data-testid="import-column-row"][data-header="Part No"]').getByTestId("import-column-field");
  await expect(pn).toHaveValue("part_number");
  // reloading the browser at the mapping step restores it
  await page.reload();
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "map");
  await expect(cards).toHaveCount(2);

  // 2. preview: two row errors, commit impossible, errors downloadable
  await page.getByTestId("import-preview-submit").click();
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "preview");
  const preview = page.getByTestId("import-preview");
  await expect(preview).toHaveAttribute("data-ok", "false");
  await expect(preview).toHaveAttribute("data-error-count", "2");
  await expect(page.getByTestId("import-row-error")).toHaveCount(2);
  const codes = await page.getByTestId("import-row-error").evaluateAll((rs) => rs.map((r) => `${r.getAttribute("data-sheet")}:${r.getAttribute("data-row")}:${r.getAttribute("data-code")}`));
  expect(codes.sort()).toEqual(["BOM:4:IMP_UNKNOWN_REFERENCE", "BOM:5:IMP_BAD_NUMBER"]);
  await expect(page.getByTestId("import-commit")).toBeDisabled();
  const dl = page.waitForEvent("download");
  await page.getByTestId("import-errors-csv").click();
  const csvPath = await (await dl).path();
  const csv = fs.readFileSync(csvPath!, "utf-8");
  expect(csv.split(/\r?\n/)[0]).toBe("sheet,row,column,code,message");
  expect(csv).toContain("IMP_UNKNOWN_REFERENCE");
  expect(csv).toContain("E2E-NOPE");
  await page.reload();
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "preview");
  await expect(page.getByTestId("import-commit")).toBeDisabled();
  const firstId = page.url().match(/import\/(imp_[0-9a-f]{32})/)![1];
  expect((await mfgJson<{ items: unknown[]; total: number }>(request, "/items?q=E2E-")).total).toBe(0);

  // 3. "Fix the file and upload again": the corrected file keeps the mapping and goes straight to the preview
  await page.getByTestId("import-reupload").click();
  await expect(page).toHaveURL(new RegExp(`/mfg/import\\?reuse=${firstId}$`));
  await page.getByTestId("import-file-input").setInputFiles({ name: "erp-bom-fixed.xlsx", mimeType: "application/octet-stream", buffer: erpWorkbook(false) });
  await page.getByTestId("import-upload-submit").click();
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "preview");
  await expect(page.getByTestId("import-preview")).toHaveAttribute("data-ok", "true");
  await expect(page.getByTestId("import-row-error")).toHaveCount(0);
  const counts = await previewCounts(page);
  expect(Object.keys(counts).sort()).toEqual(["bom_lines", "boms", "items"].sort());
  await expect(page.getByTestId("import-commit")).toBeEnabled();
  await page.getByTestId("import-commit").click();
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "done");
  await expect(page.getByTestId("import-result")).toBeVisible();
  await expect(page.getByTestId("import-result-counts")).toContainText("4");

  // the data arrived as mapped (aliases: Nos/PCS -> EA, MTR -> M, B/purchased -> buy; wire 250 MM)
  const assy = await findItem(request, "E2E-ASSY");
  expect(assy.make_buy).toBe("make");
  const wire = await findItem(request, "E2E-WIRE");
  expect((await mfgJson<{ uom: string; lead_time_days: number }>(request, `/items/${wire.id}`))).toMatchObject({ uom: "M", lead_time_days: 14 });
  const boms = await mfgJson<{ items: { id: string; status: string; line_count: number }[] }>(request, `/items/${assy.id}/boms`);
  expect(boms.items).toHaveLength(1);
  expect(boms.items[0]).toMatchObject({ status: "draft", line_count: 4 });
  const bom = await mfgJson<{ lines: { find_number: string; qty_per: number; uom: string; ref_designators: string }[] }>(request, `/boms/${boms.items[0].id}`);
  expect(bom.lines.map((l) => `${l.find_number} ${l.qty_per} ${l.uom} ${l.ref_designators}`)).toEqual(["10 1 EA ", "20 4 EA R1-R4", "30 250 MM ", "40 2 EA R5-R6"]);
  const dv = (await mfgJson<{ data_version: number }>(request, "/summary")).data_version;

  // 4. re-import of the same file: everything unchanged, nothing written
  await uploadImportFile(page, "erp-bom-fixed.xlsx", erpWorkbook(false));
  await page.getByTestId("import-preview-submit").click();
  await expect(page.getByTestId("import-preview")).toHaveAttribute("data-ok", "true");
  const again = await previewCounts(page);
  for (const [sheet, text] of Object.entries(again)) {
    const nums = text.match(/\d+/g)!.map(Number);
    expect(nums.slice(0, 3), `${sheet}: ${text}`).toEqual([0, 0, nums[2]]); // create, update = 0; unchanged = n
    expect(nums[2], `${sheet}: ${text}`).toBeGreaterThan(0);
  }
  await page.getByTestId("import-commit").click();
  await expect(page.getByTestId("import-result")).toBeVisible();
  expect((await mfgJson<{ data_version: number }>(request, "/summary")).data_version).toBe(dv);
  expect((await mfgJson<{ items: { id: string }[] }>(request, `/items/${assy.id}/boms`)).items).toHaveLength(1);
  expectClean(problems);
});

test("export downloads (xlsx and zip) and an export -> wizard import round trip of the small sample", async ({ page, request }) => {
  await loadSample(request, "small");
  const before = await mfgJson<{ counts: Record<string, number> }>(request, "/summary");
  const health = await mfgJson<{ fingerprint: string }>(request, "/health");
  const problems = watch(page);
  await gotoMfg(page, "");
  const dl = page.waitForEvent("download");
  await page.getByTestId("mfg-export").click();
  const file = await dl;
  expect(file.suggestedFilename()).toMatch(/^superplanner-mfg-[A-Za-z0-9_-]{1,40}-\d{8}\.xlsx$/);
  const xbytes = fs.readFileSync((await file.path())!);
  expect(xbytes.subarray(0, 2).toString()).toBe("PK");
  const dz = page.waitForEvent("download");
  await page.getByTestId("mfg-export-zip").click();
  const zfile = await dz;
  expect(zfile.suggestedFilename()).toMatch(/\.zip$/);
  // template download from the import page
  await gotoMfg(page, "/import");
  const dt = page.waitForEvent("download");
  await page.getByTestId("import-template-xlsx").click();
  expect((await dt).suggestedFilename()).toMatch(/\.xlsx$/);

  // wipe and import the exported workbook through the wizard with the suggested mapping, unedited
  await resetMfg(request);
  await uploadImportFile(page, file.suggestedFilename(), xbytes);
  await expect(page.getByTestId("import-stepper")).toHaveAttribute("data-step", "map");
  await page.getByTestId("import-preview-submit").click();
  await expect(page.getByTestId("import-preview")).toHaveAttribute("data-ok", "true");
  await page.getByTestId("import-commit").click();
  await expect(page.getByTestId("import-result")).toBeVisible();
  const after = await mfgJson<{ counts: Record<string, number> }>(request, "/summary");
  expect(after.counts).toEqual(before.counts);
  const h2 = await mfgJson<{ fingerprint: string; ok: boolean }>(request, "/health");
  expect(h2.ok).toBe(true);
  expect(h2.fingerprint).toBe(health.fingerprint);
  await page.getByTestId("import-done-health").click();
  await expect(page.getByTestId("health-status")).toHaveAttribute("data-ok", "true");
  expectClean(problems);
});

test("client-side size check: a file over the server limit is refused before upload", async ({ page }) => {
  const problems = watch(page);
  await gotoMfg(page, "/import");
  const meta = await page.evaluate(async () => (await (await fetch("/api/v1/mfg/meta")).json()) as { limits: { max_body_bytes: number } });
  const big = Buffer.alloc(meta.limits.max_body_bytes + 10, 0x41);
  await page.getByTestId("import-file-input").setInputFiles({ name: "big.csv", mimeType: "text/csv", buffer: big });
  await expect(page.getByTestId("import-too-big")).toBeVisible();
  await expect(page.getByTestId("import-upload-submit")).toBeDisabled();
  expectClean(problems);
});
