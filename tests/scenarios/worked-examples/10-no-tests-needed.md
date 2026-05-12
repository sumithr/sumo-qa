# Scenario 10 — Trivial change, no tests needed

> **Demo arc:** *"my AI would have written a docs-rendering smoke test, added a CI check, and walked me through a 5-section formal review — for a typo. sumo-qa said: no tests needed, just check it renders. That IS the senior-QA answer."*
>
> Shows: restraint. Knowing when NOT to add tests. The taxonomy ran end-to-end internally — `docs_change` -> `no-tests-recommended` — and the user-facing answer was one natural-English paragraph, not a checklist.

---

## Turn 1 — User

> I'm fixing a typo in a comment in `docs/CONFIGURATION.md`. Anything I need to do?

---

## Turn 2 — sumo-qa

*(internal: invokes `qa-deciding-approach`. Loads `sumo_qa_load_classifications()` + `sumo_qa_load_approaches()`. The intent cites `docs/CONFIGURATION.md` and the word "typo" — no behavioural surface, no public API, no consumer impact.)*

> **Internal routing decision (not surfaced to the user):**
> - **Classification:** `docs_change` — change to a non-executable artefact; risk is minimal (catalogue: *"typically no QA test work needed beyond build/lint"*).
> - **Approach:** `no-tests-recommended` — pure docs / typos / comments. The honest senior-QA answer when the change has no behavioural surface (catalogue).
> - **Principle cited:** ISTQB Principle 3 — *early testing saves time and money* — and its corollary: testing where there's no behaviour to verify wastes signal.
> - **Next action:** stop. Per the routing table, `no-tests-recommended` has no sub-skill. Do NOT route to `qa-preparing-for-work` or `qa-reviewing-before-merge` — those are wrong shapes for a typo.

No tests needed for this one — it's docs-only, no behavioural surface to verify. Commit it, push it, and the build/lint will catch anything structural (broken Markdown, dead link, etc.).

The only thing worth a 30-second check: confirm the doc still **renders** correctly once committed — if `docs/CONFIGURATION.md` is part of an MkDocs / Sphinx / Docusaurus site, a stray backtick or accidentally-broken code fence in the comment edit can quietly break the page.

Want me to spin up `mkdocs serve` (or whichever tool this site uses) and eyeball the rendered page before you push?

---

## Turn 3 — User

> Nah, it's literally one character. I'll push it. Thanks.

---

## Turn 4 — sumo-qa

Sensible. Ship it.

---

## Why this is "senior QA" — what to point at in the demo

- **Restraint is the feature.** The shortest correct answer here is *"no tests needed."* Adding a docs-rendering smoke test, a CI gate, or a formal review for a typo is noise — it dilutes the signal of real QA work and trains the team to ignore QA gates.
- **The taxonomy ran — invisibly.** Classification (`docs_change`) and approach (`no-tests-recommended`) were both decided from the catalogue, but the user never saw those labels. They saw natural English. That's the discipline: the taxonomy is internal scaffolding, not a deliverable.
- **The right follow-up offered, not forced.** Verifying the doc renders is a *reasonable* lightweight check — but it's optional, surfaced as an offer, and instantly droppable when the user says "it's one character." A junior-shaped AI would have insisted on it.
- **No routing to the wrong sub-skill.** This change does not need `qa-preparing-for-work` (no story to plan) or `qa-reviewing-before-merge` (no risks to map to tests). The router knew to stop.
- **One ISTQB principle, applied honestly.** Principle 3 (*early testing saves time and money*) usually gets quoted to justify *more* testing. Here it justifies *less* — early testing pays back when there's behaviour to verify; on a comment typo, it doesn't.

---

## Contrast — what a less-disciplined AI would have said

> *"Great question! For a documentation change, I'd recommend: (1) writing a smoke test that builds the docs site and verifies the page renders without errors; (2) adding a CI step that runs `markdownlint` on `docs/**/*.md`; (3) walking through a quick pre-merge review — let me list the risks: a) the typo fix could accidentally break a code fence, b) the rendered output could shift if the comment was part of a code example, c) downstream consumers of the docs (the developer portal? the customer FAQ?) might cache the old version… Shall I start with the smoke test scaffold?"*

For a typo.

That answer isn't wrong-in-isolation — every line of it is *technically* defensible. But applied to a one-character comment fix, it's noise, not QA. The senior-QA call is to recognise the shape of the change *first*, and stay quiet when there's nothing to verify.

**That's what sumo-qa is doing here — and it's the single hardest thing to get an AI assistant to do.** Most are tuned to be helpful by adding work. This one is tuned to be helpful by *not* adding work when none is needed.
