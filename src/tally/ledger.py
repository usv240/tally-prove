"""The proof ledger: every receipt written to Amazon S3, where nobody can edit it afterwards.

A proof receipt is evidence. The sponsor reads it at the monthly review, the state agency reads it
at audit, and a year on the question is "why did the agent say that on the 8th of September?". A
record that lives in the container's memory is gone at the next deploy, and a record anyone can
rewrite is not evidence. So each proof is also written to an S3 bucket with Object Lock in
compliance mode: a write-once object, keyed by provider, day and proof id, that cannot be changed or
deleted by anyone, this code included, until the retention period ends.

The bucket is not a tool. The agent never reads it, and it does not change what the agent can do.
It is where the tool's output lands, the same way the claim lands on the sponsor's desk. S3 was
chosen because Amazon's own guidance for Automated Reasoning audit trails is a durable, tamper
evident store with Object Lock, and because a plain object key is something a reviewer can be
handed and look up without Tally in the loop.

Off unless TALLY_LEDGER_BUCKET is set. Failures are recorded on the proof and never raised: a
receipt that could not be filed is still shown, marked as unfiled, which is the honest state.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import timedelta

RETENTION_DAYS = int(os.environ.get("TALLY_LEDGER_RETENTION_DAYS", "1095"))
"""Three years: a CACFP claim can be reviewed for three fiscal years after it is paid."""

_client = None
_lock = threading.Lock()


def bucket() -> str | None:
    return os.environ.get("TALLY_LEDGER_BUCKET") or None


def enabled() -> bool:
    return bucket() is not None


def _s3():
    global _client
    with _lock:
        if _client is None:
            import boto3

            _client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        return _client


def key_for(provider_id: str, proof) -> str:
    return f"proofs/{provider_id}/{proof.at:%Y/%m/%d}/{proof.id}.json"


def file(proof, provider_id: str) -> dict:
    """Write one proof as a locked object. Returns where it went, or why it did not."""
    b = bucket()
    if not b:
        return {"filed": False, "reason": "no ledger bucket configured"}
    key = key_for(provider_id, proof)
    body = json.dumps(json.loads(proof.model_dump_json()), indent=1).encode("utf-8")
    try:
        _s3().put_object(
            Bucket=b, Key=key, Body=body, ContentType="application/json",
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=proof.at + timedelta(days=RETENTION_DAYS),
            Metadata={"verdict": proof.verdict, "guardrail-version": proof.guardrail_version or "",
                      "policy-version": proof.policy_version.split("/")[-1] if proof.policy_version else "",
                      "request-id": proof.request_id or ""},
        )
        until = (proof.at + timedelta(days=RETENTION_DAYS)).date().isoformat()
        return {"filed": True, "bucket": b, "key": key, "locked_until": until}
    except Exception as exc:
        return {"filed": False, "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}


def read(provider_id: str, proof) -> dict | None:
    """Read a receipt back from the ledger, for the reviewer who wants the stored copy, not the live one."""
    b = bucket()
    if not b:
        return None
    try:
        r = _s3().get_object(Bucket=b, Key=key_for(provider_id, proof))
        return json.loads(r["Body"].read())
    except Exception:
        return None


def status() -> dict:
    return {"bucket": bucket(), "retention_days": RETENTION_DAYS, "object_lock": "COMPLIANCE" if bucket() else None}
