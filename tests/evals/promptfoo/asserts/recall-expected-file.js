// File half of the review-recall score (issue #754): a recall case counts as
// caught only when the review names the file that carries the defect
// (`metadata.expected_file`) AND the llm-rubric judge matches the defect.
// Matching on file plus defect, not wording, keeps a review that finds the bug
// in its own words a catch, and a review that names the right symptom against
// the wrong file a miss.
//
// The file may be named by its repo path, by a trailing part of that path
// (`sumo_qa/server.py`) or by its bare file name, with or without a `:line`
// suffix or markdown around it. A path that names a same-named file in another
// directory (`docs/README.md` when the defect is in the root `README.md`) is a
// different file and does not count, nor does a longer name that merely contains
// it (`my-run-eval.sh`, `run-eval.shim`). A case with no `expected_file` (a
// negative control) is not checked here.
//
// Loaded by skill-reviewing-before-merge-recall.yaml via
// `value: file://asserts/recall-expected-file.js`.

// Path-like tokens: segments of name characters joined by `/`.
const PATH_TOKEN = /[\w.-]+(?:\/[\w.-]+)*/g;

function names(output, expected) {
  const base = expected.split('/').pop();
  for (const match of output.matchAll(PATH_TOKEN)) {
    const token = match[0].replace(/^\.\//, '').replace(/\.+$/, '');
    if (token.split('/').pop() !== base) continue;
    // `a/<path>` and `b/<path>` are the path as a `diff --git` header quotes it.
    for (const path of [token, token.replace(/^[ab]\//, '')]) {
      if (path === expected || expected.endsWith(`/${path}`)) return true;
    }
  }
  return false;
}

module.exports = function recallExpectedFile(output, context) {
  const metadata = (context && context.test && context.test.metadata) || {};
  const expected = metadata.expected_file;
  if (!expected) {
    return { pass: true, score: 1, reason: 'no expected_file on this case; file anchor not checked' };
  }
  const text = String(output || '');
  const base = expected.split('/').pop();
  if (names(text, expected)) {
    return { pass: true, score: 1, reason: `review names the defect file ${expected}` };
  }
  return {
    pass: false,
    score: 0,
    reason: `review never names the defect file ${expected} (by path or as ${base}); a finding elsewhere is not this catch`,
  };
};
