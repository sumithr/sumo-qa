// Structural mirror gate for the mirrored dependency constraint corpus
// (skill-reviewing-before-merge-mirrored-constraints.yaml and its .ab.yaml).
// It reads only the two pinned row shapes the review module emits, so it never
// judges prose:
//
//   * `Inventory drift anchor: <path>:<line> (<old> → <new>) | ... | Coverage: <label>`
//   * `Surface verifier: <verifier> | ... | Status: <label>`
//
// A line counts only when it starts with one of those prefixes (after list
// markers and markdown emphasis) and carries `|`-separated fields. Rules:
//
//   * a seed with `stale_mirror_path` must name that path in a drift row whose
//     Coverage is UNCOVERED and in a verifier line whose Status is UNVERIFIED;
//   * no seed may name a `not_stale_paths` entry in either shape, whatever
//     its label.
//
// Markdown tables, `Risk N:` lines and free text (relationship lines, the
// verdict, the clearing command's wording) never pass or fail this gate; the
// llm-rubric judges them.
//
// Referenced as `value: file://asserts/mirror-gate.js` from both configs.

const PREFIX = /^[\s>\-*+\d.)]*(inventory drift anchor|surface verifier):\s*/i;

function strip(line) {
  return String(line).replace(/\*\*|__|[*`]/g, '');
}

// Each pinned-shape row as { kind: 'drift' | 'verifier', head, label }.
// `head` is the first field (the drift anchor, or the verifier command with
// the environment it runs), `label` the Coverage / Status field's value (''
// when absent). Paths are matched in `head` only.
function pinnedRows(output) {
  const rows = [];
  for (const raw of String(output == null ? '' : output).split(/\r?\n/)) {
    const line = strip(raw);
    const m = line.match(PREFIX);
    if (!m || !line.includes('|')) continue;
    const fields = line.slice(m[0].length).split('|').map((f) => f.trim());
    const kind = /^inventory/i.test(m[1]) ? 'drift' : 'verifier';
    const labelKey = kind === 'drift' ? /^coverage:\s*/i : /^status:\s*/i;
    const labelField = fields.find((f) => labelKey.test(f));
    rows.push({
      kind,
      head: fields[0],
      label: labelField ? labelField.replace(labelKey, '') : '',
    });
  }
  return rows;
}

function hasLabel(row, label) {
  return new RegExp(`^${label}\\b`, 'i').test(row.label);
}

module.exports = function mirrorGate(output, context) {
  const vars = (context && context.vars) || {};
  const rows = pinnedRows(output);
  const fails = [];
  const stale = vars.stale_mirror_path;
  if (stale) {
    if (!rows.some((r) => r.kind === 'drift' && r.head.includes(stale) && hasLabel(r, 'UNCOVERED'))) {
      fails.push(`stale mirror ${stale} has no UNCOVERED \`Inventory drift anchor:\` row`);
    }
    if (!rows.some((r) => r.kind === 'verifier' && r.head.includes(stale) && hasLabel(r, 'UNVERIFIED'))) {
      fails.push(`stale mirror ${stale} has no UNVERIFIED \`Surface verifier:\` line`);
    }
  }
  for (const p of vars.not_stale_paths || []) {
    const bad = rows.find((r) => r.head.includes(p));
    if (bad) fails.push(`non-mirror occurrence ${p} named in a ${bad.kind} row (${bad.label || 'no label'})`);
  }
  return fails.length
    ? { pass: false, score: 0, reason: `Mirror gate FAIL: ${fails.join('; ')}` }
    : { pass: true, score: 1, reason: 'Mirror gate: pinned drift rows and verifier lines as this seed requires.' };
};

// Exposed for offline verification.
module.exports.pinnedRows = pinnedRows;
