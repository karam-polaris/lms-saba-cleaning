"""AI Agent — Vocabulary Researcher

Uses GPT-5.4-pro (reasoning_effort=high) to research unknown Deloitte-specific
abbreviations and course codes, and propose plain-language definitions.

All proposed definitions are treated as DRAFTS — they land in a HITL queue
and must be validated by a human before being saved to deloitte_vocab.json.

Architecture note:
  _ai_vocab_proposals  dict[term -> {definition, rationale, confidence, needs_human}]
                       stored as JSON string on the first row of df only (it's a
                       dataset-level result, not per-row).

Per-row columns added:
  _ai_vocab_draft_definitions  str  — JSON: {term: proposed_definition, ...} for terms
                                       found on this specific course
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SYSTEM_PROMPT = """You are a professional services knowledge specialist with deep expertise in \
Big Four accounting, audit, tax, and consulting. Your task is to research Deloitte-specific \
course codes and abbreviations found in an internal learning catalog, and propose \
plain-language definitions so that an AI skill-matching platform (Eightfold AI) can \
understand what each course covers.

Rules:
1. Be factual. Only assert things you know to be true in the professional services / \
accounting / audit context. Do NOT invent firm-specific details.
2. If a term is likely a Deloitte internal course code (e.g. TE610, CG903Re), describe \
the most probable topic based on the prefix and any known standards.
3. If you are uncertain, say so explicitly and set needs_human_validation=true.
4. Definitions should be 1–2 sentences, plain English, suitable for appending to a \
course description.
5. Source: cite the standard, regulation, or professional body if applicable.

Respond ONLY with valid JSON:
{
  "results": [
    {
      "term": "<exact term>",
      "definition": "<1-2 sentence plain-language definition>",
      "rationale": "<brief note on how you derived this>",
      "confidence": <float 0.0-1.0>,
      "needs_human_validation": <true if uncertain>,
      "source": "<standard / body / 'Deloitte internal' if unknown>"
    }
  ]
}"""


def _call_api(client: Any, terms_with_context: list[dict],
              model: str, reasoning_effort: str) -> tuple[list[dict], int]:
    lines = ["Research these terms found in a professional services learning catalog:\n"]
    for item in terms_with_context:
        lines.append(f"Term: \"{item['term']}\"")
        if item.get("courses"):
            lines.append(f"  Appears in courses: {', '.join(item['courses'][:3])}")
        if item.get("domains"):
            lines.append(f"  Domains/categories: {', '.join(item['domains'][:3])}")
        lines.append("")

    prompt = "\n".join(lines)
    input_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]

    # Route to correct API based on model
    is_responses = any(model.lower().startswith(p) for p in ("gpt-5", "o1", "o3", "o4"))

    if is_responses:
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


def research(df: pd.DataFrame,
             model: str | None = None,
             reasoning_effort: str | None = None) -> pd.DataFrame:
    """
    Research unknown Deloitte vocabulary terms using AI.
    Adds dataset-level column:
      _ai_vocab_proposals  str (JSON) — dict of term -> proposal dict
    Returns df with this column added.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    df = df.copy()
    df["_ai_vocab_proposals"] = ""

    if not api_key:
        return df

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except ImportError:
        return df

    _model  = model or os.getenv("OPENAI_MODEL_REASONING", "gpt-5.4-pro")
    _effort = reasoning_effort or os.getenv("OPENAI_REASONING_EFFORT", "high")

    # Collect unknown terms from _vocab_pending column
    title_col = next((c for c in ["_clean_title", "Course Title",
                                   "Mandatory Field: Course Title"] if c in df.columns), None)

    term_context: dict[str, dict] = {}   # term -> {courses: [], domains: []}

    if "_vocab_pending" in df.columns:
        for _, row in df.iterrows():
            pending = str(row.get("_vocab_pending", "") or "")
            if not pending.strip():
                continue
            title = str(row.get(title_col, "") or "") if title_col else ""
            domain = str(row.get("Reference: Domain", "") or row.get("Domain", "") or "")
            for term in pending.split(","):
                term = term.strip()
                if not term:
                    continue
                if term not in term_context:
                    term_context[term] = {"courses": [], "domains": []}
                if title and title not in term_context[term]["courses"]:
                    term_context[term]["courses"].append(title)
                if domain and domain not in term_context[term]["domains"]:
                    term_context[term]["domains"].append(domain)

    if not term_context:
        return df

    terms_with_ctx = [{"term": t, **v} for t, v in term_context.items()]
    VOCAB_BATCH = 20   # terms per API call — keeps each call fast (~3-5s)

    all_proposals: dict[str, dict] = {}
    total_tokens = 0

    for batch_start in range(0, len(terms_with_ctx), VOCAB_BATCH):
        batch = terms_with_ctx[batch_start: batch_start + VOCAB_BATCH]
        try:
            results, tokens = _call_api(client, batch, _model, _effort)
            total_tokens += tokens
            for r in results:
                if "term" in r:
                    all_proposals[r["term"]] = r
        except Exception as exc:
            print(f"[AI VocabResearch] API error batch {batch_start}: {exc}")

    proposals_json = json.dumps(all_proposals, ensure_ascii=False)
    df.at[df.index[0], "_ai_vocab_proposals"] = proposals_json
    print(f"[AI VocabResearch] Researched {len(all_proposals)} / {len(terms_with_ctx)} terms | "
          f"{total_tokens} tokens | model={_model}")
    return df
