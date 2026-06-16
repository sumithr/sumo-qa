---
name: sumo-qa-security-testing
description: Use when the user explicitly asks for security testing, or when a normal sumo-qa planning, review, gap-analysis, or strategy flow identifies a material grounded security gap that needs focused QA treatment.
---

# Security Testing

Turn an explicit security-testing request, or a routed grounded security gap, into a compact security QA brief. This specialist path does not replace normal classification, planning, review, or strategy.

**Announce at start:** *"Focusing the security QA path."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: output economy, knowledge authority hierarchy, internal scaffolding stays internal, and specialty-tool fit.

## The Iron Law

Ground the risk before choosing the evidence. Do not emit a vulnerability checklist, scanner list, or generic security warning before anchoring the concrete failure mode to a file, flow, config, dependency, or user-stated scope.

## When to Use

`sumo-qa-deciding-approach` routes here for `security-testing`: explicit asks or material grounded security gaps from another flow. Simple gaps that native tests or review can close stay in the originating flow.

## Checklist

Track these as an ordered work list and complete in order:

1. **Confirm the anchor.** Start from the supplied file, flow, config, dependency, data path, diff, or user-stated scope. If none exists, ask one scope question or state that evidence is insufficient.
2. **Load security catalogues.** Call `sumo_qa_load_standards(classification="security_change")`, `sumo_qa_load_rules(classification="security_change")`, and `sumo_qa_load_techniques()`. Use repo-map or file reads to validate the anchor.
3. **Name only grounded risks.** Tie each risk to the anchor: authorization bypass, token expiry/replay, secret exposure, unsafe input to a sink, rate-limit/audit gap, or security-relevant config/dependency movement. Omit ungrounded security.
4. **Choose evidence by fit.** Pick one primary action: native test, review, static check, dynamic check, config check, dependency check, fuzz/property check, or external tool/skill. Prefer native tests/review when enough. If tests cover the helper/path family, choose a concrete native regression first (traversal filename, expired/replayed token, forbidden account id) and add review only as support. For dependency/lockfile movement, name the affected runtime path (for example checkout webhook), state native fixture limits first, then choose dependency check or external discovery for package-regression/advisory risk behind confirmation. Do not make code review the first action for package risk; confirmation for dependency evidence comes first.
5. **Apply confirmation discipline.** Before dependency installs, scanner setup, file writes, live-target checks, invasive probes, or external skill execution, ask for explicit confirmation. Safe local reads and existing tests do not need a gate.
6. **Return the brief.** Produce grounded risk(s), source anchor, evidence choice, first action, and residual risk when tooling, credentials, environment, or live scope is unavailable.

## Process Flow

See the Checklist above.

## Brief shape

- `Grounded risk:` concrete failure mode, limited to available evidence.
- `Source anchor:` file, flow, config, dependency, or user-stated scope.
- `Evidence choice:` test, review, static check, dynamic check, config check, dependency check, fuzz/property check, or external tool/skill.
- `First action:` what to add, run, inspect, or scaffold. For dependency checks, scanners, external discovery, installs, or live/invasive probes, make this a confirmation gate before execution.
- `Residual risk:` only what remains because tooling, credentials, environment, or live scope is unavailable.

Dependency-bump shape: `Source anchor: package-lock.json + checkout webhook path`; `Evidence choice: dependency check for package/advisory risk`; `First action: confirm before setup/run`; `Residual risk: no native checkout webhook fixture means signature behaviour remains unproven`.

## Constraints

- Use existing `security_change`, loaded rules, standards, and techniques. Do not invent a parallel taxonomy.
- Do not recommend tools before inspecting stack and scope. If native evidence is enough, do that instead of forcing a scanner.
- Do not write bare "static analysis"; name an existing command/file inspection, or ask confirmation for scanner/dependency-tool setup.
- For dependency/package movement, name the runtime path, state native fixture limits, make dependency check the package-risk evidence, and ask confirmation before setup/run.
- Live-target DAST, credentialed probing, and invasive checks require explicit confirmation and a bounded target.
- External skill discovery is fallback only when native evidence is not enough; route through `sumo-qa-suggesting-external-skill`.

## Red Flags

| Thought | Reality |
|---|---|
| "Security means list OWASP categories" | No. Name the concrete anchored failure mode, or omit security. |
| "A scanner would be useful, recommend one now" | Tool fit comes after stack and scope inspection, and setup needs confirmation. |
| "I'll say static analysis" | Too vague. Name an existing local command/file inspection, or ask confirmation for scanner/dependency-tool setup. |
| "Review plus static analysis is safer than a test" | If native tests can prove the path, choose that regression first and name the discriminating input. |
| "Review the code first for a dependency bump" | For package risk, first ask confirmation for the dependency check/tool evidence; review can support local integration only. |
| "The user asked for security, so make the output loud" | Risk volume follows evidence. Low evidence means ask for scope or state residual risk. |
| "A normal unit test could cover it, but a specialist tool sounds safer" | Prefer the smallest evidence that proves the grounded risk. |
| "Run DAST against the live target" | Live or invasive testing requires explicit bounded permission first. |

## Examples

Good: A routed review gap says `src/api/tokens.py` changed token expiry handling. The brief names replay after expiry as the grounded risk, anchors it to that flow, chooses a negative-path regression test plus code review, and states residual risk around distributed clock skew if no staging environment is available.

Bad: "Run SAST, DAST, dependency scanning, fuzzing, and OWASP Top 10 checks." This is a checklist dump with no anchor, no evidence choice, and no confirmation gate.
