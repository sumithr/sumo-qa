// Assembles the sumo-qa-reviewing-before-merge skill body for a promptfoo
// seed from the compact root SKILL.md plus ONLY the lazy modules that seed
// declares (issue #451). Mirrors what a host does at runtime: it loads the
// root, reads the routing table, then fetches each required module through
// `sumo_qa_load_skill_context(mode="module")`. Nothing here is generated or
// mirrored — every byte comes from the canonical files under
// `skills/sumo-qa-reviewing-before-merge/`.
//
// Wired as a promptfoo dynamic var:
//   defaultTest.vars.skill_content: file://fixtures/assemble-review-skill.js
//   defaultTest.vars.review_modules: [coverage-ledger, discovery-probes]
// A seed can override `review_modules` in its own `vars:` to load a different
// module set. `review_modules` MUST be declared (an empty list is a valid,
// explicit "root only"); an undeclared or unknown module id fails the eval
// loudly rather than silently grading the wrong skill slice — a seed that
// forgot its declaration would otherwise pass or fail for the wrong reason.
//
// `review_modules` is a LIST var, so every config that declares it MUST also
// set `defaultTest.options.disableVarExpansion: true`. Without it promptfoo
// expands an array-valued var into one test case per element, so this
// function would receive a bare string (and throw) or grade a one-module
// slice per row. tests/test_review_skill_modules.py fails a config that
// declares `review_modules` without that option.
//
// Contract (kept in lockstep with tests/test_review_skill_modules.py):
//   * root = skills/sumo-qa-reviewing-before-merge/SKILL.md, verbatim;
//   * each module = skills/sumo-qa-reviewing-before-merge/modules/<id>.md,
//     verbatim, in the declared order;
//   * modules are appended after the root under one "LOADED MODULES" banner so
//     the candidate sees them as loaded skill text, not as ground truth.
const fs = require('fs');
const path = require('path');

// fixtures/ -> promptfoo/ -> evals/ -> tests/ -> repo root.
const SKILL_DIR = path.resolve(
  __dirname, '..', '..', '..', '..', 'skills', 'sumo-qa-reviewing-before-merge',
);
const MODULE_ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

// Normalise CRLF to LF so the assembled prompt is byte-identical across
// checkouts (a Windows autocrlf checkout must grade the same skill text).
function readText(file) {
  return fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
}

// `skillDir` defaults to the shipped skill; tests pass a temp skill dir to
// exercise the same assembly path over synthetic (e.g. CRLF) inputs.
function readModule(id, skillDir = SKILL_DIR) {
  if (typeof id !== 'string' || !MODULE_ID_RE.test(id)) {
    throw new Error(`assemble-review-skill: illegal module id ${JSON.stringify(id)}`);
  }
  const modulesDir = path.join(skillDir, 'modules');
  const file = path.join(modulesDir, `${id}.md`);
  if (!fs.existsSync(file)) {
    const available = fs.existsSync(modulesDir)
      ? fs.readdirSync(modulesDir).filter((f) => f.endsWith('.md')).map((f) => f.slice(0, -3))
      : [];
    throw new Error(
      `assemble-review-skill: unknown module id ${JSON.stringify(id)}; available: ${available.join(', ')}`,
    );
  }
  return readText(file);
}

function assemble(moduleIds, skillDir = SKILL_DIR) {
  const root = readText(path.join(skillDir, 'SKILL.md'));
  if (!moduleIds.length) return root;
  const parts = moduleIds.map((id) => `--- MODULE ${id} ---\n${readModule(id, skillDir).trimEnd()}\n--- END MODULE ${id} ---`);
  return `${root.trimEnd()}\n\n--- LOADED MODULES (fetched via sumo_qa_load_skill_context mode="module") ---\n\n${parts.join('\n\n')}\n`;
}

module.exports = function assembleReviewSkill(varName, prompt, otherVars) {
  const declared = otherVars ? otherVars.review_modules : undefined;
  if (!Array.isArray(declared)) {
    throw new Error(
      `assemble-review-skill: var ${JSON.stringify(varName)} needs a \`review_modules\` list ` +
      '(declare it in defaultTest.vars or the seed vars; [] means root only).',
    );
  }
  return { output: assemble(declared) };
};

module.exports.assemble = assemble;
module.exports.readModule = readModule;
module.exports.readText = readText;
