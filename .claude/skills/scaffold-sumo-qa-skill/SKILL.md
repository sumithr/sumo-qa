---
name: scaffold-sumo-qa-skill
description: Scaffolds a new sumo-qa sub-skill end-to-end — SKILL.md skeleton, matching promptfoo eval YAML, and an approaches.md catalogue entry — through a single bundled script. Use this whenever the user wants to add a new sumo-qa-* skill, even if they describe it as "creating a skill", "adding an approach", "starting a new routing branch", or just "writing skills/sumo-qa-X". Enforces the sumo-qa- name prefix and checks for collisions against both the source tree and the installed MCP server, so a clean handoff to the next contributor is always possible.
disable-model-invocation: true
---

# scaffold-sumo-qa-skill

Drives the four-step recipe for adding a new `sumo-qa-<name>` sub-skill so all the pieces land together. The deterministic file generation lives in `scripts/scaffold.py`; this document is the thin guide for gathering inputs and checking the surfaces the script cannot reach (the installed MCP server).

## When to use

Trigger this skill whenever the user asks to add a new sumo-qa sub-skill — phrases like "scaffold a new skill", "add a sumo-qa-X skill", "I want a skill that handles Y for QA", or even just "let's start the routing for Z". The user invokes it explicitly with `/scaffold-sumo-qa-skill`; it doesn't auto-trigger.

## Inputs

Gather these from the user up front. If they only give a partial set, ask for the rest in one round of questions — don't drip-feed.

1. **Skill name** (without prefix) — kebab-case, descriptive of the user-intent the skill handles. The script prepends `sumo-qa-` automatically.
2. **One-line description** — for the SKILL.md frontmatter `description:`. Convention across the estate: start with "Use when ..." so the trigger context is obvious.
3. **Approach tag** — the kebab-case routing key that lands in `knowledge/approaches.md`. The user's `sumo-qa-deciding-approach` skill consults this catalogue when picking which sub-skill to route to.

## Verify the surfaces the script can't reach

The script checks for collisions against the source tree (`skills/`, `tests/evals/promptfoo/`, `knowledge/approaches.md`). It can't check the installed MCP server, which serves a frozen-at-install-time view of the catalogues. Before invoking the script, call:

```
sumo_qa_load_approaches
```

through the MCP server and confirm the proposed approach tag isn't already shipped. The source tree may have unreleased entries the MCP doesn't yet see, and vice versa — checking both surfaces is what catches both classes of collision.

## Run the script

```bash
python3 .claude/skills/scaffold-sumo-qa-skill/scripts/scaffold.py \
  --name <kebab-name> \
  --description "Use when <triggering context>." \
  --approach-tag <kebab-tag>
```

The script exits non-zero with a clear message on any source-tree collision. If that happens, surface the collision to the user verbatim rather than trying to work around it — the namespace policy exists to keep routing unambiguous.

On success, the script prints the three files it created plus the next-step checklist. Pass that summary back to the user so they know what they still need to do by hand.

## What the script does and does not do

It writes three files (the SKILL.md skeleton, the eval YAML stub, the approaches.md block) and prints the follow-up checklist. It deliberately does **not** edit `skills/sumo-qa-deciding-approach/SKILL.md` — that file has context-sensitive routing tables that resist mechanical patching, and a half-correct edit there breaks routing for every other sub-skill. The contributor adds the routing line by hand using the approach tag they just registered.

## After the script runs

Remind the user, in this order:

1. Flesh out the workflow in the new `skills/sumo-qa-<name>/SKILL.md` — the skeleton is intentionally generic.
2. Replace the seed scenario in the new eval YAML with a concrete case before running `npm run eval`. The placeholder will fail every assertion.
3. Add the routing line in `skills/sumo-qa-deciding-approach/SKILL.md` manually.
4. Run `sumo-qa-validate` so the catalogue still parses.
5. Reinstall the package (`pip install -e .`) and restart the MCP host before the new approach tag becomes visible to `sumo_qa_load_approaches`. Until then, source and installed views disagree — that's expected, not a bug.

The scaffold is a starting point, not a finished skill. Don't open a PR with just the scaffold contents; the eval will fail against the placeholder content, and the policy in this repo is to fix the SKILL.md until the eval passes rather than ship with known gaps.
