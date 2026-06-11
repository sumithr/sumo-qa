"""GEPA adapter scoring candidates through the real promptfoo harness."""

import harness
import scoring
import scratch
from gepa.core.adapter import EvaluationBatch, GEPAAdapter


class PromptfooAdapter(GEPAAdapter):
    def __init__(self, seed_tokens: int):
        self.seed_tokens = seed_tokens

    def evaluate(self, batch, candidate, capture_traces=False):
        text = candidate["skill_md"]
        outputs, scores, trajectories = [], [], []
        if not scoring.shape_ok(text):
            for inst in batch:
                outputs.append({"yaml": inst["yaml"], "rows": []})
                scores.append(0.0)
                trajectories.append(
                    {"yaml": inst["yaml"], "rows": [], "note": "malformed candidate (shape guard)"}
                )
            return EvaluationBatch(
                outputs=outputs,
                scores=scores,
                trajectories=trajectories if capture_traces else None,
            )
        scratch.write_candidate(text)
        cand_tokens = scoring.token_count(text)
        for inst in batch:
            rows = harness.run_yaml_with_retry(inst["yaml"])
            if inst["kind"] == "ab":
                score = scoring.ab_score(rows)  # raises EnvironmentDrift -> halt run
            else:
                score = scoring.candidate_score(rows, cand_tokens, self.seed_tokens)
            outputs.append({"yaml": inst["yaml"], "rows": rows})
            scores.append(score)
            trajectories.append({"yaml": inst["yaml"], "rows": rows})
        return EvaluationBatch(
            outputs=outputs, scores=scores, trajectories=trajectories if capture_traces else None
        )

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        items = []
        for out in eval_batch.outputs:
            for r in out["rows"]:
                if not r["success"]:
                    items.append(
                        {
                            "Inputs": f"{out['yaml']} :: {r['desc']}",
                            "Generated Outputs": f"(judge score {r['score']:.2f})",
                            "Feedback": r["reason"],
                        }
                    )
        if not items:
            cand_tokens = scoring.token_count(candidate["skill_md"])
            items.append(
                {
                    "Inputs": "all minibatch tests passing",
                    "Generated Outputs": f"candidate is {cand_tokens} tokens",
                    "Feedback": (
                        f"All tests passed. Candidate is {cand_tokens} tokens vs seed "
                        f"{self.seed_tokens}; target is <= {self.seed_tokens // 2}. "
                        "Compress further WITHOUT losing any behavioural rule, trigger, "
                        "named check, gate or verdict format."
                    ),
                }
            )
        return {"skill_md": items}
