# Test design techniques

Pick one technique per named risk. The catalogue below is authoritative —
do not invent techniques not in this list. If a risk needs something not
catalogued, flag it as a gap rather than confabulating.

## Black-box

### equivalence partitioning
Group inputs into classes that share behaviour; pick one representative
per class. Use when the input space is large but partitions clearly.

### boundary value analysis
Test the values immediately above, at, and below boundaries (off-by-one,
limits, capacity thresholds). Defects cluster at boundaries.

### decision tables
Enumerate every combination of input conditions and the expected output.
Use when business rules are conjunctions of multiple conditions.

### state transition testing
Model the system as a finite state machine; test every legal transition
and a sample of illegal ones. Use for stateful components.

### pairwise / orthogonal arrays
When a feature has many parameters with many values each, test every pair
of value combinations rather than the full Cartesian product.

### classification trees
Hierarchical refinement of equivalence partitions, useful when partitions
have sub-partitions.

### use case testing
Walk through end-to-end user scenarios. Catches integration defects unit
tests miss.

## White-box / structural

### statement coverage
Every statement executes at least once.

### branch coverage
Every branch (if/else, switch arm, loop entry/exit) is exercised both ways.

### decision coverage
Every boolean decision evaluates to both true and false.

### MC-DC (modified condition / decision coverage)
Each condition independently affects the decision outcome. Required for
safety-critical software.

### data-flow coverage
Every definition-use pair is exercised.

## Experience-based

### error guessing
Senior-QA judgment on where defects historically appear in similar systems.

### exploratory testing charters
Time-boxed, mission-driven sessions documenting findings.

### checklist-based testing
Reusable list of common pitfalls (e.g. OWASP Top 10).

## Static

### review (walkthrough / technical review / inspection)
Code review with varying formality. Cheapest defect removal.

### static analysis
Linters, type checkers, SAST scanners. Catches whole classes of defects
without execution.

## Property-based

### property-based testing
Generate inputs satisfying invariants and check the output preserves the
invariant. Tools: Hypothesis (Python), jqwik (JVM), fast-check (JS).
Fits pure-function refactors and algorithms.

## Mutation

### mutation testing
Mutate the production code, run the test suite, kill the mutants. Surfaces
weak assertions. Tools: Pitest (JVM), Stryker (JS / .NET), mutmut (Python).
Fits strengthen-test-coverage approach.
