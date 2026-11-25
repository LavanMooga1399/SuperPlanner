// i18n check (UX-STANDARD 8): finds hard-coded user-facing copy in src (JSX text runs with their string/number
// values, user-facing JSX attributes, natural-language string and template literals outside lib/strings, api and
// pwa). `npm run i18n:check` reports the count (0 expected); `--list` prints them; `--apply` keys them.
const ts = require("typescript");
const fs = require("fs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
const SRC = path.join(ROOT, "src");
const APPLY = process.argv.includes("--apply");
const LIST = process.argv.includes("--list");

const cfg = ts.getParsedCommandLineOfConfigFile(path.join(ROOT, "tsconfig.json"), {}, { ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} });
const program = ts.createProgram(cfg.fileNames, cfg.options);
const checker = program.getTypeChecker();

const EXCLUDE_DIRS = ["/lib/strings/", "/api/", "/pwa/", "/e2e/"];
const EXCLUDE_FILES = new Set(["lib/i18n.ts", "mfg/lib/paths.ts", "main.tsx", "boot.tsx", "vite-env.d.ts"]);
function areaOf(rel) {
  if (rel.startsWith("mfg/floor/")) return "floor";
  if (rel.startsWith("mfg/mobile/")) return "mobile";
  if (rel.startsWith("mfg/assistant/")) return "assistant";
  if (rel.startsWith("mfg/")) return "mfg";
  if (rel.startsWith("finance/")) return "finance";
  if (rel.startsWith("auth/") || rel.startsWith("orgs/")) return "account";
  if (rel.startsWith("components/shell/") || rel.startsWith("lib/") || rel === "App.tsx" || rel.startsWith("state/")) return "shell";
  return "studio";
}

const KEYS = new Set(["Enter", "Escape", "Tab", "Backspace", "Delete", "Home", "End", "PageUp", "PageDown", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Shift", "Control", "Alt", "Meta", "Space", "Inter", "Monday", "GET", "POST", "PUT", "DELETE"]);
function isNL(s) {
  const x = s.trim();
  if (x.length < 2) return false;
  if (!/[A-Za-z]{2,}/.test(x)) return false;
  if (/:\/\/|^\/|^#|=>|--|var\(|rgba?\(|^\.|\d(px|em|rem|ms|s)\b|sans-serif|monospace|^[a-z0-9_.:/@-]+$|^[A-Z0-9_]+$|^[a-z]+[A-Z][A-Za-z]*$/.test(x)) return false;
  if (KEYS.has(x)) return false;
  if (/^[A-Z][a-z]+(-[A-Z][a-z]+)+$/.test(x)) return false; // header names
  if (/^[\w-]+\/[\w.+-]+$/.test(x)) return false; // mime types, time zones
  if (/^(sp|mfg|table|views|common|nav|filters|shell|palette|error|guard)\.[\w.]+$/.test(x)) return false; // keys
  if (/[a-zA-Z]{2,}\s+[a-zA-Z(]/.test(x) || /^[A-Z][a-z]+([ .:!?…,)]|$)/.test(x) || /[a-z]{2,}[.:!?…]$/.test(x)) return true;
  return false;
}

const ATTR_UI = new Set(["title", "label", "placeholder", "aria-label", "description", "empty", "confirmLabel", "cancelLabel", "submitLabel", "hint", "alt", "text", "header", "help", "summary", "caption", "subtitle", "noun", "what", "message", "tooltip", "emptyText", "loadingLabel", "unit"]);
const PROP_TECH = new Set(["className", "key", "id", "testId", "to", "href", "path", "icon", "tone", "kind", "type", "status", "code", "variant", "width", "height", "align", "role", "method", "mode", "format", "sortKey", "sortKeyDesc", "field", "value", "tableId", "exportName", "pageKey", "storageKey", "prefKey", "query", "font", "fontFamily", "background", "color", "border", "display", "gridTemplateColumns", "transform", "d", "fill", "stroke", "viewBox", "accept", "inputMode", "autoComplete", "rel", "target", "src", "pattern", "dir", "lang", "ref", "scope", "headers"]);
const CALL_SKIP = /^(t|tr|plural|console\.\w+|require|fetch|request\w*|mfgRequest\w*|mfgRaw|mfgDownload|\w+\.querySelector\w*|document\.\w+|\w*[sS]torage\.\w+|\w+\.addEventListener|\w+\.removeEventListener|matchMedia|window\.\w+|getComputedStyle|setSearchParam|\w+\.(get|set|has|delete|append)|URLSearchParams|RegExp|Intl\.\w+|\w+\.toLocaleString|\w+\.toLocale\w+|CSS\.escape|\w+\.startsWith|\w+\.endsWith|\w+\.includes|\w+\.indexOf|\w+\.split|\w+\.replace\w*|\w+\.match|\w+\.test|savePref|syncPref|loadPref|\w+\.setAttribute|\w+\.getAttribute|\w+\.closest|\w+\.join|new\s+\w+|saveBlob|downloadText|\w+\.toFixed|navigate|useNavigate|\w+\.download|mfgPaths\.\w+|enc|encodeURIComponent|ifMatch|Symbol\.for|classNames|cx|clsx|useLoad|usePaged|createContext|\w+\.locator|\w+\.click)$/;

function calleeText(call, sf) {
  return call.expression.getText(sf).replace(/\s+/g, "");
}

function jsxNormalize(text) {
  const lines = text.split(/\r\n|\n|\r/);
  let last = 0;
  lines.forEach((l, i) => { if (/[^ \t]/.test(l)) last = i; });
  let out = "";
  lines.forEach((line, i) => {
    let s = line.replace(/\t/g, " ");
    if (i !== 0) s = s.replace(/^[ ]+/, "");
    if (i !== lines.length - 1) s = s.replace(/[ ]+$/, "");
    if (s) { if (i !== last) s += " "; out += s; }
  });
  return out;
}

function isTextType(expr) {
  const tp = checker.getTypeAtLocation(expr);
  const ok = (x) => (x.flags & (ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike)) !== 0;
  if (tp.isUnion()) return tp.types.every(ok);
  return ok(tp);
}

function varName(expr, sf, used) {
  let n = "v";
  let e = expr;
  while (ts.isParenthesizedExpression(e) || ts.isNonNullExpression(e)) e = e.expression;
  if (ts.isIdentifier(e)) n = e.text;
  else if (ts.isPropertyAccessExpression(e)) n = e.name.text;
  else if (ts.isCallExpression(e)) {
    const a = e.arguments[0];
    if (a && (ts.isIdentifier(a) || ts.isPropertyAccessExpression(a))) n = ts.isIdentifier(a) ? a.text : a.name.text;
    else if (ts.isPropertyAccessExpression(e.expression)) {
      const inner = e.expression.expression;
      n = ts.isPropertyAccessExpression(inner) ? inner.name.text : ts.isIdentifier(inner) ? inner.text : e.expression.name.text;
    } else if (ts.isIdentifier(e.expression)) n = e.expression.text;
  }
  n = n.replace(/[^A-Za-z0-9]/g, "") || "v";
  if (/^\d/.test(n)) n = "v" + n;
  let k = n, i = 2;
  while (used.has(k)) k = n + i++;
  used.add(k);
  return k;
}

function camel(text) {
  const words = text.replace(/\{[^}]*\}/g, " ").split(/[^A-Za-z0-9]+/).filter(Boolean).slice(0, 5);
  if (!words.length) return "text";
  return words[0].toLowerCase() + words.slice(1).map((w) => w[0].toUpperCase() + w.slice(1).toLowerCase()).join("");
}

// ---------------------------------------------------------------- existing dictionaries
const STR_DIR = path.join(SRC, "lib/strings");
const dicts = {}; // area -> {key: value}
const byVal = {}; // area|file|kind|value -> key
function loadDict(area) {
  if (dicts[area]) return dicts[area];
  const f = path.join(STR_DIR, `${area}.ts`);
  const d = {};
  if (fs.existsSync(f)) for (const m of fs.readFileSync(f, "utf8").matchAll(/^  ("[^"\n]+"): (".*"),$/gm)) d[JSON.parse(m[1])] = JSON.parse(m[2]);
  dicts[area] = d;
  return d;
}
function keyFor(area, fileNs, kind, value) {
  const d = loadDict(area);
  const id = `${area}|${fileNs}|${kind}|${value}`;
  if (byVal[id]) return byVal[id];
  for (const [k, v] of Object.entries(d)) if (v === value && k.startsWith(`${area}.${fileNs}.${kind}.`)) return (byVal[id] = k);
  const base = `${area}.${fileNs}.${kind}.${camel(value)}`;
  let k = base, i = 2;
  while (d[k] !== undefined && d[k] !== value) k = base + i++;
  d[k] = value;
  return (byVal[id] = k);
}

// ---------------------------------------------------------------- scan
let total = 0;
const perArea = {};
const listOut = [];
const touched = [];
for (const sf of program.getSourceFiles()) {
  const abs = sf.fileName;
  if (!abs.startsWith(SRC + "/")) continue;
  const rel = path.relative(SRC, abs);
  if (EXCLUDE_DIRS.some((d) => ("/" + rel).includes(d)) || EXCLUDE_FILES.has(rel) || /\.(test|spec)\.|fixtures?/.test(rel)) continue;
  const area = areaOf(rel);
  const base = path.basename(rel).replace(/\.(tsx?|ts)$/, "");
  const fileNs = base[0].toLowerCase() + base.slice(1);
  const edits = [];
  // local `t` shadowing -> use alias tr
  let shadow = false;
  const findShadow = (n) => {
    if ((ts.isParameter(n) || ts.isVariableDeclaration(n) || ts.isBindingElement(n) || ts.isFunctionDeclaration(n)) && n.name && ts.isIdentifier(n.name) && n.name.text === "t") shadow = true;
    if (ts.isImportSpecifier(n) && n.name.text === "t" && !/lib\/i18n"?$/.test(n.parent.parent.parent.moduleSpecifier.getText(sf).replace(/['"]/g, ""))) shadow = true;
    ts.forEachChild(n, findShadow);
  };
  findShadow(sf);
  const existingImport = sf.statements.find((s) => ts.isImportDeclaration(s) && /lib\/i18n["']$/.test(s.moduleSpecifier.getText(sf)));
  let fn = "t";
  if (existingImport && /\bt as tr\b/.test(existingImport.getText(sf))) fn = "tr";
  if (shadow) fn = "tr";

  const count = (n, what, text) => {
    total++;
    perArea[area] = (perArea[area] || 0) + 1;
    if (LIST) listOut.push(`${rel}:${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1} [${what}] ${text.slice(0, 80)}`);
  };
  const inSkippedCall = (n) => {
    let p = n.parent;
    while (p && (ts.isParenthesizedExpression(p) || ts.isConditionalExpression(p) || ts.isBinaryExpression(p) && (p.operatorToken.kind === ts.SyntaxKind.BarBarToken || p.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken || p.operatorToken.kind === ts.SyntaxKind.PlusToken))) p = p.parent;
    if (p && (ts.isCallExpression(p) || ts.isNewExpression(p)) && p.arguments && p.arguments.includes(n.parent === p ? n : n)) {
      const c = ts.isNewExpression(p) ? "new " + p.expression.getText(sf) : calleeText(p, sf);
      if (/^new\s+Error$/.test(c)) return false;
      return CALL_SKIP.test(c);
    }
    if (p && (ts.isCallExpression(p) || ts.isNewExpression(p))) {
      const c = ts.isNewExpression(p) ? "new " + p.expression.getText(sf) : calleeText(p, sf);
      if (/^new\s+Error$/.test(c)) return false;
      return CALL_SKIP.test(c);
    }
    return false;
  };
  const techAncestor = (n) => {
    let c = n, p = n.parent;
    while (p) {
      if (ts.isJsxAttribute(p)) {
        const name = p.name.getText(sf);
        return !ATTR_UI.has(name);
      }
      if (ts.isPropertyAssignment(p) && p.initializer === c) {
        const k = p.name.getText(sf).replace(/['"]/g, "");
        if (PROP_TECH.has(k) || k === "style") return true;
      }
      if (ts.isCallExpression(p) && c !== p.expression) {
        const ce = calleeText(p, sf);
        if (CALL_SKIP.test(ce)) return true;
      }
      if (ts.isJsxElement(p) || ts.isJsxSelfClosingElement(p) || ts.isSourceFile(p) || ts.isFunctionLike(p) && !ts.isArrowFunction(p)) return false;
      c = p;
      p = p.parent;
    }
    return false;
  };
  const literalContextOk = (n) => {
    const p = n.parent;
    if (!p) return false;
    if (techAncestor(n)) return false;
    if (ts.isImportDeclaration(p) || ts.isExportDeclaration(p) || ts.isExternalModuleReference(p) || ts.isLiteralTypeNode(p) || ts.isImportTypeNode?.(p)) return false;
    if ((ts.isPropertyAssignment(p) || ts.isPropertyDeclaration(p) || ts.isMethodDeclaration(p) || ts.isPropertySignature(p)) && p.name === n) return false;
    if (ts.isElementAccessExpression(p) && p.argumentExpression === n) return false;
    if (ts.isCaseClause(p)) return false;
    if (ts.isBinaryExpression(p) && [ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken, ts.SyntaxKind.InKeyword].includes(p.operatorToken.kind)) return false;
    if (ts.isJsxAttribute(p)) {
      const name = p.name.getText(sf);
      return ATTR_UI.has(name);
    }
    if (ts.isJsxExpression(p) && ts.isJsxAttribute(p.parent)) {
      const name = p.parent.name.getText(sf);
      if (!ATTR_UI.has(name) && PROP_TECH.has(name)) return false;
      if (name.startsWith("data-") || name === "className" || name === "style" || name === "key") return false;
    }
    if (ts.isPropertyAssignment(p) && p.initializer === n) {
      const k = p.name.getText(sf).replace(/['"]/g, "");
      if (PROP_TECH.has(k)) return false;
      // inside style={{...}}
      let q = p.parent && p.parent.parent;
      if (q && ts.isJsxExpression(q) && ts.isJsxAttribute(q.parent) && q.parent.name.getText(sf) === "style") return false;
    }
    if (ts.isTypeReferenceNode(p) || ts.isUnionTypeNode(p)) return false;
    if (inSkippedCall(n)) return false;
    // `as const` tuples of ids / enum-like arrays: let the NL heuristic decide
    return true;
  };
  const insideT = (n) => {
    let c = n, p = n.parent;
    while (p) {
      // the key of t()/tr() and the nouns of plural() stay; values inside t()'s vars object are copy too
      if (ts.isCallExpression(p) && /^(t|tr)$/.test(p.expression.getText(sf)) && p.arguments[0] === c) return true;
      if (ts.isCallExpression(p) && p.expression.getText(sf) === "plural" && c !== p.arguments[0]) return true;
      if (ts.isJsxElement(p) && /^(code|pre|kbd|style|script)$/.test(p.openingElement.tagName.getText(sf))) return true;
      c = p;
      p = p.parent;
    }
    return false;
  };

  const visit = (n) => {
    // JSX children runs
    if (ts.isJsxElement(n) || ts.isJsxFragment(n)) {
      const tag = ts.isJsxElement(n) ? n.openingElement.tagName.getText(sf) : "";
      if (!/^(code|pre|kbd|style|script)$/.test(tag) && !insideT(n)) {
        const kids = n.children;
        let i = 0;
        while (i < kids.length) {
          const isTextish = (c) => ts.isJsxText(c) || (ts.isJsxExpression(c) && c.expression && !ts.isJsxElement(c.expression) && !ts.isJsxSelfClosingElement(c.expression) && !ts.isJsxFragment(c.expression) && isTextType(c.expression));
          if (!isTextish(kids[i])) { i++; continue; }
          let j = i;
          while (j + 1 < kids.length && isTextish(kids[j + 1])) j++;
          const run = kids.slice(i, j + 1);
          // drop leading/trailing pure expressions (keep them outside the sentence)
          let a = 0, b = run.length - 1;
          while (a <= b && !ts.isJsxText(run[a])) a++;
          while (b >= a && !ts.isJsxText(run[b])) b--;
          if (a <= b) {
            // expressions at the edges join the sentence when a text touches them on the same line
            let s = a, e = b;
            if (s > 0 && ts.isJsxExpression(run[s - 1]) && !/^\s*\n/.test(run[s].text) && jsxNormalize(run[s].text) !== "") s--;
            if (e < run.length - 1 && ts.isJsxExpression(run[e + 1]) && !/\n\s*$/.test(run[e].text) && jsxNormalize(run[e].text) !== "") e++;
            const seg = run.slice(s, e + 1);
            let value = "";
            const used = new Set();
            const vars = [];
            for (const c of seg) {
              if (ts.isJsxText(c)) value += jsxNormalize(c.text).replace(/\{/g, "(").replace(/\}/g, ")");
              else {
                const name = varName(c.expression, sf, used);
                vars.push(`${name}: ${c.expression.getText(sf)}`);
                value += `{${name}}`;
              }
            }
            const lead = /^\s/.test(value) ? `{" "}` : "";
            const trail = /\s$/.test(value) ? `{" "}` : "";
            const v = value.trim();
            if (isNL(v.replace(/\{[^}]*\}/g, " x "))) {
              count(seg[0], "jsx", v);
              const key = keyFor(area, fileNs, "text", v);
              const call = vars.length ? `${fn}("${key}", { ${vars.join(", ")} })` : `${fn}("${key}")`;
              const startNode = seg[0];
              const start = ts.isJsxText(startNode) ? startNode.pos : startNode.getStart(sf);
              // keep pure-whitespace text edges as they were (they carry line breaks)
              const first = seg[0], last = seg[seg.length - 1];
              let st = start, en = last.end, pre = "", post = "";
              if (ts.isJsxText(first)) { const m = first.text.match(/^\s*/)[0]; if (m.includes("\n")) { st = first.pos + m.length; } }
              if (ts.isJsxText(last)) { const m = last.text.match(/\s*$/)[0]; if (m.includes("\n")) { en = last.end - m.length; } }
              const leadNeeded = lead && !(ts.isJsxText(first) && first.text.match(/^\s*/)[0].includes("\n"));
              const trailNeeded = trail && !(ts.isJsxText(last) && last.text.match(/\s*$/)[0].includes("\n"));
              pre = leadNeeded ? lead : ""; post = trailNeeded ? trail : "";
              edits.push([st, en, `${pre}{${call}}${post}`]);
            }
          }
          i = j + 1;
        }
      }
    }
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) {
      if (!ts.isJsxText(n) && isNL(n.text) && literalContextOk(n) && !insideT(n)) {
        count(n, ts.isJsxAttribute(n.parent) ? "attr" : "str", n.text);
        const key = keyFor(area, fileNs, ts.isJsxAttribute(n.parent) ? "attr" : "str", n.text.replace(/\{/g, "(").replace(/\}/g, ")"));
        const repl = ts.isJsxAttribute(n.parent) ? `{${fn}("${key}")}` : `${fn}("${key}")`;
        edits.push([n.getStart(sf), n.end, repl]);
      }
    } else if (ts.isTemplateExpression(n)) {
      const stat = n.head.text + n.templateSpans.map((s) => " " + s.literal.text).join("");
      if (isNL(stat) && literalContextOk(n) && !insideT(n) && !n.templateSpans.some((s) => s.expression.getText(sf).includes("`"))) {
        const used = new Set();
        const vars = [];
        let value = n.head.text.replace(/\{/g, "(").replace(/\}/g, ")");
        for (const s of n.templateSpans) {
          const name = varName(s.expression, sf, used);
          vars.push(`${name}: ${s.expression.getText(sf)}`);
          value += `{${name}}` + s.literal.text.replace(/\{/g, "(").replace(/\}/g, ")");
        }
        count(n, "tpl", value);
        const key = keyFor(area, fileNs, "tpl", value);
        const repl = `${fn}("${key}", { ${vars.join(", ")} })`;
        const p = n.parent;
        edits.push([n.getStart(sf), n.end, ts.isJsxAttribute(p) ? `{${repl}}` : repl]);
        return; // inner templates handled as part of this one
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  if (APPLY && edits.length) {
    let text = sf.getFullText();
    edits.sort((x, y) => y[0] - x[0]);
    let lastStart = Infinity;
    for (const [s, e, r] of edits) {
      if (e > lastStart) continue; // overlapping (nested) edit: outer one already applied
      text = text.slice(0, s) + r + text.slice(e);
      lastStart = s;
    }
    // import
    const relI18n = path.relative(path.dirname(abs), path.join(SRC, "lib/i18n")).replace(/\\/g, "/");
    const spec = relI18n.startsWith(".") ? relI18n : "./" + relI18n;
    const want = fn === "tr" ? "t as tr" : "t";
    const re = new RegExp(`import \\{([^}]*)\\} from "${spec.replace(/[./]/g, (c) => "\\" + c)}";`);
    const m = text.match(re);
    if (m) {
      const names = m[1].split(",").map((x) => x.trim()).filter(Boolean);
      if (!names.includes(want)) {
        const filtered = want === "t as tr" ? names.filter((x) => x !== "t") : names;
        filtered.push(want);
        text = text.replace(re, `import { ${filtered.join(", ")} } from "${spec}";`);
      }
    } else {
      const imps = [...text.matchAll(/^import [^;]+;$/gm)];
      const pos = imps.length ? imps[imps.length - 1].index + imps[imps.length - 1][0].length : 0;
      text = text.slice(0, pos) + `\nimport { ${want} } from "${spec}";` + text.slice(pos);
    }
    fs.writeFileSync(abs, text);
    touched.push(rel);
  }
}
if (APPLY) {
  for (const [area, d] of Object.entries(dicts)) {
    const f = path.join(STR_DIR, `${area}.ts`);
    let head;
    if (fs.existsSync(f)) head = fs.readFileSync(f, "utf8").split("export const")[0];
    else head = `/**\n * ${area} copy (UX-STANDARD 8): keyed per screen (\`${area}.<file>.<kind>.<name>\`), English default; merged into the\n * dictionary in \`lib/i18n.ts\`. Values with \`{name}\` are filled by \`t(key, { name })\`.\n */\n`;
    const body = Object.keys(d).sort().map((k) => `  ${JSON.stringify(k)}: ${JSON.stringify(d[k])},`).join("\n");
    fs.writeFileSync(f, `${head}export const ${area}Strings = {\n${body}\n} as const;\n`);
  }
  console.log("files changed", touched.length);
}
if (LIST) console.log(listOut.join("\n"));
console.log("hard-coded user-facing strings:", total, JSON.stringify(perArea));

// ---------------------------------------------------------------- M7 10: translation parity (fr-CA)
// Every English key (lib/strings/<area>.ts and the inline keys of lib/i18n.ts) must exist in
// lib/strings/fr-CA/<area>.ts (common.ts for the inline keys) with the same {placeholders}; no extra keys.
{
  const readDict = (f) => {
    const d = {};
    if (fs.existsSync(f)) for (const m of fs.readFileSync(f, "utf8").matchAll(/^  ("[^"\n]+"): (".*"),$/gm)) d[JSON.parse(m[1])] = JSON.parse(m[2]);
    return d;
  };
  const ph = (s) => [...new Set(s.match(/\{[A-Za-z0-9_]+\}/g) || [])].sort().join(",");
  const FR = path.join(STR_DIR, "fr-CA");
  const pairs = [[path.join(SRC, "lib/i18n.ts"), path.join(FR, "common.ts"), "common"]];
  for (const f of fs.readdirSync(STR_DIR)) if (f.endsWith(".ts")) pairs.push([path.join(STR_DIR, f), path.join(FR, f), f.replace(/\.ts$/, "")]);
  let problems = 0;
  const report = [];
  for (const [enFile, frFile, area] of pairs) {
    const en = readDict(enFile);
    const fr = readDict(frFile);
    for (const k of Object.keys(en)) {
      if (!(k in fr)) (problems++, report.push(`fr-CA missing ${area}: ${k}`));
      else if (ph(en[k]) !== ph(fr[k])) (problems++, report.push(`fr-CA placeholders differ ${area}: ${k} [${ph(en[k])}] vs [${ph(fr[k])}]`));
    }
    for (const k of Object.keys(fr)) if (!(k in en)) (problems++, report.push(`fr-CA extra key ${area}: ${k}`));
  }
  if (LIST || problems) console.log(report.slice(0, 50).join("\n"));
  console.log("fr-CA parity problems:", problems);
  if (problems || total) process.exitCode = 1;
}
