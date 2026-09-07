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
const ROOT_PATH = path.join(SKILL_DIR, 'SKILL.md');
const MODULES_DIR = path.join(SKILL_DIR, 'modules');
const MODULE_ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function readModule(id) {
  if (typeof id !== 'string' || !MODULE_ID_RE.test(id)) {
    throw new Error(`assemble-review-skill: illegal module id ${JSON.stringify(id)}`);
  }
  const file = path.join(MODULES_DIR, `${id}.md`);
  if (!fs.existsSync(file)) {
    const available = fs.existsSync(MODULES_DIR)
      ? fs.readdirSync(MODULES_DIR).filter((f) => f.endsWith('.md')).map((f) => f.slice(0, -3))
      : [];
    throw new Error(
      `assemble-review-skill: unknown module id ${JSON.stringify(id)}; available: ${available.join(', ')}`,
    );
  }
  return fs.readFileSync(file, 'utf8');
}

function assemble(moduleIds) {
  const root = fs.readFileSync(ROOT_PATH, 'utf8');
  if (!moduleIds.length) return root;
  const parts = moduleIds.map((id) => `--- MODULE ${id} ---\n${readModule(id).trimEnd()}\n--- END MODULE ${id} ---`);
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
