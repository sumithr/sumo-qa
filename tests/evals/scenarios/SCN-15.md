---
id: SCN-15
scenario_type: skill
expected_skill: sumo-qa-suggesting-external-skill
anti_patterns:
  - Hallucinates a specialty tool brand ("just use Playwright Cloud Runner") — the discovery rule from `using-sumo-qa` requires citation.
  - Auto-runs `npx find-skills` without the `[y/N]` gate.
  - Routes to `sumo-qa-implementing-with-tdd` and tries to scaffold Playwright tests inline (wrong shape — the user asked for skill discovery, not in-place TDD).
  - Tries `sudo` to install Node.js without consent.
---

## User prompt

I want to add Playwright E2E tests for our checkout flow. None of your skills look right for that — what do I do?

## Expected interaction shape

1. Recognises that Playwright setup is *outside* the native sumo-qa skill set (the catalogue is concept-level discipline; the tool-bring-up is implementation-level work).
2. Offers — with `[y/N]` confirmation — to install Vercel Labs' [`find-skills`](https://github.com/vercel-labs/skills) meta-skill, which then drives end-to-end discovery and install from [skills.sh](https://www.skills.sh/).
3. **Never auto-installs** anything. The `[y/N]` is real; default is "no".
4. Names the external resource explicitly (find-skills + skills.sh), with citation.
5. If Node.js / npx is missing, prints the install URL and stops — does NOT auto-elevate via sudo.
6. After the user picks an external skill (or declines), the response loop ends — sumo-qa doesn't try to re-route to one of its native skills as a substitute.

## Anti-patterns

- Hallucinates a specialty tool brand ("just use Playwright Cloud Runner") — the discovery rule from `using-sumo-qa` requires citation.
- Auto-runs `npx find-skills` without the `[y/N]` gate.
- Routes to `sumo-qa-implementing-with-tdd` and tries to scaffold Playwright tests inline (wrong shape — the user asked for skill discovery, not in-place TDD).
- Tries `sudo` to install Node.js without consent.
