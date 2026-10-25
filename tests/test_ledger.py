"""The proof ledger files receipts as locked objects, and says so honestly when it cannot."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tally import ledger, prove, runtime
from tally.models import Proof
from tally.service import setup
from tally.tools.prove import prove_answer


def proof(**kw) -> Proof:
    base = {"id": "proof-abc12345", "provider_id": "rosa", "at": datetime(2026, 9, 8, 7, 38),
            "question": "q", "answer": "a", "verdict": "VALID", "guardrail_version": "8",
            "policy_version": "arn:aws:bedrock:us-east-1:1:automated-reasoning-policy/x:7"}
    return Proof(**{**base, **kw})


class FakeS3:
    def __init__(self, fail=False):
        self.puts, self.fail = [], fail

    def put_object(self, **kw):
        if self.fail:
            raise RuntimeError("AccessDenied")
        self.puts.append(kw)

    def get_object(self, **kw):
        import io
        return {"Body": io.BytesIO(self.puts[-1]["Body"])}


def test_off_without_a_bucket(monkeypatch):
    monkeypatch.delenv("TALLY_LEDGER_BUCKET", raising=False)
    assert not ledger.enabled()
    assert ledger.file(proof(), "rosa") == {"filed": False, "reason": "no ledger bucket configured"}


def test_files_a_locked_object_under_provider_and_day(monkeypatch):
    monkeypatch.setenv("TALLY_LEDGER_BUCKET", "b")
    fake = FakeS3()
    monkeypatch.setattr(ledger, "_client", fake)
    out = ledger.file(proof(), "rosa")
    assert out["filed"] and out["key"] == "proofs/rosa/2026/09/08/proof-abc12345.json"
    put = fake.puts[0]
    assert put["ObjectLockMode"] == "COMPLIANCE"
    assert put["ObjectLockRetainUntilDate"] == datetime(2026, 9, 8, 7, 38) + timedelta(days=ledger.RETENTION_DAYS)
    assert put["Metadata"] == {"verdict": "VALID", "guardrail-version": "8", "policy-version": "x:7", "request-id": ""}
    assert ledger.read("rosa", proof())["id"] == "proof-abc12345"


def test_a_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("TALLY_LEDGER_BUCKET", "b")
    monkeypatch.setattr(ledger, "_client", FakeS3(fail=True))
    out = ledger.file(proof(), "rosa")
    assert out["filed"] is False and "AccessDenied" in out["reason"]


@pytest.fixture
def rt():
    rt, _ = setup()
    runtime.configure(rt)
    return rt


def test_the_tool_files_every_real_verdict_and_skips_none(rt, monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "on")
    monkeypatch.setenv("TALLY_LEDGER_BUCKET", "b")
    fake = FakeS3()
    monkeypatch.setattr(ledger, "_client", fake)
    monkeypatch.setattr(prove, "prove", lambda *a, **k: prove.Checked(verdict="INVALID", rules=["r"]))
    out = prove_answer("Q?", "A.")
    p = rt.store.list_proofs()[0]
    assert p.ledger["filed"] and len(fake.puts) == 1
    assert any(e["kind"] == "proof_filed" and e["filed"] for e in rt.trace)
    monkeypatch.setenv("TALLY_PROVE", "off")
    prove_answer("Q2?", "A.")
    assert len(fake.puts) == 1, "a SKIPPED proof is not evidence and is not filed"
    assert out["verdict"] == "INVALID"
