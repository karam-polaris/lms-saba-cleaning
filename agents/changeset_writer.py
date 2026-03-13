"""Agent 11 -- ChangeSetWriter

Merges all agent outputs into:
  - data/output/catalog_with_proposals.xlsx    (full working copy with all _columns)
  - data/output/hitl_queues/<Qname>.json        (one file per queue with items)
  - data/output/changeset_audit_log.jsonl       (row-level audit trail)

HITL queues:
  Q1_HighRiskRetirement    - regulatory or active courses proposed for retirement
  Q2_RegulatoryOverride    - regulatory flag below 0.75 confidence
  Q3_VendorRemap           - fuzzy/unknown vendor mapping
  Q4_BLMapping             - unknown or low-confidence business line
  Q5_Translation           - non-English description without approved translation
  Q5b_DescriptionRequired  - placeholder or missing description
  Q5c_DescriptionMismatch  - title/description topic mismatch
  Q6_LowConfidenceScope    - scope Review or score < 0.60
  Q7_VocabClarification    - unknown Deloitte terms found in title/description
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RUN_ID = str(uuid.uuid4())[:8]
RUN_TS = datetime.now(timezone.utc).isoformat()


# -- Queue assignment --

# Known queues — anything not covered here goes to Q_Other
_KNOWN_QUEUES = {
    "Q1_HighRiskRetirement", "Q2_RegulatoryOverride", "Q3_VendorRemap",
    "Q4_BLMapping", "Q5_Translation", "Q5b_DescriptionRequired",
    "Q5c_DescriptionMismatch", "Q6_LowConfidenceScope", "Q7_VocabClarification",
}

# AI agents can register extra queues dynamically by adding columns named
# _ai_queue_<QueueName> = True/non-empty on any row.
# The changeset writer will discover them and include them automatically.


def _assign_queues(row: pd.Series) -> list[str]:
    queues = []

    retire      = bool(row.get("_retire_flag", False))
    is_reg      = bool(row.get("_is_regulatory", False))
    reg_conf    = float(row.get("_regulatory_confidence", 1.0) or 1.0)
    scope       = str(row.get("_scope", "Review"))
    scope_score = float(row.get("_scope_score", 1.0) or 1.0)
    fy26_c      = float(row.get("FY26 Completions", 0) or 0)
    v_type      = str(row.get("_vendor_change_type", "") or "")
    bl_conf     = float(row.get("_bl_confidence", 1.0) or 1.0)
    pending     = str(row.get("_vocab_pending", "") or "").strip()

    if retire and (is_reg or fy26_c > 0):
        queues.append("Q1_HighRiskRetirement")
    if is_reg and reg_conf < 0.75:
        queues.append("Q2_RegulatoryOverride")
    if v_type in ("FuzzyMed", "Unknown"):
        queues.append("Q3_VendorRemap")
    if bl_conf < 0.70:
        queues.append("Q4_BLMapping")
    if row.get("_translation_needed"):
        queues.append("Q5_Translation")
    if row.get("_description_placeholder") or row.get("_description_missing"):
        queues.append("Q5b_DescriptionRequired")
    if row.get("_description_mismatch"):
        queues.append("Q5c_DescriptionMismatch")
    if scope == "Review" or scope_score < 0.60:
        queues.append("Q6_LowConfidenceScope")
    if pending:
        queues.append("Q7_VocabClarification")

    # Dynamic AI queues: any column named _ai_queue_<Name> with a truthy value
    for col, val in row.items():
        if str(col).startswith("_ai_queue_") and val:
            q_name = str(col)[len("_ai_queue_"):]
            if q_name not in _KNOWN_QUEUES and q_name not in queues:
                queues.append(q_name)

    # Catch-all: if a course has any _ai_issue_* flag not covered above
    ai_issue_flags = [
        col for col in row.index
        if str(col).startswith("_ai_issue_") and row.get(col)
    ]
    already_flagged = bool(queues)
    if ai_issue_flags and not already_flagged:
        queues.append("Q_Other")
    elif ai_issue_flags:
        # Has known queues but also AI-detected extra issues — add to Other too
        queues.append("Q_Other")

    return queues


# -- Human-readable comment --

def _mf_comments(row: pd.Series) -> str:
    parts = []
    if row.get("_description_placeholder"):
        parts.append("DESCRIPTION REQUIRED -- current text is a generic placeholder, blocks Eightfold export")
    if row.get("_description_mismatch"):
        parts.append("DESCRIPTION MISMATCH -- description content appears to belong to a different course (possible copy-paste error)")
    if row.get("_encoding_issues"):
        parts.append("ENCODING ISSUE -- title or description contains corrupted characters, manual correction needed")
    if row.get("_is_regulatory"):
        parts.append(f"REGULATORY COURSE ({row.get('_regulatory_topics', '')}) -- any retirement requires L&D leadership sign-off")
    if row.get("_retire_flag"):
        parts.append(f"PROPOSED RETIREMENT: {row.get('_proposed_discontinue_date', 'TBD')}")
    if row.get("_vocab_pending"):
        parts.append(f"UNKNOWN DELOITTE TERMS -- clarification needed: {row.get('_vocab_pending', '')}")
    return " | ".join(parts) if parts else "No issues detected"


def _operations_rec(row: pd.Series) -> str:
    scope  = str(row.get("_scope", "Review"))
    retire = bool(row.get("_retire_flag", False))
    is_reg = bool(row.get("_is_regulatory", False))

    if is_reg:
        return "Keep active. Regulatory course -- any discontinuation must be approved by L&D leadership."
    if scope == "In-Scope":
        return "Keep active. Update any missing metadata (Category, Vendor, Business Owner) before Eightfold export."
    if scope == "Out-of-Scope" and retire:
        return (
            f"Propose retirement by {row.get('_proposed_discontinue_date', 'TBD')}. "
            "Zero completions across FY24-FY26. Confirm with course owner before discontinuing."
        )
    if scope == "Review":
        return "Human review required. Confirm future need with course owner before any status change."
    return "Review required."


# -- Column selection for queue exports --

_QUEUE_COLS = [
    "ActiveCourseID", "Course Number",
    "Course Title", "Mandatory Field: Course Title",
    "_scope", "_scope_score", "_scope_rationale",
    "_is_assessment", "_is_regulatory", "_regulatory_topics",
    "_retire_flag", "_proposed_discontinue_date", "_sunset_rationale",
    "_clean_title", "_title_change_type", "_title_confidence",
    "_description_placeholder", "_description_mismatch", "_description_missing",
    "_description_change_summary",
    "_clean_vendor", "_vendor_confidence", "_vendor_change_type",
    "_business_line", "_bl_confidence",
    "_vocab_pending", "_vocab_flags",
    "_encoding_issues",
    "_hitl_queues", "MF Comments", "Operations Recommendation",
]


# -- Main --

def write(df: pd.DataFrame, output_dir: str = "data/output") -> tuple[pd.DataFrame, dict]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    df = df.copy()
    df["_pipeline_run_id"] = RUN_ID
    df["_pipeline_run_ts"] = RUN_TS

    # Assign queues
    df["_hitl_queues"] = df.apply(lambda r: ", ".join(_assign_queues(r)), axis=1)

    # Eightfold export blocker
    df["_eightfold_blocked"] = (
        df.get("_description_missing",     pd.Series(False, index=df.index)).astype(bool)
        | df.get("_description_placeholder", pd.Series(False, index=df.index)).astype(bool)
        | (df.get("_clean_vendor", pd.Series("Unknown", index=df.index)).astype(str) == "Unknown")
    )

    # Populate action columns
    df["MF Comments"]             = df.apply(_mf_comments, axis=1)
    df["Operations Recommendation"] = df.apply(_operations_rec, axis=1)

    # -- Write proposals Excel --
    proposals_path = out / "catalog_with_proposals.xlsx"
    df.to_excel(proposals_path, index=False)
    print(f"[ChangeSetWriter] [OK] {proposals_path}")

    # -- Write HITL queues --
    queues_dir = out / "hitl_queues"
    queues_dir.mkdir(exist_ok=True)

    # Discover all queue names dynamically from the data (includes Q_Other + any AI queues)
    all_queues_ordered = [
        "Q1_HighRiskRetirement", "Q2_RegulatoryOverride", "Q3_VendorRemap",
        "Q4_BLMapping",          "Q5_Translation",        "Q5b_DescriptionRequired",
        "Q5c_DescriptionMismatch", "Q6_LowConfidenceScope", "Q7_VocabClarification",
    ]
    # Add any queues found in the data that aren't in the canonical list
    extra_queues: list[str] = []
    for cell in df["_hitl_queues"].dropna().astype(str):
        for q in cell.split(","):
            q = q.strip()
            if q and q not in all_queues_ordered and q not in extra_queues:
                extra_queues.append(q)
    # Q_Other always last
    if "Q_Other" in extra_queues:
        extra_queues.remove("Q_Other")
        extra_queues.append("Q_Other")
    all_queues = all_queues_ordered + extra_queues

    queue_summary: dict[str, int] = {}
    present_cols = [c for c in _QUEUE_COLS if c in df.columns]

    for qname in all_queues:
        mask  = df["_hitl_queues"].str.contains(qname, na=False)
        count = int(mask.sum())
        queue_summary[qname] = count
        if count == 0:
            continue
        records = df.loc[mask, present_cols].to_dict(orient="records")
        q_path  = queues_dir / f"{qname}.json"
        with open(q_path, "w", encoding="utf-8") as f:
            json.dump(
                {"queue": qname, "run_id": RUN_ID, "count": count, "items": records},
                f, indent=2, default=str,
            )
        print(f"[ChangeSetWriter]   {qname}: {count} items -> {q_path.name}")

    # -- Write audit log --
    audit_path = out / "changeset_audit_log.jsonl"
    with open(audit_path, "w", encoding="utf-8") as f:
        for _, row in df.iterrows():
            record = {
                "run_id":   RUN_ID,
                "run_ts":   RUN_TS,
                "course_id": str(row.get("ActiveCourseID", row.get("Course Number", "")) or ""),
                "proposed_changes": {
                    "scope":                   str(row.get("_scope", "")),
                    "scope_score":             float(row.get("_scope_score", 0) or 0),
                    "retire_flag":             bool(row.get("_retire_flag", False)),
                    "proposed_disc_date":      str(row.get("_proposed_discontinue_date", "") or ""),
                    "clean_title":             str(row.get("_clean_title", "") or ""),
                    "title_change_type":       str(row.get("_title_change_type", "") or ""),
                    "description_placeholder": bool(row.get("_description_placeholder", False)),
                    "description_mismatch":    bool(row.get("_description_mismatch", False)),
                    "clean_vendor":            str(row.get("_clean_vendor", "") or ""),
                    "business_line":           str(row.get("_business_line", "") or ""),
                    "is_regulatory":           bool(row.get("_is_regulatory", False)),
                    "is_assessment":           bool(row.get("_is_assessment", False)),
                    "eightfold_blocked":       bool(row.get("_eightfold_blocked", False)),
                },
                "hitl_queues": str(row.get("_hitl_queues", "")),
            }
            f.write(json.dumps(record, default=str) + "\n")
    print(f"[ChangeSetWriter] [OK] {audit_path}")

    return df, queue_summary
