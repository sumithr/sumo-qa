// Faithfully reconstruct the llm-rubric judge prompt promptfoo sends, using
// promptfoo's OWN bundled nunjucks (autoescape:false) and its exact 2-pass +
// processContextForTemplating logic. This is what makes the re-grade an
// apples-to-apples comparison with the stored cloud verdict.
//
//   node render.js <raw_json_in> <prompt_out>
//
// raw_json_in: {template, raw_rubric, vars, output}
// Prints "residual: <n>" — number of unrendered nunjucks tokens (should be 0).
const fs = require('fs');
const path = require('path');

// repo root is 4 levels up: validate-local-judge -> promptfoo -> evals -> tests -> repo
const REPO = path.resolve(__dirname, '..', '..', '..', '..');
const nunjucks = require(path.join(REPO, 'node_modules', 'nunjucks'));
nunjucks.configure({ autoescape: false });

// Exact copy of promptfoo's processContextForTemplating (enableObjectAccess=false):
// arrays/objects in the template context are JSON-stringified.
function processContextForTemplating(context) {
  return Object.fromEntries(Object.entries(context).map(([k, v]) => {
    if (v && typeof v === 'object') {
      if (Array.isArray(v)) return [k, v.map((i) => (i && typeof i === 'object') ? JSON.stringify(i) : i)];
      return [k, JSON.stringify(v)];
    }
    return [k, v];
  }));
}

const [, , rawIn, promptOut] = process.argv;
const raw = JSON.parse(fs.readFileSync(rawIn, 'utf8'));

// Pass 1: render the rubric (assertion.value) against vars — arrays intact so
// any {% for %} loop expands.
const rubricRendered = nunjucks.renderString(raw.raw_rubric || '', raw.vars || {});

// Pass 2: render rubricPrompt template with processed {output, rubric, ...vars}.
const ctx = processContextForTemplating(Object.assign({}, raw.vars || {}, {
  output: raw.output,
  rubric: rubricRendered,
}));
const finalPrompt = nunjucks.renderString(raw.template, ctx);

fs.writeFileSync(promptOut, finalPrompt);
const residual = (finalPrompt.match(/{{[^}]*}}|{%[^%]*%}/g) || []).length;
console.log(`residual: ${residual}`);
