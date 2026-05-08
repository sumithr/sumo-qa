# QA principles — ISTQB Foundation, Advanced, ISO 25010

## ISTQB Foundation — the seven testing principles

1. Testing shows the presence of defects, not their absence.
2. Exhaustive testing is impossible; use risk and prioritisation.
3. Early testing saves time and money — shift left.
4. Defects cluster — concentrate effort where defect history is dense.
5. Pesticide paradox — the same tests stop finding defects; refresh
   assertions and add new techniques.
6. Testing is context-dependent — safety-critical, regulated, web,
   mobile, AI all warrant different mixes.
7. Absence-of-errors fallacy — validate fitness for use, not just
   code-level correctness.

## ISTQB Advanced

- **Test Manager:** risk-based testing (likelihood x impact), shaping
  coverage to where risk is highest, accepting low-risk areas with
  thinner tests, entry/exit criteria, test estimation.
- **Test Analyst:** black-box / experience-based technique mastery,
  tester independence, defect taxonomy.
- **Technical Test Analyst:** white-box / structural coverage, code
  analysis, performance / security / reliability test design.

## ISO/IEC 25010 quality characteristics

- functional suitability
- performance efficiency
- compatibility
- usability
- reliability
- security
- maintainability
- portability

Pick the characteristics the change actually threatens; do not list them all.

## Test levels and the pyramid

unit -> component integration -> system -> system integration -> acceptance.
Shape the mix to the risk and the change.

## Test types (orthogonal to levels)

- functional
- non-functional (performance, security, accessibility, reliability,
  compatibility, usability)
- white-box / structural
- change-related (confirmation + regression)

## Static testing

Review (informal walkthrough, technical review, inspection) and static
analysis (linters, type checkers, SAST). Often the cheapest defect removal.
A code review or a stricter linter rule can be the right answer instead of
"add more tests".

## Senior-QA disciplines

- Decide the SHAPE of the work first (single change vs repo-wide strategy;
  bug vs greenfield vs refactor vs strengthen-existing-tests vs spike vs
  config tweak vs docs). Wrong shape = wrong-shaped tests.
- Reach for the smallest useful test set that gives release confidence.
  Avoid generic advice; tie every recommendation to a specific risk.
- When the user asks about strategy / audit / pyramid / rollout, that is a
  strategy ask, not a single change. Don't force per-change output.
- When the user describes work that doesn't change production code (mutation-
  testing follow-up, raise-coverage, kill surviving mutants, tighten weak
  assertions), do NOT scaffold tests against new behaviour. Strengthen
  existing tests. Suppress equivalent mutants in tool config rather than
  chasing them.
- Critical paths (auth, authorization, payment, billing, encryption, rate
  limiting, anything where a regression hits money, security, or customer
  trust) warrant tighter coverage and at least one boundary test per rule.
- Honest TDD: red phase first. Tests that fail BEFORE production code is
  written. Never bless a change as merge-ready without evidence.
- Static testing counts. A code review or a stricter linter rule can be
  the right answer instead of "add more tests".
