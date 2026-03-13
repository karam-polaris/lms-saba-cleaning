"""Agent 5 -- SunsetPlanner

Proposes concrete retirement dates and flags implausible existing dates.

Rules:
  - Regulatory courses -> HITL required, no automated retirement
  - Out-of-Scope + zero FY26 activity -> propose 2026-03-31
  - Out-of-Scope + FY26 activity      -> propose 2026-06-30, flag HITL
  - Review                            -> propose 2026-06-30 if no date
  - Discontinue date > 4 years away   -> flag as implausible
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

TODAY          = datetime.now(timezone.utc).replace(tzinfo=None)
NEAR_RETIRE    = datetime(2026, 3, 31)
SOFT_RETIRE    = datetime(2026, 6, 30)
IMPLAUSIBLE_YR = 4


def plan(df: pd.DataFrame) -> pd.DataFrame:
    prop_dates, retire_flags, rationales, needs_hitl = [], [], [], []

    for _, row in df.iterrows():
        scope   = row.get("_scope",        "Review")
        is_reg  = bool(row.get("_is_regulatory", False))
        disc    = row.get("Discontinue Date")
        fy26_c  = float(row.get("FY26 Completions", 0) or 0)
        fy26_e  = float(row.get("FY26 Enrollments",  0) or 0)

        retire  = False
        hitl    = False
        rat     = []
        proposed = disc  # default: keep existing date

        if is_reg:
            hitl = True
            rat.append("Regulatory -- retirement requires L&D leadership approval")

        elif scope == "Out-of-Scope":
            if fy26_c > 0 or fy26_e > 0:
                proposed = SOFT_RETIRE
                hitl = True
                rat.append(f"Out-of-Scope but active in FY26 -- soft deadline {SOFT_RETIRE.date()}")
            else:
                proposed = NEAR_RETIRE
                retire   = True
                rat.append(f"No FY24/25/26 completions -- proposed retirement {NEAR_RETIRE.date()}")

        elif scope == "Review":
            if pd.isna(disc) or disc is None:
                proposed = SOFT_RETIRE
                rat.append(f"Missing retirement date -- proposed soft deadline {SOFT_RETIRE.date()}")

        # Flag implausible future dates
        if pd.notna(disc) and hasattr(disc, "year"):
            yrs_ahead = (disc - TODAY).days / 365.0
            if yrs_ahead > IMPLAUSIBLE_YR:
                rat.append(f"Existing date is {yrs_ahead:.1f} yrs away -- may be implausible")
                hitl = True

        prop_dates.append(proposed)
        retire_flags.append(retire)
        rationales.append("; ".join(rat) if rat else "No change required")
        needs_hitl.append(hitl)

    df = df.copy()
    df["_proposed_discontinue_date"] = prop_dates
    df["_retire_flag"]               = retire_flags
    df["_sunset_rationale"]          = rationales
    df["_sunset_hitl"]               = needs_hitl
    return df
