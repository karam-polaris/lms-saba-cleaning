"""Agent 6 -- TitleNormalizer

Cleans course titles:
  1. Removes placeholder words (PRUEBA, DRAFT, TEST, TBD…)
  2. Strips version noise (v2, _COPY, Final, - 2024…)
  3. Applies title-case for English titles (preserving known acronyms)
  4. Detects language (non-English titles not rewritten)
  5. Trims to ≤ 100 characters

Confidence < 0.70 or title length change > 30% -> HITL: Title Review
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

try:
    import langdetect
    _LANGDETECT_OK = True
except ImportError:
    _LANGDETECT_OK = False

_CONFIG: dict | None = None


def _load_config(config_path: str) -> dict:
    global _CONFIG
    if _CONFIG is None:
        p = Path(config_path)
        _CONFIG = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _CONFIG


def _build_placeholder_re(words: list[str]) -> re.Pattern:
    pat = r"\b(" + "|".join(re.escape(w) for w in words) + r")\b"
    return re.compile(pat, re.IGNORECASE)


def _build_version_re() -> re.Pattern:
    return re.compile(
        r"[\s\-\u2013\u2014_]*(v\s*\d+(\.\d+)?"
        r"|final|new|copy|_copy"
        r"|\u2013?\s*20\d{2}"  # - 2024 style
        r"|\(copy\))\s*$",
        re.IGNORECASE,
    )


def _detect_language(text: str) -> str:
    if not _LANGDETECT_OK or not text or len(text.strip()) < 8:
        return "unknown"
    try:
        return langdetect.detect(text)
    except Exception:
        return "unknown"


def _to_title_case(text: str, acronyms: set[str]) -> str:
    SMALL_WORDS = {
        "a", "an", "the", "in", "on", "at", "for", "to", "of",
        "and", "or", "but", "de", "la", "el", "en", "y", "e",
    }
    words  = text.split()
    result = []
    for i, word in enumerate(words):
        clean = re.sub(r"[^A-Za-z&]", "", word).upper()
        if clean in acronyms:
            result.append(word)          # preserve exactly
        elif i == 0 or word.lower() not in SMALL_WORDS:
            result.append(word.capitalize())
        else:
            result.append(word.lower())
    return " ".join(result)


def normalize(
    df: pd.DataFrame,
    config_path: str = "config/title_normalization_rules.json",
) -> pd.DataFrame:
    cfg      = _load_config(config_path)
    acronyms = set(cfg.get("protected_acronyms", []))
    ph_re    = _build_placeholder_re(cfg.get("placeholder_words", ["PRUEBA", "DRAFT", "TEST", "TBD"]))
    ver_re   = _build_version_re()

    title_col = next(
        (c for c in ["Course Title", "Mandatory Field: Course Title"] if c in df.columns),
        None,
    )
    if title_col is None:
        return df

    clean_titles, change_types, confidences, langs = [], [], [], []

    for _, row in df.iterrows():
        original = str(row.get(title_col, "") or "").strip()
        title    = original
        changes  = []

        # 1. Placeholder removal
        if ph_re.search(title):
            title = ph_re.sub("", title).strip(" \u2013\u2014-_")
            changes.append("Placeholder")

        # 2. Version noise
        if ver_re.search(title):
            title = ver_re.sub("", title).strip()
            changes.append("Versioning")

        # 3. Language detection
        lang = _detect_language(title)

        # 4. Title-case (English only)
        if lang in ("en", "unknown") and title:
            cased = _to_title_case(title, acronyms)
            if cased != title:
                title = cased
                changes.append("Case")

        # 5. Trim
        if len(title) > 100:
            title = title[:97].rstrip() + "…"
            changes.append("Trim")

        change_type = "+".join(changes) if changes else "NoChange"

        # Confidence
        if "Placeholder" in changes:
            conf = 0.60
        elif changes:
            conf = 0.92
        else:
            conf = 1.0

        # Flag large changes for HITL
        orig_len = len(original)
        if orig_len > 0 and abs(len(title) - orig_len) / orig_len > 0.30:
            conf = min(conf, 0.65)

        clean_titles.append(title)
        change_types.append(change_type)
        confidences.append(round(conf, 3))
        langs.append(lang)

    df = df.copy()
    df["_clean_title"]       = clean_titles
    df["_title_change_type"] = change_types
    df["_title_confidence"]  = confidences
    df["_title_language"]    = langs
    return df
