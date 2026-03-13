"""Agent 9 -- BLMapper

Maps each course to a Business Line using:
  1. Domain exact match      (confidence 0.95)
  2. Classification match    (confidence 0.88)
  3. Keyword/topic match     (confidence 0.85)
  4. No match -> "Unknown"   (confidence 0.00 -> HITL: BL Mapping)

Business Lines: Audit/A&A | Tax | Consulting | Advisory | Enabling Areas | Cross-LoS
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

UNKNOWN = "Unknown"

_RULES: dict | None = None


def _load_rules(config_path: str) -> dict:
    global _RULES
    if _RULES is None:
        p = Path(config_path)
        _RULES = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _RULES


def _contains_any(text: str, items: list[str]) -> bool:
    t = text.lower()
    return any(item.lower() in t for item in items)


def map_bl(
    df: pd.DataFrame,
    config_path: str = "config/bl_rules.json",
) -> pd.DataFrame:
    rules     = _load_rules(config_path)
    title_col = next(
        (c for c in ["_clean_title", "Course Title", "Mandatory Field: Course Title"]
         if c in df.columns), None
    )

    bls, confs = [], []

    for _, row in df.iterrows():
        title          = str(row.get(title_col,            "") or "") if title_col else ""
        category       = str(row.get("Course Category",   "") or "")
        classification = str(row.get("Course Classification", "") or "")
        domain         = str(row.get("Reference: Domain", "") or "")
        cpe_area       = str(row.get("Cpe Subject Area",  "") or "")
        combined       = f"{title} {category} {classification} {domain} {cpe_area}"

        best_bl   = UNKNOWN
        best_conf = 0.0

        for bl_name, rule in rules.items():
            # Priority 1: Domain exact
            if _contains_any(domain, rule.get("domains", [])):
                if best_conf < 0.95:
                    best_bl, best_conf = bl_name, 0.95

            # Priority 2: Classification match
            if _contains_any(classification, rule.get("classifications", [])):
                if best_conf < 0.88:
                    best_bl, best_conf = bl_name, 0.88

            # Priority 3: Keyword match in combined text
            kws = rule.get("keywords", [])
            if _contains_any(combined, kws) and 0.85 > best_conf:
                best_bl, best_conf = bl_name, 0.85

        bls.append(best_bl)
        confs.append(round(best_conf, 3))

    df = df.copy()
    df["_business_line"] = bls
    df["_bl_confidence"] = confs
    return df
