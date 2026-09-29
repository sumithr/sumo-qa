// Deterministic mirror gate for the mirrored dependency constraint corpus
// (skill-reviewing-before-merge-mirrored-constraints.yaml and its .ab.yaml).
// It isolates the decisive outcome from the llm-rubric's SHAPE/GROUNDING axes
// and only ever tightens that rubric:
//
//   * a seed with `stale_mirror_path` must name that path, deliver
//     NOT SAFE TO MERGE, and require the isolated environment's own run
//     (`stale_mirror_verifier`, default `pre-commit run`) as an affirmative
//     command: `pre-commit install` does not run the hook, and a negated
//     mention ("no `pre-commit run` evidence was supplied") requires nothing;
//   * no seed may anchor a `not_stale_paths` entry in an UNCOVERED ledger or
//     inventory-drift row, whether the row is inline
//     (`Inventory drift anchor: <path> ... | Coverage: UNCOVERED`) or a
//     markdown table row whose anchor column names the path;
//   * a seed without `stale_mirror_path` may emit no UNCOVERED inventory-drift
//     anchor at all.
//
// A path named in prose beside the word UNCOVERED is not a row about that
// path; only a row's own anchor field counts. Labels match case-insensitively.
//
// Referenced as `value: file://asserts/mirror-gate.js` from both configs.

const { stripMarkdown, tableCells } = require('./ledger-row-labels');

const NEGATION = /\b(no|not|never|without|none|nor|nothing)\b|n't\b/i;

// Clauses end at sentence punctuation, a colon, a semicolon, a table pipe or a
// dash separator, so a negation only counts when it governs the command.
const CLAUSE_BREAK = /[.;:!?|]\s|[;|]|\s[-–—]\s/;

function commandPattern(command) {
  const words = String(command).trim().split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  return new RegExp(`${words.join('\\s+')}\\b`, 'gi');
}

// True when some mention of `command` is affirmative: the clause text before
// it carries no negation word.
function requiresCommand(text, command) {
  const pattern = commandPattern(command);
  for (const rawLine of String(text).split(/\r?\n/)) {
    const line = stripMarkdown(rawLine);
    for (const match of line.matchAll(pattern)) {
      const before = line.slice(0, match.index);
      const parts = before.split(CLAUSE_BREAK);
      const clause = parts[parts.length - 1];
      if (!NEGATION.test(clause)) return true;
    }
  }
  return false;
}

function isUncovered(value) {
  return /^\s*uncovered\b/i.test(String(value || ''));
}

// Every row that anchors a path, as { anchor, coverage, drift }.
// `coverage` is the row's Coverage/Status value, or the whole line when an
// inline row carries no Coverage field.
function anchoredRows(output) {
  const rows = [];
  let table = null;
  for (const rawLine of String(output == null ? '' : output).split(/\r?\n/)) {
    const line = stripMarkdown(rawLine);
    const anchors = [...line.matchAll(/anchor:([^|]*)/gi)];
    if (anchors.length) {
      const coverage = line.match(/(?:coverage|status):\s*([^|]*)/i);
      const drift = /inventory drift anchor:/i.test(line);
      for (const a of anchors) {
        rows.push({
          anchor: a[1],
          coverage: coverage ? coverage[1] : (/\buncovered\b/i.test(line) ? 'UNCOVERED' : ''),
          drift,
        });
      }
      table = null;
      continue;
    }
    const cells = tableCells(line);
    if (!cells) {
      table = null;
      continue;
    }
    const anchorCol = cells.findIndex((c) => /anchor|^(path|file|location)\b/i.test(c));
    const coverageCol = cells.findIndex((c) => /^(coverage|status)\b/i.test(c));
    if (anchorCol !== -1 && coverageCol !== -1 && !table) {
      table = { anchor: anchorCol, coverage: coverageCol, drift: /inventory drift|drift anchor/i.test(cells.join(' ')) };
      continue;
    }
    if (!table || cells.every((c) => /^:?-*:?$/.test(c))) continue;
    rows.push({
      anchor: cells[table.anchor] || '',
      coverage: cells[table.coverage] || '',
      drift: table.drift,
    });
  }
  return rows;
}

module.exports = function mirrorGate(output, context) {
  const vars = (context && context.vars) || {};
  const text = String(output == null ? '' : output);
  const fails = [];
  const mustFlag = vars.stale_mirror_path;
  if (mustFlag) {
    const verifier = vars.stale_mirror_verifier || 'pre-commit run';
    if (!text.includes(mustFlag)) fails.push(`stale mirror ${mustFlag} not named`);
    if (!/not safe to merge/i.test(text)) fails.push('blocker seed did not deliver NOT SAFE TO MERGE');
    if (!requiresCommand(text, verifier)) {
      fails.push(`isolated environment verifier (an affirmative \`${verifier}\` command) not required`);
    }
  }
  const rows = anchoredRows(text);
  for (const p of vars.not_stale_paths || []) {
    if (rows.some((r) => isUncovered(r.coverage) && r.anchor.includes(p))) {
      fails.push(`non-mirror occurrence ${p} anchored as UNCOVERED`);
    }
  }
  if (!mustFlag && rows.some((r) => r.drift && isUncovered(r.coverage))) {
    fails.push('seed without a stale mirror emitted an UNCOVERED inventory drift anchor');
  }
  return fails.length
    ? { pass: false, score: 0, reason: `Mirror gate FAIL: ${fails.join('; ')}` }
    : { pass: true, score: 1, reason: 'Mirror gate: stale mirrors named and non-mirrors left alone as this seed requires.' };
};

// Exposed for offline verification.
module.exports.requiresCommand = requiresCommand;
module.exports.anchoredRows = anchoredRows;
