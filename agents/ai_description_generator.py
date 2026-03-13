"""AI Agent — Description Generator

Uses GPT-5.4-pro (reasoning_effort=high) to draft professional course descriptions
for courses that have:
  - A placeholder description ("This course is designed to enable…")
  - An empty / missing description
  - A topic-mismatched description

Processes up to BATCH_SIZE courses per API call to minimise cost and latency.
All outputs are proposals — they land in Q_AIDescription HITL queue.
The human must Approve / Edit / Reject before anything is treated as final.

Architecture note:
  _ai_description_draft      str   — AI-proposed description text
  _ai_description_rationale  str   — model's reasoning for its choices
  _ai_description_confidence float — 0.0–1.0 self-assessed quality
  _ai_description_tokens     int   — tokens used for cost tracking
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

BATCH_SIZE = 15   # courses per API call

SYSTEM_PROMPT = """You are a senior Learning & Development curriculum specialist at a Big Four \
professional services firm. Your job is to write accurate, professional course descriptions for \
an internal learning catalog that feeds into an AI skill-matching platform (Eightfold AI).

Rules:
1. Be factual — only use information given to you.
2. Do NOT start with "This course is designed to…", "This course will…", or any filler opening.
3. Write 2–3 sentences: what the course covers, who it is for, and the key skill or outcome.
4. If the course code contains recognisable professional abbreviations \
(e.g. TE=Tax/Emerging issues, CG=Corporate Governance, AUD=Audit, \
ISA=International Standards on Auditing, PSAS=Public Sector Accounting Standards, \
IFRS=International Financial Reporting Standards, CPE=Continuing Professional Education), \
use them as context clues.
5. If you see "– Assessment" or a code ending in A, this is a knowledge-check assessment, \
not a teaching course.
6. Be concise: 40–80 words per description.
7. Use plain professional English. No marketing language.

Respond ONLY with valid JSON — no markdown, no prose outside the JSON:
{
  "results": [
    {
      "index": <integer from input>,
      "description": "<2-3 sentence description>",
      "rationale": "<1 sentence explaining what signals you used>",
      "confidence": <float 0.0–1.0>
    }
  ]
}"""


def _build_prompt(batch: list[dict]) -> str:
    lines = ["Generate descriptions for these courses:\n"]
    for item in batch:
        lines.append(f"[{item['index']}]")
        lines.append(f"  Title:          {item.get('title', '')}")
        lines.append(f"  Course Number:  {item.get('course_number', '')}")
        lines.append(f"  Classification: {item.get('classification', '')}")
        lines.append(f"  Category:       {item.get('category', '')}")
        lines.append(f"  Domain:         {item.get('domain', '')}")
        lines.append(f"  CPE Subject:    {item.get('cpe_subject', '')}")
        lines.append(f"  Learning Hours: {item.get('hours', '')}")
        lines.append(f"  Delivery:       {item.get('delivery', '')}")
        lines.append(f"  Vendor:         {item.get('vendor', '')}")
        lines.append(f"  Is Assessment:  {item.get('is_assessment', False)}")
        lines.append("")
    return "\n".join(lines)


def _uses_responses_api(model: str) -> bool:
    """gpt-5.x-pro and o-series require the Responses API. gpt-4.x uses Chat Completions."""
    m = model.lower()
    if any(m.startswith(p) for p in ("gpt-4", "gpt-3")):
        return False
    if any(p in m for p in ("o1", "o3", "o4")):
        return True
    if "5." in m or m.startswith("gpt-5"):
        return True
    return False   # default to Chat Completions


def _call_api(client: Any, prompt: str, model: str,
              reasoning_effort: str) -> tuple[list[dict], int]:
    """Route to Responses API (gpt-5.x-pro, o-series) or Chat Completions (gpt-4.x)."""
    input_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]

    if _uses_responses_api(model):
        response = client.responses.create(
            model=model,
            reasoning={"effort": reasoning_effort},
            input=input_messages,
        )
        tokens = response.usage.total_tokens if hasattr(response, "usage") and response.usage else 0
        raw = (response.output_text or "{}").strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
    else:
        response = client.chat.completions.create(
            model=model,
            messages=input_messages,
            response_format={"type": "json_object"},
        )
        tokens = response.usage.total_tokens if response.usage else 0
        raw = response.choices[0].message.content or "{}"

    try:
        data = json.loads(raw)
        return data.get("results", []), tokens
    except json.JSONDecodeError:
        return [], tokens


def generate(df: pd.DataFrame,
             model: str | None = None,
             reasoning_effort: str | None = None,
             progress_callback=None) -> pd.DataFrame:
    """
    progress_callback(batches_done: int, batches_total: int, courses_done: int, courses_total: int)
    Called after each batch completes so the UI can update.
    """
    """
    Generate AI descriptions for courses that need them.
    Adds columns:
      _ai_description_draft, _ai_description_rationale,
      _ai_description_confidence, _ai_description_tokens
    Returns df with these columns added.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        df = df.copy()
        for col in ("_ai_description_draft", "_ai_description_rationale",
                    "_ai_description_confidence", "_ai_description_tokens"):
            df[col] = "" if "draft" in col or "rationale" in col else 0.0
        return df

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except ImportError:
        df = df.copy()
        for col in ("_ai_description_draft", "_ai_description_rationale",
                    "_ai_description_confidence", "_ai_description_tokens"):
            df[col] = "" if "draft" in col or "rationale" in col else 0.0
        return df

    _model   = model or os.getenv("OPENAI_MODEL_GENERATION", "gpt-5.4-pro")
    _effort  = reasoning_effort or os.getenv("OPENAI_REASONING_EFFORT", "high")

    df = df.copy()
    df["_ai_description_draft"]      = ""
    df["_ai_description_rationale"]  = ""
    df["_ai_description_confidence"] = 0.0
    df["_ai_description_tokens"]     = 0

    # Identify which courses need a description
    needs_mask = (
        df.get("_description_placeholder", pd.Series(False, index=df.index)).astype(bool)
        | df.get("_description_missing", pd.Series(False, index=df.index)).astype(bool)
        | df.get("_description_mismatch", pd.Series(False, index=df.index)).astype(bool)
    )
    target_idx = df[needs_mask].index.tolist()

    if not target_idx:
        return df

    # Column name resolution
    title_col = next((c for c in ["_clean_title", "Course Title",
                                   "Mandatory Field: Course Title"] if c in df.columns), None)

    def _get(row: pd.Series, *keys: str, default: str = "") -> str:
        for k in keys:
            v = str(row.get(k, "") or "").strip()
            if v:
                return v
        return default

    # Build batch items
    items = []
    for local_i, idx in enumerate(target_idx):
        row = df.loc[idx]
        items.append({
            "index":          local_i,
            "title":          _get(row, title_col or "") if title_col else "",
            "course_number":  _get(row, "Course Number"),
            "classification": _get(row, "Course Classification"),
            "category":       _get(row, "Course Category"),
            "domain":         _get(row, "Reference: Domain", "Domain"),
            "cpe_subject":    _get(row, "Cpe Subject Area"),
            "hours":          _get(row, "Learning Hours"),
            "delivery":       _get(row, "Full Delivery Type"),
            "vendor":         _get(row, "_clean_vendor", "Course Vendor Name"),
            "is_assessment":  bool(row.get("_is_assessment", False)),
        })

    # Process in batches
    result_map: dict[int, dict] = {}
    total_tokens = 0
    n_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num, batch_start in enumerate(range(0, len(items), BATCH_SIZE)):
        batch = items[batch_start: batch_start + BATCH_SIZE]
        prompt = _build_prompt(batch)
        try:
            results, tokens = _call_api(client, prompt, _model, _effort)
            total_tokens += tokens
            for r in results:
                local_i = r.get("index")
                if local_i is not None:
                    result_map[local_i] = r
        except Exception as exc:
            print(f"[AI DescGen] API error batch {batch_start}: {exc}")

        if progress_callback:
            courses_done = min(batch_start + BATCH_SIZE, len(items))
            progress_callback(batch_num + 1, n_batches, courses_done, len(items))

    # Write results back to df
    for local_i, idx in enumerate(target_idx):
        r = result_map.get(local_i, {})
        df.at[idx, "_ai_description_draft"]      = r.get("description", "")
        df.at[idx, "_ai_description_rationale"]  = r.get("rationale", "")
        df.at[idx, "_ai_description_confidence"] = float(r.get("confidence", 0.0))
        df.at[idx, "_ai_description_tokens"]     = total_tokens // max(len(target_idx), 1)

    print(f"[AI DescGen] Generated {len(result_map)} descriptions | "
          f"{len(target_idx)} needed | {total_tokens} tokens | model={_model}")
    return df
