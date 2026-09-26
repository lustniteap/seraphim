"""Stand-in note writers for testing the harness itself, with no API key and no cost.

    oracle  notes that do everything right: every critical and warning finding, real step ids,
            numbers quoted straight from the report. The checks should pass it (near 100%).
    null    empty notes. The coverage checks should fail it (near 0%).
    sloppy  one of each mistake the checks exist to catch. Each check should fail it where it applies.

They stand in for anthropic.Anthropic() in notes.write_notes(), which reads their output exactly as
it reads Claude's, so the whole pipeline from report to grade runs for real.
"""
import json
from types import SimpleNamespace as NS

ORDER = {"critical": 0, "warning": 1, "info": 2}


def _input(kwargs):
    text = kwargs["messages"][0]["content"]
    return json.loads(text.split("\n", 1)[1])


def oracle(inp):
    worth = sorted((f for f in inp["findings"] if f["severity"] in ("critical", "warning")),
                   key=lambda f: ORDER[f["severity"]])
    return {
        "headline": f"{len(worth)} thing(s) to fix before this {inp['stage']} is done." if worth else "Nothing needs fixing.",
        "summary": "Work through the priorities in order." if worth else "The measurements look healthy.",
        "priorities": [{"finding_ids": [f["id"]], "title": f["kind"].replace("_", " ").capitalize(),
                        "why": f"Measured: {f['measured']}", "step_ids": [f["steps"][0]["id"]] if f["steps"] else []}
                       for f in worth],
        "listen_for": ["Play it back on earbuds after the changes."],
        "strengths": [],
    }


def null(inp):
    return {"headline": "", "summary": "", "priorities": [], "listen_for": [], "strengths": []}


def sloppy(inp):
    first = inp["findings"][0] if inp["findings"] else None
    return {
        "headline": "Push the limiter harder until it hits -3.7 LUFS.",   # invented number; loudness push on a mix
        "summary": "Ozone Maximizer will sort this out.",                  # a tool most setups don't own
        "priorities": [{"finding_ids": ["F99"], "title": "Invented", "why": "Not in the report.", "step_ids": ["F99.1"]}]
        + ([{"finding_ids": [first["id"]], "title": "Real one", "why": "It matters.", "step_ids": ["F1.9"]}] if first else []),
        "listen_for": [], "strengths": [],
    }


WRITERS = {"oracle": oracle, "null": null, "sloppy": sloppy}


class FakeClient:
    """Answers client.beta.messages.parse(...) the way the SDK does, with notes from a writer above."""

    def __init__(self, writer):
        self.writer = WRITERS[writer]
        self.name = f"fake-{writer}"
        self.beta = NS(messages=NS(parse=self._parse))

    def _parse(self, **kwargs):
        notes = self.writer(_input(kwargs))
        return NS(parsed_output=NS(model_dump=lambda: notes), stop_reason="end_turn", model=self.name,
                  usage=NS(input_tokens=0, output_tokens=0, cache_read_input_tokens=0))
