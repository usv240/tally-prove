"""prove_answer as an AWS Lambda function, for anyone's agent.

The same proof Tally's Day agent calls, with no Tally around it: a Function URL that takes a
question, a draft answer and the facts, and returns the verdict, the rule sentences and the fact
that would decide it. Put it in front of your own agent's rule answers, from any language, with one
HTTP call. The policy it checks against is whichever guardrail the function is deployed with, so
the same function serves any rulebook built with deploy/reasoning_policy.py.

Deployed by template.yaml (AWS SAM). The function carries only src/tally/prove.py and the exported
policy definition, so a receipt quotes the rule in words rather than by id.

    POST <function-url>
    {"question": "...", "answer": "...", "facts": "..."}
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict

from tally import prove

CFG = {"guardrail_id": os.environ["GUARDRAIL_ID"], "guardrail_version": os.environ["GUARDRAIL_VERSION"]}


def handler(event, context):
    try:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            import base64

            body = base64.b64decode(body).decode("utf-8")
        data = json.loads(body) if isinstance(body, str) else body
    except Exception:
        return _reply(400, {"error": "body must be JSON"})
    question = (data.get("question") or "").strip()
    answer = (data.get("answer") or "").strip()
    if not question or not answer:
        return _reply(400, {"error": "question and answer are required", "optional": ["facts"]})
    t0 = time.time()
    checked = prove.prove(question, answer, data.get("facts") or "", cfg=CFG)
    out = asdict(checked)
    out["summary"] = checked.summary()
    out["latency_ms"] = int((time.time() - t0) * 1000)
    out["guardrail"] = CFG
    return _reply(200, out)


def _reply(status: int, body: dict) -> dict:
    # No CORS headers here: the Function URL adds them from template.yaml, and a browser that sees
    # the header twice refuses the response. The first prove.html did exactly that.
    return {"statusCode": status, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}
