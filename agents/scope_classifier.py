"""Agent 4 -- ScopeClassifier

Scores every course on relevance and proposes:
  In-Scope   (score >= 0.65)  -> export to Eightfold
  Review     (score 0.35-0.64) -> human review required
  Out-of-Scope (score < 0.35) -> propose retirement

Regulatory and assessment courses have protected score floors.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

TODAY = datetime.now(timezone.utc).replace(tzinfo=None)

SCOPE_IN    = "In-Scope"
SCOPE_OUT   = "Out-of-Scope"
SCOPE_REVIEW = "Review"

THRESHOLD_IN  = 0.65
THRESHOLD_OUT = 0.35

REG_FLOOR   = 0.50   # regulatory courses never go below this
ENROL_FLOOR = 0.45   # courses with open FY26 enrollments never go below this


def _score_row(row: pd.Series) -> tuple[float, list[str]]:
    score     = 1.0
    rationale = []

    fy24 = float(row.get("FY24 Completions", 0) or 0)
    fy25 = float(row.get("FY25 Completions", 0) or 0)
    fy26 = float(row.get("FY26 Completions", 0) or 0)
    enr  = float(row.get("FY26 Enrollments", 0) or 0)

    # -- Participation --
    if fy24 == 0 and fy25 == 0 and fy26 == 0:
        score -= 0.40
        rationale.append("No completions in FY24, FY25, or FY26")

    # -- Recency --
    last_comp = row.get("Last Completion Date")
    if pd.isna(last_comp) or last_comp is None:
        score -= 0.20
        rationale.append("No last-completion date on record")
    elif hasattr(last_comp, "year"):
        months_ago = (TODAY - last_comp).days / 30.0
        if months_ago > 24:
            score -= 0.20
            rationale.append(f"Last completion {int(months_ago)} months ago")

    # -- Aging --
    avail = row.get("Cat Item Available Date")
    if pd.notna(avail) and hasattr(avail, "year"):
        years_old = (TODAY - avail).days / 365.0
        if years_old > 4:
            score -= 0.15
            rationale.append(f"Course is {years_old:.1f} yrs old (available {avail.date()})")

    # -- Metadata completeness --
    if not str(row.get("Course Category", "") or "").strip():
        score -= 0.05
        rationale.append("Course Category missing")
    if not str(row.get("Course Business Owner1", "") or "").strip():
        score -= 0.05
        rationale.append("Business Owner missing")

    # -- Protective floors --
    if row.get("_is_regulatory"):
        score = max(score, REG_FLOOR)
        rationale.append(f"Regulatory course -- score floor {REG_FLOOR} applied")
    if enr > 0:
        score = max(score, ENROL_FLOOR)
        rationale.append(f"FY26 open enrollments ({int(enr)}) -- retirement blocked")

    return max(score, 0.0), rationale


def classify(df: pd.DataFrame) -> pd.DataFrame:
    scopes, scores, rationales = [], [], []

    for _, row in df.iterrows():
        score, rat = _score_row(row)

        if score >= THRESHOLD_IN:
            scope = SCOPE_IN
        elif score >= THRESHOLD_OUT:
            scope = SCOPE_REVIEW
        else:
            scope = SCOPE_OUT

        # Assessments: never auto Out-of-Scope (legitimate zero-completion tools)
        if row.get("_is_assessment") and scope == SCOPE_OUT:
            scope = SCOPE_REVIEW
            rat.append("Assessment -- moved Out-of-Scope -> Review")

        scopes.append(scope)
        scores.append(round(score, 3))
        rationales.append("; ".join(rat) if rat else "Score above In-Scope threshold")

    df = df.copy()
    df["_scope"]          = scopes
    df["_scope_score"]    = scores
    df["_scope_rationale"] = rationales
    return df
