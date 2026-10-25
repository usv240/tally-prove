"""Domain models. Pydantic so every agent output and every stored record is typed.

Vocabulary follows the child care day and the food program: component, meal pattern, ratio,
subsidy authorization, claim.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Component(StrEnum):
    MILK = "milk"
    FRUIT = "fruit"
    VEGETABLE = "vegetable"
    GRAIN = "grain"
    MEAT_ALT = "meat_alt"
    JUICE = "juice"  # a fruit, but limited to once a day, so tracked separately
    NONE = "none"  # identified food that counts toward no component, such as a condiment


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    SUPPER = "supper"
    SNACK = "snack"


class AgeGroup(StrEnum):
    INFANT = "infant"
    A1_2 = "1-2"
    A3_5 = "3-5"
    A6_12 = "6-12"
    A13_18 = "13-18"


def age_group_for(birth_date: date, on: date) -> AgeGroup:
    years = on.year - birth_date.year - ((on.month, on.day) < (birth_date.month, birth_date.day))
    if years < 1:
        return AgeGroup.INFANT
    if years <= 2:
        return AgeGroup.A1_2
    if years <= 5:
        return AgeGroup.A3_5
    if years <= 12:
        return AgeGroup.A6_12
    return AgeGroup.A13_18


class Child(BaseModel):
    id: str
    provider_id: str
    first_name: str
    birth_date: date
    enrolled_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # Monday is 0
    usual_arrival: str = "07:30"
    subsidized: bool = False
    subsidy_days: list[int] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    family_contact: str = ""
    family_language: Literal["en", "es"] = "en"

    def age_group(self, on: date) -> AgeGroup:
        return age_group_for(self.birth_date, on)


class Provider(BaseModel):
    id: str
    name: str
    state: str = "TX"
    license_type: str = "licensed"
    tier: Literal["tier_1", "tier_2"] = "tier_1"
    language: Literal["en", "es"] = "en"
    sponsor_name: str = ""
    sponsor_email: str = ""
    assistant_from: str | None = "14:30"
    nap_start: str = "13:00"
    nap_end: str = "14:30"
    question_budget: int = 2


class Item(BaseModel):
    """One food the vision model saw on the plate."""

    name: str
    component: Component
    confidence: float
    note: str = ""


class PlateReading(BaseModel):
    """What the Plate agent saw. Deliberately no portion sizes."""

    items: list[Item] = Field(default_factory=list)
    meal_type_guess: MealType | None = None
    questions: list[str] = Field(default_factory=list)
    """One question per item the model was not sure enough about to log."""


class Verdict(BaseModel):
    reimbursable: bool
    missing: list[Component] = Field(default_factory=list)
    smallest_fix: str = ""
    flags: list[str] = Field(default_factory=list)
    label_checks: list[str] = Field(default_factory=list)
    rule_version: str = ""
    explanation: str = ""
    by_age_group: dict[str, bool] = Field(default_factory=dict)


ProofVerdict = Literal[
    "VALID",        # the rules prove the answer
    "INVALID",      # the rules contradict the answer; `rules` says which
    "SATISFIABLE",  # true under some facts, false under others; `missing_facts` says which
    "AMBIGUOUS",    # the sentence has two readings; `missing_facts` says how they differ
    "IMPOSSIBLE",   # the stated facts contradict each other
    "UNVERIFIED",   # outside the rulebook, or too complex to decide
    "SKIPPED",      # proving is switched off, or the check did not run
]


class Proof(BaseModel):
    """One check of one answer against the regulation. Kept, so a reviewer can see it a year later."""

    id: str
    provider_id: str
    at: datetime
    question: str
    answer: str
    facts: str = ""
    verdict: ProofVerdict
    rules: list[str] = Field(default_factory=list)
    """The rules that prove or contradict the answer, in the rulebook's words."""
    premises: list[str] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    untranslated: list[str] = Field(default_factory=list)
    """Parts of the answer the logic could not read. A VALID verdict does not cover these."""
    missing_facts: list[str] = Field(default_factory=list)
    """Statements whose truth would settle the answer. The agent turns one into a question."""
    policy_version: str = ""
    guardrail_version: str = ""
    latency_ms: int = 0
    text_units: int = 0
    request_id: str = ""
    """AWS request id of the check, for matching the receipt against CloudTrail."""
    attempt: int = 1
    meal_id: str | None = None
    ledger: dict = Field(default_factory=dict)
    """Where the receipt was filed in Amazon S3 (bucket, key, locked_until), or why it was not."""


class Meal(BaseModel):
    id: str
    provider_id: str
    at: datetime
    meal_type: MealType
    photo_key: str | None = None
    items: list[Item] = Field(default_factory=list)
    verdict: Verdict | None = None
    children_served: list[str] = Field(default_factory=list)
    substitutions: dict[str, list[Item]] = Field(default_factory=dict)
    """child id to the items that child actually had, when they differ (an allergy substitute)."""
    replaces: str | None = None
    """the meal id this one corrects, when a provider fixes a plate and photographs it again."""


class AttendanceEvent(BaseModel):
    child_id: str
    event: Literal["arrive", "depart", "absent", "expected"]
    at: datetime
    note: str = ""


class RatioCheck(BaseModel):
    now_count: int
    now_ok: bool
    limit: int
    next_change_at: datetime | None = None
    next_change_count: int | None = None
    next_change_ok: bool | None = None
    unaccounted: list[str] = Field(default_factory=list)
    """Enrolled today, not signed in, usual arrival passed. Counted toward the limit, because
    assuming they are not coming is the unsafe direction."""
    explanation: str = ""


class Question(BaseModel):
    id: str
    provider_id: str
    at: datetime
    text: str
    options: list[str] = Field(default_factory=list)
    priority: Literal["safety", "meal", "reconciliation", "compliance"] = "reconciliation"
    answered: bool = False
    answer: str = ""
    # What this question is about, in terms that recur: "subsidy-leo-1" is Leo on a Tuesday. Empty
    # for questions that cannot repeat, like a plate that is short a component right now.
    topic: str = ""


class ParentNote(BaseModel):
    child_id: str
    on: date
    text: str
    language: Literal["en", "es"] = "en"
    approved: bool = False
    sent_at: datetime | None = None


class ComplianceItem(BaseModel):
    id: str
    provider_id: str
    kind: str
    label: str
    due: date
    last_done: date | None = None
    status: Literal["ok", "due", "overdue"] = "ok"


class ClaimLine(BaseModel):
    meal_type: MealType
    count: int
    rate: float
    amount: float


class Claim(BaseModel):
    provider_id: str
    month: str  # YYYY-MM
    lines: list[ClaimLine] = Field(default_factory=list)
    total: float = 0.0
    not_reimbursable: int = 0
    lost_amount: float = 0.0
    """What the non-reimbursable meals would have paid. This is the number that closes homes."""
    status: Literal["draft", "sent"] = "draft"
    sent_at: datetime | None = None
    computed_in: str = "local"
    """Where the arithmetic ran: agentcore_code_interpreter, local, or local_fallback. Shown on the
    month view, because a claim about where money was computed should be checkable."""
    computed_reason: str = ""
    """Why it fell back, when it did. Saying which one answered is only half of honest."""
