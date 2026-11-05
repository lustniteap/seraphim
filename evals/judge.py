"""LLM judge for the parts of the notes code can't check: priorities, impact, specificity, tone.

A different model from the one writing the notes grades each case against a fixed rubric
(prompts/judge_notes.md) with structured output, so every verdict parses the same way. Before its
grades steer prompt changes, check it against hand labels (notes_eval.py label / agreement).
"""
import json
from pathlib import Path
from typing import Literal

PROMPT = Path(__file__).parent / "prompts" / "judge_notes.md"
CRITERIA = ["priority_order", "explains_impact", "groups_causes", "specific", "stage_appropriate", "faithful", "concise"]
DEFAULT_JUDGE = "claude-sonnet-5"  # not the model under test, which would favour its own writing


def _schema():
    from pydantic import BaseModel, create_model

    class Verdict(BaseModel):
        verdict: Literal["pass", "fail", "n/a"]
        reason: str

    return create_model("Grades", **{c: (Verdict, ...) for c in CRITERIA})


def judge(client, inp, notes, model=DEFAULT_JUDGE):
    """({criterion: 1.0/0.0/None}, {criterion: reason}, usage, served model)."""
    response = client.messages.parse(
        model=model,
        max_tokens=4000,
        system=PROMPT.read_text(encoding="utf-8"),
        messages=[{"role": "user", "content":
                   "<report>\n" + json.dumps(inp, indent=1, ensure_ascii=False) + "\n</report>\n\n"
                   "<notes>\n" + json.dumps(notes, indent=1, ensure_ascii=False) + "\n</notes>"}],
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        output_format=_schema(),
    )
    if response.parsed_output is None:
        raise RuntimeError(f"judge returned no verdict (stop reason: {response.stop_reason})")
    grades = response.parsed_output.model_dump()
    score = {c: None if g["verdict"] == "n/a" else float(g["verdict"] == "pass") for c, g in grades.items()}
    reasons = {c: g["reason"] for c, g in grades.items()}
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return score, reasons, usage, getattr(response, "model", model)
