"""Agent 7 -- DescriptionSanitizer

Cleans catalog item descriptions:
  1. Strips HTML tags (preserving paragraph text)
  2. Removes MS-Word artifacts (MsoNormal, nbsp, etc.)
  3. Detects generic placeholder descriptions (blocks Eightfold export)
  4. Detects title/description topic mismatches via word overlap
  5. Detects language; flags non-English for translation routing

PoC findings embedded as constants:
  - 43/150 rows use exact EN boilerplate -> _description_placeholder = True
  - 20/150 rows have ISA 600R audit desc on non-audit course -> _description_mismatch = True
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import pandas as pd
from bs4 import BeautifulSoup

try:
    import langdetect
    _LANGDETECT_OK = True
except ImportError:
    _LANGDETECT_OK = False

# -- Known boilerplate strings (confirmed from PoC) --
PLACEHOLDER_EXACT: set[str] = {
    "This course is designed to enable practitioners to apply best practices.",
    "Curso diseñado para habilitar a los profesionales a aplicar mejores prácticas.",
    # encoding-corrupted variant
    "Curso dise\ufffdado para habilitar a los profesionales a aplicar mejores pr\ufffdcticas.",
}

PLACEHOLDER_FUZZY_THRESHOLD = 0.88   # SequenceMatcher ratio

MISMATCH_JACCARD_THRESHOLD  = 0.08   # word overlap below this -> suspect mismatch
MIN_DESC_LENGTH = 20                 # shorter than this -> treat as missing


# -- HTML cleaning --

def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(separator=" ")
    # Remove residual MS-Word / HTML artifacts
    text = re.sub(r"\bMsoNormal\b", "", text)
    text = re.sub(r"&nbsp;|&amp;|&lt;|&gt;|&quot;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# -- Placeholder detection --

def _is_placeholder(text: str) -> bool:
    stripped = text.strip()
    if stripped in PLACEHOLDER_EXACT:
        return True
    for ph in PLACEHOLDER_EXACT:
        if SequenceMatcher(None, stripped.lower(), ph.lower()).ratio() >= PLACEHOLDER_FUZZY_THRESHOLD:
            return True
    return False


# -- Mismatch detection (word-level Jaccard) --

def _jaccard(a: str, b: str) -> float:
    def tokens(s: str) -> set[str]:
        return set(re.sub(r"[^\w\s]", "", s.lower()).split()) - {
            "the", "a", "an", "is", "in", "on", "at", "to", "of", "and",
            "or", "for", "this", "that", "with", "be", "are", "was",
            "course", "courses", "de", "la", "el", "en", "y", "los",
        }
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# -- Language detection --

def _detect_lang(text: str) -> str:
    if not _LANGDETECT_OK or not text or len(text.strip()) < 15:
        return "unknown"
    try:
        return langdetect.detect(text)
    except Exception:
        return "unknown"


# -- Main --

def sanitize(df: pd.DataFrame) -> pd.DataFrame:
    desc_col  = "Catalog Item Description"  if "Catalog Item Description"  in df.columns else None
    title_col = next(
        (c for c in ["_clean_title", "Course Title", "Mandatory Field: Course Title"]
         if c in df.columns), None
    )

    clean_descs, langs, trans_needed = [], [], []
    is_placeholder_list, is_mismatch_list, is_missing_list = [], [], []
    summaries = []

    for _, row in df.iterrows():
        raw   = str(row.get(desc_col, "") or "") if desc_col else ""
        title = str(row.get(title_col, "") or "") if title_col else ""
        changes = []

        # 1. Strip HTML
        clean = _strip_html(raw)
        if raw.strip() != clean.strip() and raw.strip():
            changes.append("HTML stripped")

        # 2. Placeholder check
        placeholder = _is_placeholder(clean)
        if placeholder:
            changes.append("Placeholder detected -- blocks Eightfold export")

        # 3. Missing check
        missing = placeholder or len(clean.strip()) < MIN_DESC_LENGTH

        # 4. Language detection
        lang = _detect_lang(clean) if not missing else "unknown"
        needs_trans = lang not in ("en", "unknown") and not missing

        # 5. Mismatch check (only meaningful when both fields have content)
        mismatch = False
        if title.strip() and clean.strip() and not placeholder and len(clean.strip()) >= MIN_DESC_LENGTH:
            sim = _jaccard(title, clean)
            if sim < MISMATCH_JACCARD_THRESHOLD:
                mismatch = True
                changes.append(f"Topic mismatch (word overlap={sim:.2f}) -- description may belong to different course")

        clean_descs.append(clean if not missing else "")
        langs.append(lang)
        trans_needed.append(needs_trans)
        is_placeholder_list.append(placeholder)
        is_mismatch_list.append(mismatch)
        is_missing_list.append(missing)
        summaries.append("; ".join(changes) if changes else "NoChange")

    df = df.copy()
    df["_clean_description"]        = clean_descs
    df["_description_language"]     = langs
    df["_translation_needed"]       = trans_needed
    df["_description_placeholder"]  = is_placeholder_list
    df["_description_mismatch"]     = is_mismatch_list
    df["_description_missing"]      = is_missing_list
    df["_description_change_summary"] = summaries
    return df
