"""Agent 2 -- AssessmentDetector

Distinguishes assessments/tests from learning courses so downstream agents
apply appropriate thresholds (assessments are not penalised for low completion).

Confidence scoring:
  ≥ 0.60 -> _is_assessment = True
  < 0.60 -> _is_assessment = False (but low confidence flagged for HITL)
"""
from __future__ import annotations

import re

import pandas as pd

# Matches "- Assessment", "- Assessment", "-- Assessment" at end of title
# or standalone "Assessment", "Exam", "Test", "Quiz", "Evaluación"
ASSESSMENT_TITLE_RE = re.compile(
    r"[-\u2013\u2014]\s*assess(ment)?s?\s*$"
    r"|\bassess(ment)?s?\b"
    r"|\bexam(ination)?s?\b"
    r"|\bquiz(zes)?\b"
    r"|\bevalua(ci[oó]n|tion)s?\b",
    re.IGNORECASE,
)

# Deloitte course code ending in 'A' indicates assessment (e.g., TE715A, SIT110A)
CODE_SUFFIX_A_RE = re.compile(r"\b[A-Z]{2,4}\d{2,4}A\b")


def _get_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    return next((c for c in candidates if c in df.columns), None)


def detect(df: pd.DataFrame) -> pd.DataFrame:
    title_col = _get_col(df, ["Course Title", "Mandatory Field: Course Title"])
    hours_col = _get_col(df, ["Learning Hours"])
    cpe_col   = _get_col(df, ["Cpe Hours"])
    adhoc_col = _get_col(df, ["Is Adhoc Course"])

    is_assessments, confidences = [], []

    for _, row in df.iterrows():
        title      = str(row.get(title_col, "") or "") if title_col else ""
        confidence = 0.0
        signals    = []

        # 1. Title regex match (strongest signal)
        if ASSESSMENT_TITLE_RE.search(title):
            confidence += 0.70
            signals.append("title_pattern")

        # 2. Deloitte code suffix 'A'
        if CODE_SUFFIX_A_RE.search(title):
            confidence += 0.20
            signals.append("code_suffix_A")

        # 3. Very short duration + no CPE
        if hours_col:
            hrs = float(row.get(hours_col, 0) or 0)
            cpe = float(row.get(cpe_col, 0) or 0) if cpe_col else 0
            if hrs <= 0.25 and cpe == 0:
                confidence += 0.15
                signals.append("short_duration")

        # 4. Adhoc flag
        if adhoc_col and str(row.get(adhoc_col, "")).strip().lower() == "yes":
            confidence += 0.10
            signals.append("adhoc_flag")

        confidence = min(confidence, 1.0)
        is_assessments.append(confidence >= 0.60)
        confidences.append(round(confidence, 3))

    df = df.copy()
    df["_is_assessment"]           = is_assessments
    df["_assessment_confidence"]   = confidences
    return df
