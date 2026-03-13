"""pipeline.py -- Saba LMS Catalog Cleaning Pipeline

Two-pass architecture:
  Pass 1 (rule-based, always runs):
    Ingest -> Profile -> Classify -> Scope -> Sunset -> Title/Desc/Vendor/BL/Vocab -> Changeset

  Pass 2 (AI-powered, runs when OPENAI_API_KEY is set):
    AI Description Generation -> AI Vocabulary Research

Usage:
    python pipeline.py
    python pipeline.py path/to/catalog.xlsx
    python pipeline.py path/to/catalog.xlsx data/output
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents import (
    ingest_profiler,
    assessment_detector,
    reg_compliance_classifier,
    scope_classifier,
    sunset_planner,
    title_normalizer,
    description_sanitizer,
    vendor_resolver,
    bl_mapper,
    vocab_resolver,
    changeset_writer,
)
import agents.vocab_resolver            as _vr
import agents.vendor_resolver           as _vendor
import agents.bl_mapper                 as _bl
import agents.reg_compliance_classifier as _rc
import agents.title_normalizer          as _tn

DEFAULT_XLSX   = r"C:\Users\karam\Downloads\PoC_Saba_Catalog_Clean_Format_150.xlsx"
DEFAULT_OUT    = "data/output"
PROCESSED_DIR  = "data/processed"


def _reset_agent_caches() -> None:
    _vr._VOCAB_CACHE    = None
    _vendor._ALIASES    = None
    _bl._RULES          = None
    _rc._KEYWORD_CACHE  = None
    _tn._CONFIG         = None


def run_pipeline(xlsx_path: str, output_dir: str = DEFAULT_OUT,
                 run_ai: bool = True,
                 ai_model: str | None = None,
                 ai_reasoning_effort: str | None = None) -> tuple:
    """
    Run the full pipeline.

    Returns: (df, queue_summary, quality_metrics)
    """
    import json
    import os
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")

    sep = "=" * 65
    print(f"\n{sep}")
    print("  Saba LMS Catalog Cleaning Pipeline")
    print(f"  Source : {xlsx_path}")
    print(f"  Output : {output_dir}")
    ai_enabled = run_ai and bool(os.getenv("OPENAI_API_KEY", ""))
    print(f"  AI pass: {'ENABLED' if ai_enabled else 'DISABLED (no API key)'}")
    print(sep)

    # ── Pass 1: Rule-based ────────────────────────────────────────────────
    print("\n[Stage 1/6] Ingest & Profile")
    df = ingest_profiler.run(xlsx_path, PROCESSED_DIR)
    quality: dict = {}
    p = Path(PROCESSED_DIR) / "profile_report.json"
    if p.exists():
        quality = json.loads(p.read_text(encoding="utf-8")).get("quality_metrics", {})

    print("\n[Stage 2/6] Classification")
    df = assessment_detector.detect(df)
    df = reg_compliance_classifier.detect(df)
    print(f"  Assessments: {int(df['_is_assessment'].sum())}  |  "
          f"Regulatory: {int(df['_is_regulatory'].sum())}")

    print("\n[Stage 3/6] Scope & Sunset")
    df = scope_classifier.classify(df)
    df = sunset_planner.plan(df)
    for s, c in df["_scope"].value_counts().items():
        print(f"  {s}: {c}")

    print("\n[Stage 4/6] Content & Metadata (rule-based)")
    df = title_normalizer.normalize(df)
    df = description_sanitizer.sanitize(df)
    df = vendor_resolver.resolve(df)
    df = bl_mapper.map_bl(df)
    df = vocab_resolver.resolve(df)

    n_ph   = int(df["_description_placeholder"].sum())
    n_mm   = int(df["_description_mismatch"].sum())
    n_tr   = int(df["_translation_needed"].sum())
    n_vp   = int((df["_vocab_pending"].astype(str).str.strip() != "").sum())
    print(f"  Placeholder descriptions : {n_ph}")
    print(f"  Topic mismatches         : {n_mm}")
    print(f"  Needs translation        : {n_tr}")
    print(f"  Unknown Deloitte terms   : {n_vp}")

    # ── Pass 2: AI-powered ────────────────────────────────────────────────
    if ai_enabled:
        from agents.ai_description_generator import generate as ai_gen_desc
        from agents.ai_vocab_researcher      import research as ai_vocab

        print("\n[Stage 5/6] AI — Description Generation")
        df = ai_gen_desc(df, model=ai_model, reasoning_effort=ai_reasoning_effort)
        n_ai_desc = int((df["_ai_description_draft"].astype(str).str.strip() != "").sum())
        print(f"  AI descriptions drafted: {n_ai_desc}")

        print("\n[Stage 6/6] AI — Vocabulary Research")
        df = ai_vocab(df, model=ai_model, reasoning_effort=ai_reasoning_effort)
        proposals_json = str(df.at[df.index[0], "_ai_vocab_proposals"] or "{}")
        try:
            n_ai_vocab = len(json.loads(proposals_json))
        except Exception:
            n_ai_vocab = 0
        print(f"  AI vocab proposals:      {n_ai_vocab}")
    else:
        print("\n[Stage 5/6] AI stages SKIPPED — set OPENAI_API_KEY to enable")
        df["_ai_description_draft"]      = ""
        df["_ai_description_rationale"]  = ""
        df["_ai_description_confidence"] = 0.0
        df["_ai_description_tokens"]     = 0
        df["_ai_vocab_proposals"]        = ""
        print("\n[Stage 6/6] AI vocab SKIPPED")

    # ── Change Set & HITL Queuing ─────────────────────────────────────────
    df, queue_summary = changeset_writer.write(df, output_dir)

    # ── Summary ───────────────────────────────────────────────────────────
    n_ef_ready   = int(((df["_scope"] == "In-Scope") & ~df["_eightfold_blocked"]).sum())
    n_ef_blocked = int(df["_eightfold_blocked"].sum())
    total_tokens = int(df.get("_ai_description_tokens", 0).sum()) if "_ai_description_tokens" in df.columns else 0

    print(f"\n{sep}")
    print("  PIPELINE COMPLETE")
    print(sep)
    print(f"  Rows processed         : {len(df)}")
    print(f"  Eightfold export ready : {n_ef_ready}")
    print(f"  Eightfold blocked      : {n_ef_blocked}")
    if ai_enabled:
        print(f"  AI tokens used         : {total_tokens}")
    print(f"\n  HITL queues:")
    for q, n in queue_summary.items():
        if n:
            print(f"    {q}: {n}")
    print(sep + "\n")

    return df, queue_summary, quality


if __name__ == "__main__":
    _reset_agent_caches()
    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    out  = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    run_pipeline(xlsx, out)
