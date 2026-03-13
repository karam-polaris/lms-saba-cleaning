"""Agent 8 -- VendorResolver

Normalises course vendor names using:
  1. Exact alias dictionary lookup
  2. Fuzzy matching (rapidfuzz token_sort_ratio)

Resolution types:
  Alias     -> confidence 1.00 (from dict)
  FuzzyHigh -> confidence ≥ 0.85 (auto-accept)
  FuzzyMed  -> confidence 0.70-0.84 (proposed, HITL: Vendor Remap)
  Unknown   -> confidence < 0.70 (kept raw, HITL: Vendor Remap)
  Missing   -> vendor null/empty -> "Unknown"
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

try:
    from rapidfuzz import fuzz, process as rfprocess
    _RAPIDFUZZ_OK = True
except ImportError:
    _RAPIDFUZZ_OK = False

HIGH_CONF = 85
MED_CONF  = 70

_ALIASES: dict | None = None


def _load_aliases(config_path: str) -> dict[str, str]:
    global _ALIASES
    if _ALIASES is None:
        p = Path(config_path)
        _ALIASES = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _ALIASES


def resolve(
    df: pd.DataFrame,
    config_path: str = "config/vendor_alias_dict.json",
) -> pd.DataFrame:
    aliases        = _load_aliases(config_path)
    controlled     = list(set(v for v in aliases.values() if v not in ("Unknown", "")))

    vendor_col = "Course Vendor Name" if "Course Vendor Name" in df.columns else None
    if vendor_col is None:
        return df

    clean_vendors, confs, types_ = [], [], []

    for _, row in df.iterrows():
        raw = str(row.get(vendor_col, "") or "").strip()

        if not raw or raw in ("None", "N/A", "nan"):
            clean_vendors.append("Unknown")
            confs.append(0.0)
            types_.append("Missing")
            continue

        # Exact alias lookup
        if raw in aliases:
            clean_vendors.append(aliases[raw])
            confs.append(1.0)
            types_.append("Alias")
            continue

        # Case-insensitive exact lookup
        raw_lower = raw.lower()
        matched_key = next((k for k in aliases if k.lower() == raw_lower), None)
        if matched_key:
            clean_vendors.append(aliases[matched_key])
            confs.append(1.0)
            types_.append("Alias")
            continue

        # Fuzzy match
        if _RAPIDFUZZ_OK and controlled:
            result = rfprocess.extractOne(raw, controlled, scorer=fuzz.token_sort_ratio)
            if result:
                match_str, score, _ = result
                if score >= HIGH_CONF:
                    clean_vendors.append(match_str)
                    confs.append(round(score / 100, 3))
                    types_.append("FuzzyHigh")
                elif score >= MED_CONF:
                    clean_vendors.append(match_str)
                    confs.append(round(score / 100, 3))
                    types_.append("FuzzyMed")
                else:
                    clean_vendors.append(raw)
                    confs.append(round(score / 100, 3))
                    types_.append("Unknown")
                continue

        clean_vendors.append(raw)
        confs.append(0.0)
        types_.append("Unknown")

    df = df.copy()
    df["_clean_vendor"]        = clean_vendors
    df["_vendor_confidence"]   = confs
    df["_vendor_change_type"]  = types_
    return df
