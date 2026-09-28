// Deterministic ledger-consistency assertion for the reviewing-before-merge
// evals (issue #689): does every coverage-ledger row's label agree with its own
// `Fresh matching tests` field?
//
// The rule is pinned in skills/sumo-qa-reviewing-before-merge/modules/
// coverage-ledger.md ("Coverage labels (pinned)"): the label follows the row.
// A row that lists a fresh test is never UNCOVERED; a row whose tests field is
// NONE is never UNPROVEN and never COVERED. The llm-rubric judges which label
// the scenario calls for; this check only fails a row that contradicts itself,
// which a judge can read past.
//
// Parsed shapes (markdown bold/italics/backticks stripped first):
//   * inline rows: any line carrying both `Fresh matching tests:` and
//     `Coverage:`, with or without surrounding table pipes;
//   * markdown tables whose header has a `Fresh matching tests` column and a
//     `Coverage` column.
// Only the three path-keyed labels are checked. Other labels (N/A, COVERED BY
// VERIFICATION, DISCHARGED, module-pinned statuses) are ignored, and output
// with no ledger rows passes: other assertions own "a ledger must exist".
//
// Shared by every skill-reviewing-before-merge*.yaml config that loads the
// coverage-ledger module, via `value: file://asserts/ledger-row-labels.js`.

const LABELS = ['UNCOVERED', 'UNPROVEN', 'COVERED'];

function stripMarkdown(text) {
  return String(text).replace(/\*\*|__|[*`]/g, '');
}

// NONE, "none", "(none)", "no path-matching test", "N/A", "nothing",
// "0 tests", "not run", an empty field, or a bare dash all mean no fresh test
// is listed.
function isNone(tests) {
  const value = tests.trim();
  if (value === '' || /^[-–—]+$/.test(value)) return true;
  return /^[\s([]*(none|no|n\/a|nothing|0 tests?|not run)(?![\w/])/i.test(value);
}

// Returns UNCOVERED / UNPROVEN / COVERED, or null for a label this check ignores.
function coverageLabel(field) {
  const value = field.trim();
  if (/^COVERED\s+BY\s+VERIFICATION\b/i.test(value)) return null;
  const match = value.match(/^(UNCOVERED|UNPROVEN|COVERED)\b/i);
  return match ? match[1].toUpperCase() : null;
}

function contradiction(tests, label) {
  if (!label) return null;
  const none = isNone(tests);
  if (!none && label === 'UNCOVERED') return 'lists a fresh test but is labelled UNCOVERED';
  if (none && label !== 'UNCOVERED') return `has Fresh matching tests NONE but is labelled ${label}`;
  return null;
}

// The tests field runs lazily up to the row's own `Coverage:` key, so a test ID
// carrying `|` (a parametrized id such as `test_parse[a|b]`) stays in the
// field instead of hiding the row from the check.
const INLINE_ROW = /Fresh matching tests:\s*(.*?)\s*\|?\s*Coverage:\s*([^|]*)/gi;

function inlineRows(line) {
  const rows = [];
  for (const match of line.matchAll(INLINE_ROW)) {
    rows.push({ tests: match[1], coverage: match[2] });
  }
  return rows;
}

function tableCells(line) {
  const trimmed = line.trim();
  if (!trimmed.startsWith('|')) return null;
  return trimmed.replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
}

function describe(row) {
  const risk = row.match(/Risk[^:|]*:\s*([^|]+)/i);
  const text = risk ? `Risk: ${risk[1].trim()}` : row.trim();
  return text.length > 160 ? `${text.slice(0, 157)}...` : text;
}

// Every ledger row in `output`, as { text, tests, label }.
function ledgerRows(output) {
  const rows = [];
  let table = null; // { tests, coverage } column indexes while inside a ledger table
  for (const rawLine of String(output == null ? '' : output).split(/\r?\n/)) {
    const line = stripMarkdown(rawLine);
    const inline = inlineRows(line);
    if (inline.length) {
      for (const r of inline) {
        rows.push({ text: line, tests: r.tests, label: coverageLabel(r.coverage) });
      }
      continue;
    }
    const cells = tableCells(line);
    if (!cells) {
      table = null;
      continue;
    }
    const testsCol = cells.findIndex((c) => /^fresh matching tests$/i.test(c));
    const coverageCol = cells.findIndex((c) => /^coverage$/i.test(c));
    if (testsCol !== -1 && coverageCol !== -1) {
      table = { tests: testsCol, coverage: coverageCol, header: cells };
      continue;
    }
    if (!table || cells.every((c) => /^:?-*:?$/.test(c))) continue;
    const riskCol = table.header.findIndex((c) => /^risk/i.test(c));
    const risk = riskCol !== -1 && cells[riskCol] ? `Risk: ${cells[riskCol]} | ` : '';
    rows.push({
      text: `${risk}Fresh matching tests: ${cells[table.tests] || ''} | Coverage: ${cells[table.coverage] || ''}`,
      tests: cells[table.tests] || '',
      label: coverageLabel(cells[table.coverage] || ''),
    });
  }
  return rows;
}

module.exports = function ledgerRowLabels(output) {
  const rows = ledgerRows(output);
  const checked = rows.filter((r) => LABELS.includes(r.label));
  const offending = [];
  for (const row of checked) {
    const problem = contradiction(row.tests, row.label);
    if (problem) offending.push(`"${describe(row.text)}" ${problem}`);
  }
  if (offending.length) {
    return {
      pass: false,
      score: 0,
      reason: `ledger label contradicts its tests field (a listed test is never UNCOVERED; NONE is only UNCOVERED): ${offending.join('; ')}`,
    };
  }
  if (!checked.length) {
    return { pass: true, score: 1, reason: 'no COVERED/UNPROVEN/UNCOVERED ledger rows to check' };
  }
  return {
    pass: true,
    score: 1,
    reason: `${checked.length} ledger row(s) checked; every label agrees with its tests field`,
  };
};

// Exposed for offline verification.
module.exports.ledgerRows = ledgerRows;
module.exports.isNone = isNone;
module.exports.coverageLabel = coverageLabel;
