// Deterministic routing-state leak assertion for the deciding-approach
// user-facing eval (issue #248): the approach router is an internal hop, so
// its routing payload, taxonomy labels, route announcement and checklist
// bookkeeping must never appear in what the user reads.
//
// Mirrors `find_routing_leaks` in src/sumo_qa/conformance.py family for
// family; tests/test_eval_no_routing_leak_assert.py runs both over
// tests/scenarios/conformance/leak_transcripts.yaml so the two cannot drift.
//
// Families:
//   * payload_json       a brace-balanced span naming classification, approach
//                        AND next_action (compact, pretty, or unquoted keys);
//   * taxonomy_label     `Classification:` / `Approach:` whose value is exactly
//                        a catalogue entry name (read from knowledge/) or n/a;
//   * route_announcement "Picking the QA approach", "Routing to sumo-qa-...",
//                        or first-person handoff narration ("I'm routing you to");
//   * checklist_status   [DONE] / [IN PROGRESS] / [PENDING] / [COMPLETED];
//   * router_checklist   a numbered line naming a router step.
// Ordinary prose using "approach" or "classification" passes.

const fs = require('fs');
const path = require('path');

const KNOWLEDGE_DIR = path.resolve(__dirname, '..', '..', '..', '..', 'knowledge');
const PAYLOAD_KEYS = ['classification', 'approach', 'next_action'];
const ROUTE_ANNOUNCEMENT =
  /picking the qa approach|\b(?:routing|handing off|routed) to\W{0,3}(?:sumo[-_]qa|using[-_]sumo[-_]qa)|\b(?:i'm|i am|i'll|i will)\s+(?:now\s+)?(?:rout(?:e|ing)|handing)\s+(?:you|this)\b/i;
const CHECKLIST_STATUS = /\[(?:done|in[ _]progress|pending|completed)\]/i;
const ROUTER_CHECKLIST =
  /^\s*\d+[.)]\s+.*(?:load_classifications|load_approaches|removability gate|reason about (?:classification|shape)|routing[- ]payload|read the user's intent)/im;

function catalogueNames() {
  const names = [];
  for (const file of ['classifications.md', 'approaches.md']) {
    let text;
    try {
      text = fs.readFileSync(path.join(KNOWLEDGE_DIR, file), 'utf8');
    } catch {
      return [];
    }
    for (const m of text.matchAll(/^##\s+([a-z][a-z0-9_-]*)\s*$/gm)) names.push(m[1]);
  }
  return names;
}

function braceSpans(text) {
  const spans = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === '{') {
      if (depth === 0) start = i;
      depth += 1;
    } else if (text[i] === '}' && depth) {
      depth -= 1;
      if (depth === 0) spans.push(text.slice(start, i + 1));
    }
  }
  return spans;
}

function hasRoutingPayload(text) {
  return braceSpans(text).some((span) =>
    PAYLOAD_KEYS.every((key) => new RegExp(`\\b${key}["']?\\s*:`).test(span)),
  );
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function hasTaxonomyLabel(text) {
  const names = catalogueNames().sort((a, b) => b.length - a.length);
  if (!names.length) return false;
  const alternatives = names.map(escapeRegExp).join('|');
  const label = new RegExp(
    `(?<![\\w"'])(?:classification|approach)[\\s*\`"']{0,4}:[\\s*\`"']{0,6}` +
      `(?:${alternatives}|n/a)[\`*"']*(?=\\s*$|[.,;)])`,
    'im',
  );
  return label.test(text);
}

const CHECKS = {
  payload_json: hasRoutingPayload,
  taxonomy_label: hasTaxonomyLabel,
  route_announcement: (s) => ROUTE_ANNOUNCEMENT.test(s),
  checklist_status: (s) => CHECKLIST_STATUS.test(s),
  router_checklist: (s) => ROUTER_CHECKLIST.test(s),
};

function findRoutingLeaks(text) {
  return Object.keys(CHECKS).filter((family) => CHECKS[family](String(text)));
}

module.exports = (output) => {
  const leaks = findRoutingLeaks(output);
  if (leaks.length) {
    return {
      pass: false,
      score: 0,
      reason: `internal routing state leaked into the user-visible reply: ${leaks.join(', ')}`,
    };
  }
  return { pass: true, score: 1, reason: 'no routing payload, taxonomy label, announcement or checklist leaked' };
};

// Exposed for offline verification.
module.exports.findRoutingLeaks = findRoutingLeaks;
