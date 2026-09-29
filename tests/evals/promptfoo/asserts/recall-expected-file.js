// File half of the review-recall score (issue #754): a recall case counts as
// caught only when the review names the file that carries the defect
// (`metadata.expected_file`) AND the llm-rubric judge matches the defect.
// Matching on file plus defect, not wording, keeps a review that finds the bug
// in its own words a catch, and a review that names the right symptom against
// the wrong file a miss.
//
// The file may be named by its repo path or by its bare file name, with or
// without a `:line` suffix or markdown around it. A longer name that merely
// contains it (`my-run-eval.sh`, `run-eval.shim`) does not count. A case with no
// `expected_file` (a negative control) is not checked here.
//
// Loaded by skill-reviewing-before-merge-recall.yaml via
// `value: file://asserts/recall-expected-file.js`.

function escape(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// A name character on either side means the match is part of a longer name.
function named(output, name) {
  return new RegExp(`(^|[^\\w.-])${escape(name)}(?![\\w-]|\\.\\w)`).test(output);
}

module.exports = function recallExpectedFile(output, context) {
  const metadata = (context && context.test && context.test.metadata) || {};
  const expected = metadata.expected_file;
  if (!expected) {
    return { pass: true, score: 1, reason: 'no expected_file on this case; file anchor not checked' };
  }
  const text = String(output || '');
  const base = expected.split('/').pop();
  if (named(text, expected) || named(text, base)) {
    return { pass: true, score: 1, reason: `review names the defect file ${expected}` };
  }
  return {
    pass: false,
    score: 0,
    reason: `review never names the defect file ${expected} (by path or as ${base}); a finding elsewhere is not this catch`,
  };
};
