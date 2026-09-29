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
//   * payload_json       a brace-balanced span (braces in strings ignored)
//                        naming classification, approach, next_action AND a
//                        skill handoff (compact, pretty, or unquoted keys);
//   * taxonomy_label     `Classification:` / `Approach:` whose value is exactly
//                        a catalogue entry name (read from knowledge/) or n/a;
//   * route_announcement "Picking the QA approach", "Routing to sumo-qa-...",
//                        or first-person handoff narration ("I'm routing you to");
//   * checklist_status   [DONE] / [IN PROGRESS] / [PENDING] / [COMPLETED] on a
//                        line naming a router step;
//   * router_checklist   two or more numbered lines naming router steps.
// Ordinary prose using "approach" or "classification" passes.

const fs = require('fs');
const path = require('path');

// Catalogue names come from QA_KNOWLEDGE_PATH when set, else the repo's
// knowledge/ (what the eval configs load). Unlike the Python validator, this
// does not resolve ingested project/global packs.
const KNOWLEDGE_DIR =
  process.env.QA_KNOWLEDGE_PATH || path.resolve(__dirname, '..', '..', '..', '..', 'knowledge');
const PAYLOAD_KEYS = ['classification', 'approach', 'next_action'];
const NEXT_ACTION = /\bnext_action["']?\s*:\s*(?=\{)/g;
const SKILL_KEY = /\bskill["']?\s*:/;
// Quoted strings left to right: one followed by ':' is a key, any other is a
// value and is blanked before key matching.
const QUOTED = /(["'])(?:\\.|(?!\1)[\s\S])*\1/g;
const KEY_FOLLOWS = /^[ \t]*:/;
// One explicit character set for both engines (their \s differ).
const LINE_BREAK = /[\r\u2028\u2029]/g;
const SPACE = /[\t\v\f \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]/g;
const DECOR = '[\\s*_`"\']';
const ROUTE_ANNOUNCEMENT = new RegExp(
  'picking the qa approach' +
    '|\\b(?:routing|handing off|routed) to[\\s*_`"\'\\[(]{0,8}(?:sumo[-_]qa|using[-_]sumo[-_]qa)' +
    "|\\b(?:i'm|i am|i'll|i will)\\s+(?:now\\s+)?(?:rout(?:e|ing)|handing)\\s+(?:you|this)\\b",
  'i',
);
const ROUTER_STEP =
  '(?:load(?:_|\\s+)(?:the\\s+)?(?:classifications|approaches|catalogues)' +
  '|removability (?:gate|check)|reason about (?:classification|shape)' +
  "|routing[- ]payload|read the user's intent|pick the approach" +
  '|route to the (?:named )?sub-skill)';
const ROUTER_STEP_RE = new RegExp(ROUTER_STEP, 'i');
const CHECKLIST_STATUS = /\[(?:done|in[ _]progress|pending|completed)\]/i;
const NUMBERED_LINE = /^[ \t]*\d+[.)][ \t]/;

// Typographic apostrophes to ASCII, line breaks (CRLF, CR, U+2028/9) to \n,
// and every other whitespace character to a plain space.
function normalise(text) {
  return String(text)
    .replace(/\u2019/g, "'")
    .replace(/\r\n/g, '\n')
    .replace(LINE_BREAK, '\n')
    .replace(SPACE, ' ');
}

// Lines that qualify AND name a router step, checked line by line (linear).
function routerStepLines(text, qualifies) {
  return text.split('\n').filter((line) => qualifies.test(line) && ROUTER_STEP_RE.test(line));
}

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

// Top-level {...} spans, ignoring braces inside quoted strings.
function braceSpans(text) {
  const spans = [];
  let depth = 0;
  let start = 0;
  let quote = '';
  let escaped = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === quote) quote = '';
    } else if ((ch === '"' || ch === "'") && depth) {
      quote = ch;
    } else if (ch === '{') {
      if (depth === 0) start = i;
      depth += 1;
    } else if (ch === '}' && depth) {
      depth -= 1;
      if (depth === 0) spans.push(text.slice(start, i + 1));
    }
  }
  return spans;
}

// The skill handoff must sit inside the next_action object itself.
function nextActionHasSkill(span) {
  for (const m of span.matchAll(NEXT_ACTION)) {
    const inner = braceSpans(span.slice(m.index + m[0].length));
    if (inner.length && SKILL_KEY.test(inner[0])) return true;
  }
  return false;
}

function blankStringValues(span) {
  return span.replace(QUOTED, (match, _q, offset) =>
    KEY_FOLLOWS.test(span.slice(offset + match.length)) ? match : '""',
  );
}

function hasRoutingPayload(text) {
  return braceSpans(text)
    .map(blankStringValues)
    .some(
      (keys) =>
        PAYLOAD_KEYS.every((key) => new RegExp(`\\b${key}["']?\\s*:`).test(keys)) &&
        nextActionHasSkill(keys),
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
    `(?<!\\w)(?:classification|approach)${DECOR}{0,4}:${DECOR}{0,6}` +
      `(?:${alternatives}|n/a)[\`*"']*(?=[ \\t]*$|[.,;:)]|\\s+[-\\u2013\\u2014]\\s)`,
    'im',
  );
  return label.test(text);
}

const CHECKS = {
  payload_json: hasRoutingPayload,
  taxonomy_label: hasTaxonomyLabel,
  route_announcement: (s) => ROUTE_ANNOUNCEMENT.test(s),
  checklist_status: (s) => routerStepLines(s, CHECKLIST_STATUS).length > 0,
  router_checklist: (s) => routerStepLines(s, NUMBERED_LINE).length >= 2,
};

function findRoutingLeaks(text) {
  const s = normalise(text);
  return Object.keys(CHECKS).filter((family) => CHECKS[family](s));
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
