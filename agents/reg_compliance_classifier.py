"""Agent 3 -- RegComplianceClassifier

Flags courses covering regulatory/compliance topics and protects them
from automated retirement.

Confidence:
  CPE Hours > 0         -> 0.95 (hard signal)
  Keyword match         -> 0.90
  < 0.75                -> route to HITL: Regulatory Override queue
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

_KEYWORD_CACHE: dict | None = None


def _load_keywords(config_path: str) -> dict[str, list[str]]:
    global _KEYWORD_CACHE
    if _KEYWORD_CACHE is None:
        with open(config_path, encoding="utf-8") as f:
            _KEYWORD_CACHE = json.load(f)
    return _KEYWORD_CACHE


def _match_topics(text: str, keyword_map: dict[str, list[str]]) -> list[str]:
    text_lower = text.lower()
    return [
        topic
        for topic, kws in keyword_map.items()
        if any(kw.lower() in text_lower for kw in kws)
    ]


def detect(
    df: pd.DataFrame,
    config_path: str = "config/regulatory_keywords.json",
) -> pd.DataFrame:
    keywords = _load_keywords(config_path)

    title_col = next((c for c in ["Course Title", "Mandatory Field: Course Title"] if c in df.columns), None)
    desc_col  = "Catalog Item Description" if "Catalog Item Description" in df.columns else None
    cpe_area_col = "Cpe Subject Area" if "Cpe Subject Area" in df.columns else None
    cpe_hrs_col  = "Cpe Hours"         if "Cpe Hours"         in df.columns else None
    cat_col   = "Course Category"   if "Course Category"   in df.columns else None

    is_reg_list, topics_list, conf_list = [], [], []

    for _, row in df.iterrows():
        title    = str(row.get(title_col,    "") or "") if title_col    else ""
        desc     = str(row.get(desc_col,     "") or "") if desc_col     else ""
        cpe_area = str(row.get(cpe_area_col, "") or "") if cpe_area_col else ""
        category = str(row.get(cat_col,      "") or "") if cat_col      else ""
        combined = f"{title} {desc} {cpe_area} {category}"

        matched = _match_topics(combined, keywords)

        # CPE hours signal
        cpe_hrs = float(row.get(cpe_hrs_col, 0) or 0) if cpe_hrs_col else 0
        if cpe_hrs > 0 or cpe_area.strip():
            if "CPE_Required" not in matched:
                matched.append("CPE_Required")

        is_reg = len(matched) > 0
        confidence = 0.95 if cpe_hrs > 0 else (0.90 if matched else 0.0)

        is_reg_list.append(is_reg)
        topics_list.append(", ".join(matched))
        conf_list.append(round(confidence, 3))

    df = df.copy()
    df["_is_regulatory"]          = is_reg_list
    df["_regulatory_topics"]      = topics_list
    df["_regulatory_confidence"]  = conf_list
    return df
