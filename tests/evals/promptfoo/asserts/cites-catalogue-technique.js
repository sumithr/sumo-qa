// Deterministic grounding assertion for the implementing-with-tdd evals: did
// the candidate cite a real test-design technique from the catalogue?
//
// The set of accepted techniques is DERIVED from `knowledge/techniques.md`
// (its level-3 `###` headings, the single source of truth), never a hardcoded
// allowlist. Before issue #350 each eval hardcoded six technique substrings, so
// a candidate citing any other VALID catalogue technique (e.g. `error guessing`,
// `build artifact contents verification`) failed this axis even though the
// llm-rubric grounding axis passed, silently pressuring scenario authors toward
// the six. Sourcing the names from the catalogue means adding a technique to
// techniques.md widens what every eval accepts, with no eval edit required.
//
// Level-2 `##` headings are CATEGORIES (Black-box, White-box / structural, ...),
// not techniques, so they are excluded; level 1 is the catalogue title. This
// mirrors how `sumo_qa_load_techniques`'s per-entry indexer treats the file.
//
// Shared by skill-implementing-with-tdd.yaml, .ab.yaml, and -retrospective.yaml
// via `value: file://asserts/cites-catalogue-technique.js`.
const fs = require('fs');
const path = require('path');

// asserts/ -> promptfoo/ -> evals/ -> tests/ -> repo root.
const TECHNIQUES_MD = path.resolve(
  __dirname, '..', '..', '..', '..', 'knowledge', 'techniques.md',
);

// Extract the catalogue's technique names: the level-3 (`###`) ATX headings,
// skipping any that fall inside a fenced code block. techniques.md currently
// has no fences; the guard keeps the parse correct if a fenced example is ever
// added.
function catalogueTechniqueNames(markdown) {
  const names = [];
  let fence = null; // { char, len } while inside a fenced code block, else null
  // Split on \r?\n so a CRLF checkout (Windows) leaves no trailing \r that
  // would defeat the end-anchored closing-fence match below; this mirrors the
  // catalogue indexer's str.splitlines() in src/sumo_qa/knowledge_loaders.py.
  for (const line of markdown.split(/\r?\n/)) {
    if (fence === null) {
      // An opening fence is a run of >=3 backticks/tildes (indented <=3),
      // optionally followed by an info string; record its char and length.
      const open = line.match(/^ {0,3}(`{3,}|~{3,})/);
      if (open) {
        fence = { char: open[1][0], len: open[1].length };
        continue;
      }
      const heading = line.match(/^###\s+(.*\S)\s*$/);
      if (heading) names.push(heading[1].trim());
    } else {
      // A closing fence must use the SAME character, be at least as long as the
      // opening run, and carry no info string (CommonMark). A shorter or
      // different-character run inside the block (e.g. a 3-backtick example
      // nested in a 4-backtick outer fence) does NOT close it, so `###` lines
      // in a fenced example are never mistaken for catalogue techniques. The
      // remainder is captured and trimmed (rather than a `[ \t]*` class) so any
      // whitespace-only tail closes the fence, matching the python indexer's
      // `not remainder.strip()` in src/sumo_qa/knowledge_loaders.py.
      const close = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
      if (
        close &&
        close[1][0] === fence.char &&
        close[1].length >= fence.len &&
        close[2].trim() === ''
      ) {
        fence = null;
      }
    }
  }
  return names;
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Built once per process; the catalogue does not change mid-run.
function buildTechniqueRegex() {
  const names = catalogueTechniqueNames(fs.readFileSync(TECHNIQUES_MD, 'utf8'));
  if (names.length === 0) {
    throw new Error(
      `no technique headings parsed from ${TECHNIQUES_MD} (catalogue path or format drift)`,
    );
  }
  // Longest-first so the alternation reports the most specific match in `reason`.
  const alternation = names
    .slice()
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join('|');
  return { regex: new RegExp(alternation, 'i'), count: names.length };
}

let cached;

module.exports = function citesCatalogueTechnique(output) {
  if (!cached) cached = buildTechniqueRegex();
  const matched = String(output == null ? '' : output).match(cached.regex);
  if (matched) {
    return { pass: true, score: 1, reason: `cites catalogue technique "${matched[0]}"` };
  }
  return {
    pass: false,
    score: 0,
    reason: `no catalogue technique cited; expected a verbatim heading from techniques.md (${cached.count} techniques)`,
  };
};

// Exposed for offline verification (no JS test runner in this repo).
module.exports.catalogueTechniqueNames = catalogueTechniqueNames;
module.exports.buildTechniqueRegex = buildTechniqueRegex;
