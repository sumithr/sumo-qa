// Deterministic routing-state leak assertion for
// skill-deciding-approach-user-facing.yaml (issue #248), which grades both
// routing hops: the entry router and the approach router are internal, so their
// routing payload, taxonomy labels, route announcement and checklist
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
//   * taxonomy_label     a bare `Classification:` / `Approach:` line whose
//                        value is exactly a catalogue entry name (read from
//                        knowledge/) or n/a, optionally followed by a second
//                        label pair (after . , ; a space, or glued);
//   * route_announcement "Picking the QA approach", "Routing this QA intent",
//                        "Routing/Routed [this|you|it] to [the] sumo-qa-...",
//                        or a first-person "I'm routing you to" / "I'll route
//                        this to sumo-qa-...";
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
// A single quote between word characters is an apostrophe, never a delimiter.
const WORD = 'A-Za-z0-9_';
const QUOTED = new RegExp(
  '"(?:\\\\[\\s\\S]|[^"\\\\])*"' +
    `|(?<![${WORD}])'(?:\\\\[\\s\\S]|[^'\\\\]|(?<=[${WORD}])'(?=[${WORD}]))*` +
    `(?:(?<![${WORD}])'|'(?![${WORD}]))`,
  'g',
);
const WORD_CHAR = new RegExp(`[${WORD}]`);
const isWord = (text, i) => i >= 0 && i < text.length && WORD_CHAR.test(text[i]);
const KEY_FOLLOWS = /^\s*:/;
// One explicit character set for both engines (their \s differ).
const LINE_BREAK = /[\r\u2028\u2029]/g;
const SPACE = /[\t\v\f \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u202f\u205f\u3000\ufeff]/g;
// High-confidence router voice only; paraphrased handoffs are the judge's job.
// A skill is named sumo-qa-* (hyphens); sumo_qa_* tool names are where
// downstream skills legitimately send data.
const TO_SKILL =
  '[:\\s*_`"\'\\[(]{0,8}(?:the\\s+[*_`"\'\\[(]{0,8})?(?:sumo-qa-|using[-_]sumo[-_]qa)';
const ROUTE_ANNOUNCEMENT = new RegExp(
  'picking the qa approach' +
    '|\\brouting this qa intent\\b' +
    '|\\b(?:routing|routed)(?:\\s+(?:this|you|it))?\\s+to' +
    TO_SKILL +
    "|\\b(?:i'm|i am|i'll|i will)\\s+(?:now\\s+)?(?:rout(?:e|ing)|handing)\\s+" +
    '(?:you\\s+to\\b|this\\s+to' +
    TO_SKILL +
    ')',
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

// Typographic single and double quotes to ASCII, line breaks (CRLF, CR,
// U+2028/9) to \n, and every other whitespace character to a plain space.
function normalise(text) {
  return String(text)
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201c\u201d]/g, '"')
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

// Every balanced {...} as [open, close, depth], ignoring braces in quoted
// strings (a single quote between word characters is an apostrophe).
function bracePairs(text) {
  const pairs = [];
  const stack = [];
  let quote = '';
  let escaped = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === quote && !(ch === "'" && isWord(text, i - 1) && isWord(text, i + 1)))
        quote = '';
    } else if (stack.length && (ch === '"' || (ch === "'" && !isWord(text, i - 1)))) {
      quote = ch;
    } else if (ch === '{') {
      stack.push(i);
    } else if (ch === '}' && stack.length) {
      const open = stack.pop();
      pairs.push([open, i, stack.length]);
    }
  }
  return pairs;
}

// Top-level {...} spans; an unbalanced brace yields no span.
function braceSpans(text) {
  return bracePairs(text)
    .filter(([, , depth]) => depth === 0)
    .map(([open, close]) => text.slice(open, close + 1));
}

// The skill handoff must sit inside the next_action object itself. One brace
// pass maps each { to its }, so every next_action is a lookup, not a rescan.
const SKILL_KEY_ALL = new RegExp(SKILL_KEY.source, 'g');
function nextActionHasSkill(span) {
  const closes = new Map(bracePairs(span).map(([open, close]) => [open, close]));
  const skills = [...span.matchAll(SKILL_KEY_ALL)].map((m) => m.index);
  for (const m of span.matchAll(NEXT_ACTION)) {
    const open = m.index + m[0].length;
    const close = closes.get(open);
    if (close === undefined) continue;
    let lo = 0;
    let hi = skills.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (skills[mid] < open) lo = mid + 1;
      else hi = mid;
    }
    if (lo < skills.length && skills[lo] < close) return true;
  }
  return false;
}

function blankStringValues(span) {
  return span.replace(QUOTED, (match, offset) =>
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

const labelCache = new Map();

// A bare label line: label and catalogue value (or n/a) are the whole line,
// give or take a list or heading prefix, emphasis, quotes, a clause end and
// the other label with its own catalogue value.
function labelRegExp(names) {
  const key = names.join('|');
  if (!labelCache.has(key)) {
    const alternatives = names.map(escapeRegExp).join('|');
    const decoChars = escapeRegExp('*_`"\'');
    const deco = `[${decoChars}]*`;
    const barePair =
      `(?:classification|approach)${deco}[ \\t]*:[ \\t${decoChars}]*` +
      `(?:${alternatives}|n/a)${deco}`;
    const pair = `${deco}${barePair}`;
    labelCache.set(
      key,
      new RegExp(
        // List or heading prefixes, each followed by whitespace.
        `^[ \\t]*(?:(?:[-+*]|>+|#{1,6}|\\d{1,3}[.)])[ \\t]+)*${pair}` +
          `(?:(?:(?:[ \\t]*[.,;][ \\t]*|[ \\t]+)${pair}|${barePair})(?:[ \\t]*[.,;])?` +
          '|[ \\t]*[.,;])?[ \\t]*$',
        'im',
      ),
    );
  }
  return labelCache.get(key);
}

function hasTaxonomyLabel(text) {
  const names = catalogueNames().sort((a, b) => b.length - a.length);
  return names.length > 0 && labelRegExp(names).test(text);
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
module.exports.blankStringValues = blankStringValues;
