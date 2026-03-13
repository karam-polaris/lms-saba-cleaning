"""Agent 10 -- VocabResolver

Scans titles and descriptions for Deloitte-specific abbreviations, course codes,
and proprietary terms.  For each matched term:
  - Appends a plain-language definition to _enriched_description (feeds Eightfold AI)
  - Stores resolved definitions in _vocab_definitions
  - Stores unresolved terms in _vocab_pending -> HITL: Q7_VocabClarification

This agent learns iteratively: reviewers add new terms to deloitte_vocab.json
and the next run picks them up automatically.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

# Course-code pattern: 2-4 uppercase letters + 2-4 digits + optional suffix
CODE_RE = re.compile(r"\b([A-Z]{2,4}\d{2,4}[A-Za-z0-9\-]*)\b")

# Known acronyms / proper-noun terms to scan for
ACRONYM_RE = re.compile(
    r"\b(ISA\s*\d+\w*|IFRS\s*S?\d*\w*|RPM|GLAS|JET"
    r"|Levvia|Omnia|PSAS|O2E|Ascend"
    r"|Independence\s+Matters|PRIV|PUB|PCAOB|CPE|ESG"
    r"|PSAB|FINTRAC|PIPEDA|GDPR|TCFD|ISSB)\b",
    re.IGNORECASE,
)

_VOCAB_CACHE: dict | None = None


def _load_vocab(config_path: str) -> dict[str, str]:
    global _VOCAB_CACHE
    if _VOCAB_CACHE is None:
        p = Path(config_path)
        _VOCAB_CACHE = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _VOCAB_CACHE


def _lookup(term: str, vocab: dict[str, str]) -> str | None:
    t = term.strip()
    # Exact
    if t in vocab:
        return vocab[t]
    # Case-insensitive exact
    t_lower = t.lower()
    for k, v in vocab.items():
        if k.lower() == t_lower:
            return v
    # Prefix match (e.g. "TE610A" -> key "TE610")
    for k, v in vocab.items():
        if t_lower.startswith(k.lower()) and len(k) >= 2:
            return v
    return None


def resolve(
    df: pd.DataFrame,
    config_path: str = "config/deloitte_vocab.json",
) -> pd.DataFrame:
    vocab = _load_vocab(config_path)

    title_col = next(
        (c for c in ["_clean_title", "Course Title", "Mandatory Field: Course Title"]
         if c in df.columns), None
    )
    desc_col = "_clean_description" if "_clean_description" in df.columns else "Catalog Item Description"

    all_flags, all_defs, all_pending, enriched = [], [], [], []

    for _, row in df.iterrows():
        title = str(row.get(title_col, "") or "") if title_col else ""
        desc  = str(row.get(desc_col,  "") or "")

        # Scan title for course codes, combined for acronyms
        codes   = CODE_RE.findall(title)
        acronyms = ACRONYM_RE.findall(f"{title} {desc}")
        all_terms = list(dict.fromkeys(codes + acronyms))  # preserve order, dedup

        flags, definitions, pending = [], {}, []

        for term in all_terms:
            defn = _lookup(term, vocab)
            if defn:
                definitions[term] = defn
                flags.append(term)
            else:
                pending.append(term)

        # Enrich description with context block (powers Eightfold skill matching)
        base_desc = desc
        if definitions:
            ctx = "; ".join(f"{k}: {v}" for k, v in definitions.items())
            if base_desc.strip():
                base_desc = base_desc.rstrip() + " | Deloitte context: " + ctx
            else:
                base_desc = "Deloitte context: " + ctx

        all_flags.append(", ".join(flags) if flags else "")
        all_defs.append(json.dumps(definitions, ensure_ascii=False) if definitions else "")
        all_pending.append(", ".join(pending) if pending else "")
        enriched.append(base_desc)

    df = df.copy()
    df["_vocab_flags"]         = all_flags
    df["_vocab_definitions"]   = all_defs
    df["_vocab_pending"]       = all_pending
    df["_enriched_description"] = enriched
    return df
