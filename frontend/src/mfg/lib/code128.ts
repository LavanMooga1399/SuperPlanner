/**
 * Code 128 encoder (M4 5): subset B for printable ASCII, with runs of 4+ digits packed in subset C. Returns the
 * module pattern (bar/space widths, starting with a bar) including the quiet-zone-free start, data, checksum and
 * stop symbols. Pure; drawn as SVG by `components/Barcode.tsx`.
 */

// bar/space widths of the 107 symbols (0-105 data/start, 106 stop with its final bar)
const PATTERNS = [
  "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
  "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
  "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
  "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
  "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
  "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
  "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
  "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
  "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
  "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
  "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
];
const START_B = 104;
const START_C = 105;
const CODE_B = 100;
const CODE_C = 99;
const STOP = 106;

export class Code128Error extends Error {}

/** Symbol values (start ... checksum, stop) for `text`. Throws `Code128Error` for characters outside ASCII 32-126. */
export function code128Symbols(text: string): number[] {
  for (const ch of text) {
    const c = ch.charCodeAt(0);
    if (c < 32 || c > 126) throw new Code128Error(`Character "${ch}" cannot be encoded in Code 128 B`);
  }
  const out: number[] = [];
  let set: "B" | "C" | null = null;
  let i = 0;
  const digitsRun = (from: number) => {
    let n = 0;
    while (from + n < text.length && text[from + n] >= "0" && text[from + n] <= "9") n++;
    return n;
  };
  while (i < text.length) {
    const run = digitsRun(i);
    // subset C pays off for 4+ digits (6+ in the middle); use an even count
    const useC = run >= 4 && (i === 0 || i + run === text.length || run >= 6);
    if (useC) {
      const pairs = Math.floor(run / 2);
      if (set === null) out.push(START_C);
      else if (set !== "C") out.push(CODE_C);
      set = "C";
      // odd run: the leading digit goes in B first when starting, else the last one later in B
      for (let k = 0; k < pairs; k++) {
        out.push(Number(text.substr(i, 2)));
        i += 2;
      }
      continue;
    }
    if (set === null) out.push(START_B);
    else if (set !== "B") out.push(CODE_B);
    set = "B";
    out.push(text.charCodeAt(i) - 32);
    i++;
  }
  if (set === null) out.push(START_B);
  let sum = out[0];
  for (let k = 1; k < out.length; k++) sum += out[k] * k;
  out.push(sum % 103, STOP);
  return out;
}

/** Module widths (alternating bar, space, ... starting with a bar). */
export function code128Modules(text: string): number[] {
  const widths: number[] = [];
  for (const s of code128Symbols(text)) for (const ch of PATTERNS[s]) widths.push(Number(ch));
  return widths;
}

/** Total width in modules (without quiet zones). */
export function code128Width(text: string): number {
  return code128Modules(text).reduce((a, b) => a + b, 0);
}
