---
name: sumo-qa-security-testing
description: Use when explicit security testing or a grounded security gap needs deeper evidence selection.
---

# Security Testing

Security testing here means turning an already grounded security concern into the smallest evidence that can prove the risk is covered. It is a routed specialist path after normal QA classification, not a replacement for `sumo-qa-deciding-approach`.

**Announce at start:** *"Focusing the security test evidence."*

## Output discipline (mandatory)

Inherits the global discipline from `using-sumo-qa`: grounded risks only, no internal taxonomy labels in user output, no vulnerability checklist dump, no vendor/tool-name dump, and no external setup without confirmation.

## Output economy (mandatory)

Spend output tokens on the security brief: risk, anchor, evidence choice, first action, and residual risk.

## The Iron Law

Grounded risk first, tool second. Do not recommend a scanner, external skill, live probe, or dependency install until the concrete security failure mode, source anchor, and native evidence fit have been checked.

## When to Use

Use after `sumo-qa-deciding-approach` routes an explicit security-testing request here, or after another sumo-qa workflow has named a material security gap that needs deeper treatment than a normal regression test / review line. Do not use for low-evidence prompts; ask for the missing scope or stop short.

## Checklist

1. Confirm the source anchor: file, flow, config, dependency, data path, or explicit user-stated scope. If none exists, ask one scope question; stop. No hypothetical risks/actions.
2. Load `sumo_qa_load_standards(classification="security_change")`, `sumo_qa_load_rules(classification="security_change")`, and `sumo_qa_load_techniques()`. Use repo-map or file reads when available to verify the path.
3. State the grounded failure mode in concrete terms: who/what can do something they should not, which token/secret/input/config can fail, or which security control can regress. For account-recovery or lookup flows, include account enumeration when the request path can reveal user existence.
4. Choose the smallest evidence type that fits: native test, review, static check, dynamic check, config check, dependency check, fuzz/property check, or external tool/skill.
5. Name the first concrete action: the test to add, file/config to inspect, command to run, local safe check to perform, or external-skill discovery to request.
6. Separate safe local regression work from invasive or live-target testing. Get confirmation before dependency installs, scanner setup, external skill execution, or live probing.
7. Return a compact security QA brief with residual risk when specialist tooling, credentials, environment, or live target scope is unavailable.

## Process Flow

See the Checklist above; each step narrows from anchored risk to evidence fit.

## Security QA Brief Shape

- **Grounded risk:** the specific security failure mode, limited to available evidence.
- **Source anchor:** file, flow, config, dependency, or user-stated scope.
- **Evidence choice:** one of test / review / static check / dynamic check / config check / dependency check / fuzz-property check / external tool-skill.
- **First action:** what to add, run, inspect, or request next.
- **Residual risk:** what remains unproven because environment, credentials, tooling, or live target scope is absent.

## Evidence-Fit Guide

| Evidence | Use when | First action shape |
|---|---|---|
| Native test | The failure path is reachable in unit/integration/API tests. | Add the negative path: non-owner denied, expired token rejected, tampered input fails closed, known/unknown account responses match. |
| Review | The risk is policy/design/control logic and cannot be executed locally yet. | Inspect the guard, data flow, error handling, or audit path against the loaded rule. |
| Static check | The stack has a local analyser/linter or the issue is source/sink shaped. | Run the repo-pinned check or propose one only after stack evidence exists. |
| Dynamic check | A running local service can safely exercise the path. | Hit the local target with bounded negative cases; no live target without confirmation. |
| Config check | Security depends on flags, headers, IAM, CORS, TLS, secrets, or deployment config. | Inspect the config plus the consuming runtime path. |
| Dependency check | The change adds/upgrades security-sensitive packages or lockfiles. | Run the repo's dependency audit command or inspect advisories for the named package. |
| Fuzz/property check | Parser/token/claim handling has broad input space. | Add a bounded property or fuzz seed for malformed, oversized, tampered, or replayed inputs. |
| External tool/skill | Native evidence cannot cover the risk and stack/scope point to specialist tooling. | Route through `sumo-qa-suggesting-external-skill`; confirm before install/setup/execution. |

## Red Flags

| Thought | Reality |
|---|---|
| "Security means list OWASP categories." | No. Name the concrete failure mode the repo or user scope exposes. |
| "Use ZAP/Burp/Snyk because this is security." | Tool names are earned by stack + risk evidence; otherwise choose native tests or review. |
| "The prompt says security testing, so broad live DAST is fine." | Live or invasive testing needs explicit scope and confirmation. Prefer safe local checks first. |
| "No files or flow are visible, but I'll infer likely vulnerabilities." | Ask one scope question or state insufficient evidence. Ungrounded claims fail the contract. |
| "A scanner found nothing, so risk is covered." | A specific risk is covered only by evidence that exercises or checks that path. |

## Examples

### Good

User: "Security-test the new password reset flow."

Brief: grounded risk is reset token replay or expiry bypass in the password-reset flow, plus account enumeration if the request endpoint can reveal whether an email exists. Source anchor is the reset-token issue/consume and request paths. Evidence choice is native API tests plus state transition testing: issued -> consumed -> expired. First action: add tests that expired, already-used, tampered, and replayed tokens are rejected, and that known-email vs unknown-email reset requests return same status/body. Residual risk: inbox-link delivery and any live-rate-limit behaviour remain unproven without a runnable environment.

### Good

Existing review found: "new `/documents/{id}/raw` endpoint has no owner check."

Brief: grounded risk is any authenticated user reading another user's document. Source anchor is the endpoint and missing guard. Evidence choice is native integration/API negative-path test before any external tooling. First action: add a test where user B requests user A's document and gets Forbidden. Residual risk: broader authorization matrix remains unproven unless roles/tenant rules are supplied.

### Bad

"Run OWASP Top 10, ZAP, Burp, Snyk, and a SAST scanner." This dumps categories and vendor/tool names without source anchor, stack fit, first proof action, or confirmation for setup.

## Next skill in the chain

If native evidence fits, route to the relevant implementation/review skill with the concrete action. If no native sumo-qa path can cover the grounded risk, route to `sumo-qa-suggesting-external-skill` with `entry_kind: "qa"` and the named security surface.
