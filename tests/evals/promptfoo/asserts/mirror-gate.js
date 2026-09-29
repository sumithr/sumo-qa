// Deterministic mirror gate for the mirrored dependency constraint corpus
// (skill-reviewing-before-merge-mirrored-constraints.yaml and its .ab.yaml).
// It isolates the decisive outcome from the llm-rubric's SHAPE/GROUNDING axes
// and only ever tightens that rubric:
//
//   * the FINAL verdict (the last NOT SAFE TO MERGE / SAFE TO MERGE / NEEDS
//     WORK in the output) must be NOT SAFE TO MERGE on a seed with
//     `stale_mirror_path` and SAFE TO MERGE on every other seed, so a verdict
//     phrase quoted earlier ("it would be NOT SAFE TO MERGE if...") never
//     stands in for the verdict line;
//   * a seed with `stale_mirror_path` must name that path and require the
//     isolated environment's own run (`stale_mirror_verifier`, default
//     `pre-commit run`) as a command someone still has to run: a mention
//     framed as a requirement (until, must, clears, verifier, ...) counts, a
//     mention the text negates ("no `pre-commit run` evidence", "`pre-commit
//     run` was not executed") does not, and `pre-commit install` runs nothing;
//   * no seed may name a `not_stale_paths` entry in a finding: an inventory
//     drift row, a coverage-ledger row (`Risk ... | Anchor: ...`), a
//     `Risk N:` line, a `Surface verifier:` line, or a markdown table row
//     whose anchor column names it. Any label other than COVERED / DISCHARGED
//     fails (UNCOVERED, UNPROVEN, N/A, UNVERIFIED); a `Risk N:` line carries
//     no label, so it fails unless a COVERED row names the same path;
//   * a seed without `stale_mirror_path` may emit no UNCOVERED inventory-drift
//     anchor at all.
//
// Only those pinned row shapes count: a prose line that merely contains
// `anchor:` or names a path beside the word UNCOVERED is not a finding.
// Labels match case-insensitively.
//
// Referenced as `value: file://asserts/mirror-gate.js` from both configs.

const { stripMarkdown, tableCells } = require('./ledger-row-labels');

const NEGATION = /\b(no|not|never|without|none|nor|nothing)\b|n't\b/gi;

// Words that frame a command as something still to be run.
const FRAME = /\b(until|unless|require[sd]?|requirement|must|needs?|clears?|clear(?:ed|ing)?|verifier|verify|blocker|once|re-?run)\b/gi;

// A mention's scope: from the previous sentence end or table pipe to the next.
// A colon does not end it, so "`pre-commit run` evidence: none" stays one scope.
const SCOPE_BREAK = /[.;!?](?=\s|$)|\|/g;

const VERDICT = /NOT SAFE TO MERGE|SAFE TO MERGE|NEEDS WORK/g;

function commandPattern(command) {
  const words = String(command).trim().split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  return new RegExp(`${words.join('\\s+')}\\b`, 'gi');
}

function lastIndex(re, text) {
  let last = -1;
  for (const m of text.matchAll(re)) last = m.index;
  return last;
}

function scopeAround(line, start, end) {
  let from = 0;
  for (const m of line.slice(0, start).matchAll(SCOPE_BREAK)) from = m.index + m[0].length;
  const rest = line.slice(end);
  const next = rest.search(SCOPE_BREAK);
  return { before: line.slice(from, start), after: next === -1 ? rest : rest.slice(0, next) };
}

// True when some mention of `command` requires running it. Negation is judged
// relative to the command: a requirement frame after the last negation before
// it ("NOT SAFE TO MERGE until <command>") makes the mention a requirement; a
// negation before it with no later frame ("no <command> evidence"), or, with
// no frame at all, a negation after it in the same scope ("<command> was not
// executed", "<command> evidence: none"), makes it a negated mention.
function requiresCommand(text, command) {
  const pattern = commandPattern(command);
  for (const rawLine of String(text).split(/\r?\n/)) {
    const line = stripMarkdown(rawLine);
    for (const match of line.matchAll(pattern)) {
      const { before, after } = scopeAround(line, match.index, match.index + match[0].length);
      const neg = lastIndex(NEGATION, before);
      const frame = lastIndex(FRAME, before);
      if (frame > neg) return true;
      if (neg !== -1) continue;
      if (lastIndex(NEGATION, after) === -1) return true;
    }
  }
  return false;
}

// The final verdict phrase in the output, or null. Uppercase is the pinned
// vocabulary; a lowercase phrase counts only when no uppercase one exists.
function finalVerdict(output) {
  const text = stripMarkdown(String(output == null ? '' : output));
  let matches = [...text.matchAll(VERDICT)];
  if (!matches.length) matches = [...text.matchAll(new RegExp(VERDICT.source, 'gi'))];
  return matches.length ? matches[matches.length - 1][0].toUpperCase() : null;
}

function isUncovered(value) {
  return /^\s*uncovered\b/i.test(String(value || ''));
}

function isCleared(value) {
  return /^\s*(covered|discharged)\b/i.test(String(value || ''));
}

// The row's label: its Coverage/Status field, else the first `|` field that
// is a bare coverage label.
function inlineLabel(line) {
  const field = line.match(/(?:coverage|status):\s*([^|]*)/i);
  if (field) return field[1].trim();
  const bare = line.split('|').map((f) => f.trim()).find((f) => /^(uncovered|unproven|covered|discharged|n\/a|unverified)\b/i.test(f));
  return bare || '';
}

const DRIFT_ROW = /^[\s>\-*+\d.)]*inventory drift anchor:\s*([^|]*)\|/i;
const LEDGER_ROW = /^[\s>\-*+\d.)]*risk\b[^|]*\|\s*anchor:\s*([^|]*)/i;
const RISK_LINE = /^[\s>\-*+\d.)]*risk\s*\d+\s*:/i;
const VERIFIER_LINE = /^[\s>\-*+\d.)]*surface verifier:\s*([^|]*)/i;

// Every finding row, as { kind, anchor, label, drift }. Only the pinned
// shapes count; `label` is '' when the shape carries none (a `Risk N:` line).
function findingRows(output) {
  const rows = [];
  let table = null;
  for (const rawLine of String(output == null ? '' : output).split(/\r?\n/)) {
    const line = stripMarkdown(rawLine);
    const cells = tableCells(line);
    if (!cells) {
      table = null;
      let m = line.match(DRIFT_ROW);
      if (m) {
        rows.push({ kind: 'drift', anchor: m[1], label: inlineLabel(line), drift: true });
        continue;
      }
      m = line.match(LEDGER_ROW);
      if (m) {
        rows.push({ kind: 'ledger', anchor: m[1], label: inlineLabel(line), drift: false });
        continue;
      }
      m = line.match(VERIFIER_LINE);
      if (m) {
        rows.push({ kind: 'verifier', anchor: line, label: inlineLabel(line), drift: false });
        continue;
      }
      if (RISK_LINE.test(line)) rows.push({ kind: 'risk', anchor: line, label: '', drift: false });
      continue;
    }
    const anchorCol = cells.findIndex((c) => /anchor|^(path|file|location)\b/i.test(c));
    const labelCol = cells.findIndex((c) => /^(coverage|status)\b/i.test(c));
    if (anchorCol !== -1 && labelCol !== -1 && !table) {
      table = { anchor: anchorCol, label: labelCol, drift: /inventory drift|drift anchor/i.test(cells.join(' ')) };
      continue;
    }
    if (!table || cells.every((c) => /^:?-*:?$/.test(c))) continue;
    rows.push({
      kind: table.drift ? 'drift' : 'ledger',
      anchor: cells[table.anchor] || '',
      label: cells[table.label] || '',
      drift: table.drift,
    });
  }
  return rows;
}

function isNoneAnchor(anchor) {
  return /^\s*(none|n\/a)\b/i.test(String(anchor || ''));
}

module.exports = function mirrorGate(output, context) {
  const vars = (context && context.vars) || {};
  const text = String(output == null ? '' : output);
  const fails = [];
  const mustFlag = vars.stale_mirror_path;
  const expected = mustFlag ? 'NOT SAFE TO MERGE' : 'SAFE TO MERGE';
  const verdict = finalVerdict(text);
  if (verdict !== expected) fails.push(`final verdict is ${verdict || 'missing'}, expected ${expected}`);
  if (mustFlag) {
    const verifier = vars.stale_mirror_verifier || 'pre-commit run';
    if (!text.includes(mustFlag)) fails.push(`stale mirror ${mustFlag} not named`);
    if (!requiresCommand(text, verifier)) {
      fails.push(`isolated environment verifier (a required \`${verifier}\` command) not required`);
    }
  }
  const rows = findingRows(text);
  for (const p of vars.not_stale_paths || []) {
    const naming = rows.filter((r) => !isNoneAnchor(r.anchor) && r.anchor.includes(p));
    const clearedElsewhere = naming.some((r) => isCleared(r.label));
    const bad = naming.find((r) => (r.kind === 'risk' ? !clearedElsewhere : !isCleared(r.label)));
    if (bad) fails.push(`non-mirror occurrence ${p} named in a ${bad.kind} finding (${bad.label || 'no label'})`);
  }
  if (!mustFlag && rows.some((r) => r.drift && !isNoneAnchor(r.anchor) && isUncovered(r.label))) {
    fails.push('seed without a stale mirror emitted an UNCOVERED inventory drift anchor');
  }
  return fails.length
    ? { pass: false, score: 0, reason: `Mirror gate FAIL: ${fails.join('; ')}` }
    : { pass: true, score: 1, reason: 'Mirror gate: verdict, stale mirrors and non-mirrors as this seed requires.' };
};

// Exposed for offline verification.
module.exports.requiresCommand = requiresCommand;
module.exports.findingRows = findingRows;
module.exports.finalVerdict = finalVerdict;
