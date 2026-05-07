# Iteration Round <N> — <YYYY-MM-DD HH:MM>

## Scenarios dispatched

<list of scenario IDs run in this round and their resulting verdicts>

## Verdict summary

| scenario_id | verdict | unmet dimensions |
|---|---|---|
| ... | senior-istqb-grade | (none) |
| ... | needs-iteration | principle_citation, named_techniques |

## Aggregated gaps (across scenarios)

- `<gap-name>` — <how many scenarios surfaced it> — <one-line description>

## Aggregated suggested fixes

- file: `src/sumo_qa/<file>` — what to change: `<concrete edit>` — surfaced by: `<scenario ids>`

## Edits made this round

- file: `src/sumo_qa/<file>` — <one-line summary of the edit>
- file: `standards/packs/<pack>.yaml` — <one-line summary>

## Regression check

- `uv run pytest`: <N> passed
- `uv run sumo-qa-eval`: <N>/28

## New scenarios added this round

- `<new scenario id>` — <reason: which gap it stresses>

## Next round plan

- Re-dispatch failing scenarios: <list>
- Run new scenarios: <list>

## Termination check

- All scenarios senior-istqb-grade? <yes/no>
- User read-through confirmed Tesla/SpaceX-grade? <yes/no/pending>
- Last round added zero new scenarios (steady state)? <yes/no>
- Iteration done? <yes/no>
