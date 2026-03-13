"""app.py -- Deloitte LMS Catalog Cleaning | Executive UI (Streamlit)

Run:
    streamlit run app.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Streamlit Cloud secrets take priority over .env
def _st_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import agents.vocab_resolver             as _vr
import agents.vendor_resolver            as _vendor
import agents.bl_mapper                  as _bl
import agents.reg_compliance_classifier  as _rc
import agents.title_normalizer           as _tn

from agents import (
    assessment_detector, bl_mapper, changeset_writer,
    description_sanitizer, ingest_profiler, reg_compliance_classifier,
    scope_classifier, sunset_planner, title_normalizer,
    vendor_resolver, vocab_resolver,
)

st.set_page_config(
    page_title="Saba Catalog Cleaning | Deloitte",
    layout="wide",
    initial_sidebar_state="expanded",
)

C_GREEN      = "#86BC25"
C_DARK_GREEN = "#046A38"
C_BLACK      = "#000000"
C_GRAY       = "#75787B"
C_LGRAY      = "#D0D0CE"
C_AMBER      = "#E87722"
C_RED        = "#DA291C"

st.markdown(f"""
<style>
  html, body, [class*="css"] {{ font-family: 'Segoe UI', Arial, sans-serif !important; }}
  #MainMenu, footer, header {{ visibility: hidden; }}

  .d-header {{
    background:{C_BLACK}; padding:14px 28px 10px; border-bottom:4px solid {C_GREEN};
    display:flex; align-items:center; justify-content:space-between; margin-bottom:24px;
  }}
  .d-logo {{ font-size:1.55rem; font-weight:900; color:#fff; letter-spacing:-0.5px; }}
  .d-logo span {{ color:{C_GREEN}; }}
  .d-app-title {{ font-size:0.9rem; color:#C8C8C8; margin-left:20px; }}
  .d-ts {{ font-size:0.72rem; color:{C_GRAY}; }}

  .kpi-card {{
    background:#fff; border-left:5px solid {C_GREEN}; border-radius:3px;
    padding:14px 18px 12px; box-shadow:0 1px 3px rgba(0,0,0,.07); height:100%;
  }}
  .kpi-card.warn   {{ border-left-color:{C_AMBER}; }}
  .kpi-card.danger {{ border-left-color:{C_RED}; }}
  .kpi-card.neutral {{ border-left-color:{C_GRAY}; }}
  .kpi-label {{ font-size:.65rem; color:{C_GRAY}; text-transform:uppercase;
    letter-spacing:1px; font-weight:700; margin-bottom:4px; }}
  .kpi-value {{ font-size:2.1rem; font-weight:800; color:{C_BLACK}; line-height:1.05; }}
  .kpi-sub {{ font-size:.7rem; color:{C_GRAY}; margin-top:3px; }}

  .section-h {{
    font-size:.8rem; font-weight:700; text-transform:uppercase; letter-spacing:1.2px;
    color:{C_BLACK}; border-bottom:2px solid {C_GREEN}; padding-bottom:5px; margin:20px 0 14px;
  }}

  .tip {{
    display:inline-block; cursor:help; color:{C_GRAY}; font-size:.7rem;
    border:1px solid {C_LGRAY}; border-radius:50%; padding:0 4px; margin-left:4px;
    font-weight:700; vertical-align:middle; position:relative;
  }}

  .q-card {{
    background:#fff; border:1px solid {C_LGRAY}; border-left:5px solid {C_GREEN};
    border-radius:3px; padding:12px 14px; margin-bottom:10px;
  }}
  .q-card.warn   {{ border-left-color:{C_AMBER}; }}
  .q-card.danger {{ border-left-color:{C_RED}; }}
  .q-card.done   {{ border-left-color:{C_GRAY}; background:#FAFAFA; opacity:.75; }}
  .q-title {{ font-weight:700; font-size:.88rem; color:{C_BLACK}; margin-bottom:4px; }}
  .q-issue {{ font-size:.79rem; color:{C_RED}; margin-bottom:4px; }}
  .q-rec   {{ font-size:.76rem; color:{C_GRAY}; margin-bottom:6px; }}
  .q-rationale {{
    font-size:.74rem; color:#555; background:#F5F5F5; border-radius:3px;
    padding:6px 10px; margin-bottom:8px; border-left:3px solid {C_LGRAY};
  }}
  .q-proposal {{
    font-size:.78rem; background:#F2F8E8; border-left:3px solid {C_GREEN};
    border-radius:3px; padding:6px 10px; margin-bottom:8px; color:#1A4A00;
  }}

  .diff-box {{
    background:#fff; border:1px solid {C_LGRAY}; border-radius:3px;
    padding:10px 14px; margin-bottom:6px;
  }}
  .diff-label {{ font-size:.65rem; font-weight:700; text-transform:uppercase;
    letter-spacing:1px; margin-bottom:4px; }}
  .diff-orig {{ color:{C_GRAY}; font-size:.82rem; text-decoration:line-through; }}
  .diff-new  {{ color:{C_DARK_GREEN}; font-size:.82rem; font-weight:600; }}
  .diff-same {{ color:#555; font-size:.82rem; }}
  .diff-detect {{ font-size:.75rem; padding:4px 8px; border-radius:3px; margin-top:4px; }}
  .diff-detect.ph  {{ background:#FFF0EF; color:{C_RED}; }}
  .diff-detect.mm  {{ background:#FFF5EC; color:{C_AMBER}; }}
  .diff-detect.ok  {{ background:#F2F8E8; color:{C_DARK_GREEN}; }}

  .badge {{ display:inline-block; padding:2px 9px; border-radius:10px;
    font-size:.66rem; font-weight:700; vertical-align:middle; margin-right:5px; }}
  .b-green  {{ background:{C_GREEN};  color:#fff; }}
  .b-warn   {{ background:{C_AMBER};  color:#fff; }}
  .b-danger {{ background:{C_RED};    color:#fff; }}
  .b-neutral{{ background:{C_GRAY};   color:#fff; }}
  .b-done   {{ background:#C8C8C8;    color:#fff; }}

  .how-card {{
    background:#fff; border-radius:4px; border:1px solid {C_LGRAY};
    border-top:4px solid {C_GREEN}; padding:16px 18px; height:100%;
  }}
  .how-card.amber {{ border-top-color:{C_AMBER}; }}
  .how-card.gray  {{ border-top-color:{C_GRAY};  }}
  .how-title {{ font-size:.75rem; font-weight:700; text-transform:uppercase;
    letter-spacing:1px; color:{C_BLACK}; margin-bottom:10px; }}
  .how-item {{ font-size:.8rem; color:#333; padding:3px 0; border-bottom:1px solid #F0F0F0; }}

  .ob-card {{
    background:#fff; border:1px solid {C_LGRAY}; border-radius:4px; padding:24px 28px;
    margin-bottom:0;
  }}
  .ob-step {{ font-size:.7rem; color:{C_GREEN}; font-weight:700; text-transform:uppercase;
    letter-spacing:1px; margin-bottom:8px; }}
  .ob-title {{ font-size:1.2rem; font-weight:800; color:{C_BLACK}; margin-bottom:10px; }}
  .ob-body {{ font-size:.85rem; color:#333; line-height:1.6; }}
  .ob-example {{
    background:#F5F5F5; border-left:4px solid {C_GREEN}; border-radius:3px;
    padding:10px 14px; margin-top:12px; font-size:.8rem; color:#333;
  }}

  .ai-badge {{
    display:inline-block; padding:2px 8px; border-radius:10px; font-size:.65rem;
    font-weight:700; background:#E8F4FF; color:#0057B8; border:1px solid #99CAFF;
    margin-left:6px; vertical-align:middle;
  }}
  .ai-proposal {{
    background:#F0F7FF; border-left:4px solid #0057B8; border-radius:3px;
    padding:10px 14px; font-size:.82rem; color:#003070; margin-bottom:8px;
  }}
  .ai-rationale {{
    font-size:.74rem; color:#5580A8; font-style:italic; margin-top:4px;
  }}
  .ai-conf-high  {{ color:#046A38; font-weight:700; }}
  .ai-conf-med   {{ color:{C_AMBER}; font-weight:700; }}
  .ai-conf-low   {{ color:{C_RED};   font-weight:700; }}
  .cost-bar {{
    background:#F5F5F5; border:1px solid {C_LGRAY}; border-radius:3px;
    padding:8px 12px; font-size:.78rem; color:{C_GRAY}; margin-bottom:10px;
  }}

  .vocab-term  {{ font-size:.9rem; font-weight:700; color:{C_BLACK}; }}
  .vocab-count {{ font-size:.7rem; color:{C_GRAY}; }}
  .vocab-existing {{ font-size:.8rem; color:{C_DARK_GREEN}; font-style:italic;
    background:#F2F8E8; border-radius:3px; padding:4px 8px; margin-top:4px; }}

  [data-testid="stSidebar"] > div:first-child {{
    background:#F2F2F2; border-right:1px solid {C_LGRAY};
  }}
  .sidebar-logo {{
    font-size:1.3rem; font-weight:900; color:{C_BLACK}; letter-spacing:-0.5px;
    padding:6px 0 2px; border-bottom:3px solid {C_GREEN}; margin-bottom:16px;
  }}
  .sidebar-logo span {{ color:{C_GREEN}; }}

  button[data-baseweb="tab"] {{ font-weight:600 !important; font-size:.85rem !important; }}
  button[data-baseweb="tab"][aria-selected="true"] {{
    color:{C_DARK_GREEN} !important; border-bottom:3px solid {C_GREEN} !important;
  }}
  .stButton > button[kind="primary"] {{
    background:{C_GREEN} !important; border:none !important; color:white !important;
    font-weight:700 !important; border-radius:2px !important;
  }}
  .stButton > button[kind="primary"]:hover {{ background:{C_DARK_GREEN} !important; }}
  div[data-testid="stDownloadButton"] > button {{
    background:transparent !important; border:2px solid {C_GREEN} !important;
    color:{C_DARK_GREEN} !important; font-weight:600 !important; border-radius:2px !important;
  }}
  div[data-testid="stDownloadButton"] > button:hover {{
    background:{C_GREEN} !important; color:white !important;
  }}
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────
POC_DEFAULT   = Path(r"C:\Users\karam\Downloads\PoC_Saba_Catalog_Clean_Format_150.xlsx")
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR    = ROOT / "data" / "output"
FEEDBACK_FILE = ROOT / "feedback" / "feedback.jsonl"
VOCAB_FILE    = ROOT / "config" / "deloitte_vocab.json"

# variant | what the pipeline detected | what to do | what "Approve" means | what "Reject" means | edit field
QUEUE_META: dict[str, dict] = {
    "Q1_HighRiskRetirement": dict(
        variant="danger",
        detected="Active or regulatory course proposed for retirement",
        action="Senior L&D sign-off required before discontinuing",
        approve="Approve = confirm this course should be retired on the proposed date",
        reject="Reject = keep this course active — do not retire",
        edit_field="proposed_discontinue_date",
        edit_label="Correct retirement date or add a note",
    ),
    "Q2_RegulatoryOverride": dict(
        variant="warn",
        detected="Regulatory classification below 75% confidence",
        action="Verify the regulatory topic against the course content",
        approve="Approve = confirm this IS a regulatory course (protects from auto-retirement)",
        reject="Reject = this is NOT regulatory — treat as a regular course",
        edit_field="regulatory_topics",
        edit_label="Correct regulatory topic(s)",
    ),
    "Q3_VendorRemap": dict(
        variant="warn",
        detected="Vendor name is ambiguous or unknown — pipeline could not match to controlled list",
        action="Select the correct vendor from the firm-approved list",
        approve="Approve = accept the pipeline's proposed vendor mapping",
        reject="Reject = keep the original vendor name as-is",
        edit_field="_clean_vendor",
        edit_label="Type the correct vendor name from the approved list",
    ),
    "Q4_BLMapping": dict(
        variant="neutral",
        detected="Business Line could not be determined automatically",
        action="Assign the correct Business Line manually",
        approve="N/A — no proposal to approve. Use Edit to assign the correct Business Line.",
        reject="Reject = leave Business Line as Unknown",
        edit_field="_business_line",
        edit_label="Type the correct Business Line (e.g. Audit/A&A, Tax, Consulting)",
    ),
    "Q5_Translation": dict(
        variant="warn",
        detected="Description language is not English — Eightfold requires English content",
        action="Route to an approved translator or provide the English translation here",
        approve="Approve = confirm this course needs translation (flagged for translator)",
        reject="Reject = the non-English description is acceptable as-is",
        edit_field="_clean_description",
        edit_label="Paste the approved English translation of the description",
    ),
    "Q5b_DescriptionRequired": dict(
        variant="danger",
        detected="Description is a generic placeholder or completely empty — Eightfold cannot use it",
        action="Replace with a real description that explains what the course covers",
        approve="Approve = confirm this description is invalid and must be replaced before export",
        reject="Reject = accept the placeholder as-is (not recommended — blocks Eightfold export)",
        edit_field="_clean_description",
        edit_label="Type the real course description (what does this course teach?)",
    ),
    "Q5c_DescriptionMismatch": dict(
        variant="warn",
        detected="Title and description appear to be about different topics — likely a copy-paste error",
        action="Verify with the course owner: does the description actually belong to this course?",
        approve="Approve = confirm the mismatch exists and this description needs to be replaced",
        reject="Reject = description IS correct for this course (no mismatch)",
        edit_field="_clean_description",
        edit_label="Paste the correct description that matches the course title",
    ),
    "Q6_LowConfidenceScope": dict(
        variant="neutral",
        detected="Scope is 'Review' or confidence score below 60% — pipeline is uncertain",
        action="Confirm the scope decision: should this course be kept, reviewed, or retired?",
        approve="Approve = accept the pipeline's scope proposal as the final decision",
        reject="Reject = override the pipeline's proposal",
        edit_field="_scope",
        edit_label="Your scope decision: In-Scope / Review / Out-of-Scope",
    ),
    "Q7_VocabClarification": dict(
        variant="neutral",
        detected="Unknown Deloitte abbreviations found — Eightfold cannot understand them without context",
        action="Go to the Vocabulary tab to provide plain-language definitions for these terms",
        approve="Approve = acknowledged (go to Vocabulary tab to add the definitions)",
        reject="Reject = these terms don't need definitions",
        edit_field=None,
        edit_label=None,
    ),
}
QUEUE_META["Q_Other"] = dict(
    variant="neutral",
    detected="AI or pipeline detected an issue that does not fit any standard category",
    action="Review this course — check the AI flags and MF Comments column for details",
    approve="Approve = acknowledge the issue has been reviewed",
    reject="Reject = this is not an issue — no action needed",
    edit_field=None,
    edit_label=None,
)

QUEUE_ORDER = list(QUEUE_META.keys())


def _get_queue_meta(qname: str) -> dict:
    """Return meta for known queues, or a generic fallback for unknown ones."""
    if qname in QUEUE_META:
        return QUEUE_META[qname]
    # Dynamic / AI-generated queue — generic fallback
    label = qname.replace("_", " ").replace("Q ", "").strip()
    return dict(
        variant="neutral",
        detected=f"AI-detected issue: {label}",
        action="Review the course details and decide whether action is required",
        approve="Approve = acknowledge and accept",
        reject="Reject = no action needed",
        edit_field=None,
        edit_label="Your correction or note",
    )

# ── Onboarding steps ───────────────────────────────────────────────────────
ONBOARDING_STEPS = [
    dict(
        title="What this tool does",
        body="""This is an <strong>automated cleaning pipeline</strong> for the Saba LMS catalog.
It scans every course, detects data quality problems, and proposes fixes.
You then review the proposals — nothing changes in Saba until a human confirms it.
<br><br>The pipeline runs in about 5 seconds on 150 courses.""",
        example="""<strong>Example:</strong> Course "CG903Re Independence Matters" has a description that belongs to a completely different course (ISA 600R audit content). The pipeline detects the mismatch and puts it in your review queue. You confirm, provide the correct description, and save.""",
    ),
    dict(
        title="Three types of data — each does a different job",
        body="""<strong style='color:#86BC25'>Scope Signals</strong> — decide which courses go to Eightfold<br>
FY24/25/26 completions, last completion date, course age, discontinue date, course type (assessment? regulatory?)<br><br>
<strong style='color:#E87722'>Eightfold AI Engine Inputs</strong> — power skill-to-course matching<br>
Course title and description. If the description is a generic placeholder, Eightfold cannot match skills. The AI will generate a draft description for you to review.<br><br>
<strong style='color:#75787B'>Search & Filter Signals</strong> — help users find courses<br>
Vendor/Provider and Business Line appear as filter facets in Storefront and Eightfold.""",
        example=None,
    ),
    dict(
        title="Human-in-the-Loop (HITL) — your role",
        body="""The pipeline <em>proposes</em> changes. You <em>decide</em>.
<br><br>
In the <strong>HITL Review</strong> tab, each course card shows:<br>
&nbsp;&bull; What the pipeline detected (the issue)<br>
&nbsp;&bull; What it proposes (the fix)<br>
&nbsp;&bull; <strong>Approve</strong> = accept the proposal<br>
&nbsp;&bull; <strong>Edit &amp; save</strong> = provide your own corrected value<br>
&nbsp;&bull; <strong>Reject</strong> = override, keep original<br><br>
All decisions are saved to <code>feedback.jsonl</code> with a timestamp.""",
        example="""<strong>Example:</strong> Queue "Description Required" shows 95 courses. For each one, you see the course title and the issue ("generic placeholder"). You click Edit and type the real description, or Approve to flag it for a course owner to update.""",
    ),
    dict(
        title="Vocabulary — teaching the AI your firm's language",
        body="""Deloitte uses internal codes like <strong>TE610</strong>, <strong>CG903Re</strong>, <strong>ISA 600R</strong> that Eightfold doesn't know.
<br><br>
The pipeline detects these unknown terms and lists them in the <strong>Vocabulary</strong> tab.
You provide the plain-language definition. On the next pipeline run, the definition is automatically appended to the course description so Eightfold can match the right skills.
<br><br>
<em>Important: the AI never invents definitions. Only you know what these terms mean at your firm.</em>""",
        example="""<strong>Example:</strong> "TE610 Group Audits in Action" — the pipeline flags "TE610" as unknown. You go to Vocabulary, type "TE610 is Deloitte's Group Audits course series covering ISA 600R methodology", and save. Next run, every course with TE610 in the title gets that context appended for Eightfold.""",
    ),
    dict(
        title="You're ready — here's how to start",
        body="""<strong>Step 1:</strong> Click <strong>Run Pipeline</strong> in the sidebar (PoC sample is pre-selected).<br><br>
<strong>Step 2:</strong> Review the <strong>Dashboard</strong> — scope breakdown, quality metrics, Eightfold readiness.<br><br>
<strong>Step 3:</strong> Open <strong>HITL Review</strong> — work through the queues starting with "Description Required" (biggest blocker for Eightfold).<br><br>
<strong>Step 4:</strong> Open <strong>Vocabulary</strong> — add definitions for any flagged Deloitte terms.<br><br>
<strong>Step 5:</strong> <strong>Download</strong> the proposals Excel and share with course owners.""",
        example=None,
    ),
]


# ── Helpers ────────────────────────────────────────────────────────────────

def tip(text: str) -> str:
    """Inline (?) tooltip rendered as HTML title attribute."""
    safe = text.replace('"', '&quot;')
    return (f'<span class="tip" title="{safe}">?</span>')


def _course_key(row: pd.Series) -> str:
    for col in ["ActiveCourseID", "Course Number"]:
        v = str(row.get(col, "") or "").strip()
        if v:
            return v
    return str(row.name)


def _write_feedback(course_id: str, queue: str, action: str,
                    field: str = "", edited_value: str = "") -> None:
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "course_id": course_id, "queue": queue, "action": action,
        "field": field, "edited_value": edited_value,
    }
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _mark_resolved(course_id: str, queue: str, action: str) -> None:
    key = f"{course_id}::{queue}"
    st.session_state.setdefault("resolved_keys", set()).add(key)
    st.session_state.setdefault("resolved_actions", {})[key] = action


def scope_badge(scope: str) -> str:
    cls = {"In-Scope": "b-green", "Out-of-Scope": "b-danger", "Review": "b-warn"}.get(scope, "b-neutral")
    return f'<span class="badge {cls}">{scope}</span>'


def kpi_card(col, label: str, value, sub: str = "", variant: str = "",
             tooltip: str = "") -> None:
    cls = "kpi-card" + (f" {variant}" if variant else "")
    tt = tip(tooltip) if tooltip else ""
    col.markdown(f"""
    <div class="{cls}">
      <div class="kpi-label">{label}{tt}</div>
      <div class="kpi-value">{value}</div>
      <div class="kpi-sub">{sub}</div>
    </div>""", unsafe_allow_html=True)


def render_header() -> None:
    ts = st.session_state.get("run_ts", "")
    st.markdown(f"""
    <div class="d-header">
      <div style="display:flex;align-items:baseline;gap:16px;">
        <div class="d-logo">Deloitte<span>.</span></div>
        <div class="d-app-title">Saba LMS Catalog Cleaning &mdash; Executive Dashboard</div>
      </div>
      <div class="d-ts">{ts}</div>
    </div>""", unsafe_allow_html=True)


# ── Pipeline runner ────────────────────────────────────────────────────────

def _reset_agent_caches() -> None:
    _vr._VOCAB_CACHE = None
    _vendor._ALIASES = None
    _bl._RULES       = None
    _rc._KEYWORD_CACHE = None
    _tn._CONFIG      = None


def run_pipeline_with_progress(xlsx_path: str, ai_enabled: bool,
                               ai_model: str, ai_effort: str,
                               upd) -> tuple[pd.DataFrame, dict, dict]:
    """
    upd(pct: float, msg: str) — called after every stage.
    Because upd writes directly to st.empty()/st.progress() elements,
    the browser updates in real-time without needing a rerun.
    """
    import json as _json
    from agents import (
        ingest_profiler, assessment_detector, reg_compliance_classifier,
        scope_classifier, sunset_planner, title_normalizer,
        description_sanitizer, vendor_resolver, bl_mapper,
        vocab_resolver, changeset_writer,
    )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    upd(0.03, "Reading catalog file…")
    df = ingest_profiler.run(xlsx_path, str(PROCESSED_DIR))
    n = len(df)
    quality: dict = {}
    p = PROCESSED_DIR / "profile_report.json"
    if p.exists():
        quality = _json.loads(p.read_text(encoding="utf-8")).get("quality_metrics", {})
    upd(0.10, f"Ingested {n} courses — detecting assessments & regulatory…")

    df = assessment_detector.detect(df)
    df = reg_compliance_classifier.detect(df)
    n_ass = int(df["_is_assessment"].sum())
    n_reg = int(df["_is_regulatory"].sum())
    upd(0.18, f"Classified: {n_ass} assessments · {n_reg} regulatory — scoring scope…")

    df = scope_classifier.classify(df)
    df = sunset_planner.plan(df)
    n_in  = int((df["_scope"] == "In-Scope").sum())
    n_rev = int((df["_scope"] == "Review").sum())
    n_out = int((df["_scope"] == "Out-of-Scope").sum())
    upd(0.28, f"Scope: {n_in} In-Scope · {n_rev} Review · {n_out} Out-of-Scope — normalising titles…")

    df = title_normalizer.normalize(df)
    upd(0.35, "Titles normalised — scanning descriptions for issues…")

    df = description_sanitizer.sanitize(df)
    n_ph = int(df["_description_placeholder"].sum())
    n_mm = int(df["_description_mismatch"].sum())
    upd(0.43, f"Descriptions: {n_ph} placeholders · {n_mm} mismatches — resolving vendors & BL…")

    df = vendor_resolver.resolve(df)
    df = bl_mapper.map_bl(df)
    df = vocab_resolver.resolve(df)
    n_vp = int((df["_vocab_pending"].astype(str).str.strip() != "").sum())
    upd(0.52, f"Vendors & business lines mapped · {n_vp} unknown Deloitte terms flagged")

    # ── AI stages ─────────────────────────────────────────────────────────
    if ai_enabled:
        needs_desc = int((
            df.get("_description_placeholder", pd.Series(False, index=df.index)).astype(bool)
            | df.get("_description_missing",    pd.Series(False, index=df.index)).astype(bool)
            | df.get("_description_mismatch",   pd.Series(False, index=df.index)).astype(bool)
        ).sum())

        if needs_desc > 0:
            from agents.ai_description_generator import generate as _ai_desc
            n_batches = (needs_desc + 15 - 1) // 15
            upd(0.54, f"AI — generating descriptions: 0 / {needs_desc} courses  "
                      f"(batch 0 / {n_batches})")

            def _desc_cb(b_done, b_total, c_done, c_total):
                pct = 0.54 + (b_done / b_total) * 0.32
                upd(pct, f"AI — generating descriptions: {c_done} / {c_total} courses  "
                         f"(batch {b_done} / {b_total})")

            df = _ai_desc(df, model=ai_model, reasoning_effort=ai_effort,
                          progress_callback=_desc_cb)
            n_gen = int((df["_ai_description_draft"].astype(str).str.strip() != "").sum())
            upd(0.86, f"AI drafted {n_gen} descriptions — researching Deloitte vocabulary…")
        else:
            upd(0.86, "No placeholder descriptions to generate — researching vocabulary…")

        if n_vp > 0:
            from agents.ai_vocab_researcher import research as _ai_vocab
            upd(0.87, f"AI — researching {n_vp} Deloitte terms in batches of 20…")
            df = _ai_vocab(df, model=_st_secret("OPENAI_MODEL_REASONING", "gpt-4.1"),
                           reasoning_effort=ai_effort)
            upd(0.94, "Vocabulary research complete — writing change set…")
        else:
            upd(0.94, "No unknown vocabulary — writing change set…")
    else:
        for col in ("_ai_description_draft", "_ai_description_rationale", "_ai_vocab_proposals"):
            df[col] = ""
        df["_ai_description_confidence"] = 0.0
        df["_ai_description_tokens"]     = 0
        upd(0.94, "AI pass skipped (no API key) — writing change set…")

    df, queue_summary = changeset_writer.write(df, str(OUTPUT_DIR))
    upd(1.0, f"Complete — {n} courses processed")
    return df, queue_summary, quality


# Keep cache wrapper for demo mode (pre-baked results)
BUNDLED_DEMO = ROOT / "demo" / "demo_snapshot.json"

def _restore_snapshot_types(df: pd.DataFrame) -> pd.DataFrame:
    """Cast columns that were stringified back to their proper types."""
    bool_cols = [c for c in df.columns if c.startswith("_is_") or c.startswith("_eightfold")]
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].map(lambda v: str(v).strip().lower() == "true")

    float_cols = ["_ai_description_confidence", "_scope_confidence", "_sunset_score"]
    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    int_cols = ["_ai_description_tokens", "FY24 Completions", "FY25 Completions",
                "FY26 Completions", "FY26 Enrollments", "Learning Hours"]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df


@st.cache_data(show_spinner=False)
def _load_demo_results() -> tuple[pd.DataFrame, dict, dict] | None:
    # prefer a freshly-saved snapshot; fall back to the bundled one
    demo_file = OUTPUT_DIR / "demo_snapshot.json"
    if not demo_file.exists():
        demo_file = BUNDLED_DEMO
    if not demo_file.exists():
        return None
    data = json.loads(demo_file.read_text(encoding="utf-8"))
    df = _restore_snapshot_types(pd.DataFrame(data["rows"]))
    return df, data["queue_summary"], data["quality"]


def _save_demo_snapshot(df: pd.DataFrame, qs: dict, quality: dict) -> None:
    """Save current results as a reusable demo snapshot."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "rows": df.astype(str).to_dict(orient="records"),
        "queue_summary": qs,
        "quality": quality,
    }
    snap_path = OUTPUT_DIR / "demo_snapshot.json"
    snap_path.write_text(json.dumps(snapshot, ensure_ascii=False, default=str),
                         encoding="utf-8")
    print(f"[Demo] Snapshot saved to {snap_path}")


# ── Onboarding ─────────────────────────────────────────────────────────────

def render_onboarding() -> None:
    step = st.session_state.get("ob_step", 0)
    total = len(ONBOARDING_STEPS)
    s = ONBOARDING_STEPS[step]

    # Progress dots
    def _dot(i: int) -> str:
        bg = C_GREEN if i == step else C_LGRAY
        return (
            f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
            f'margin:0 3px;background:{bg};"></span>'
        )
    dots = "".join(_dot(i) for i in range(total))

    st.markdown(f"""
    <div class="ob-card">
      <div class="ob-step">Step {step+1} of {total}</div>
      <div class="ob-title">{s["title"]}</div>
      <div class="ob-body">{s["body"]}</div>
      {"" if not s.get("example") else f'<div class="ob-example">{s["example"]}</div>'}
      <div style="margin-top:18px;">{dots}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("")
    n1, n2, n3 = st.columns([1, 1, 4])
    if step > 0:
        if n1.button("Previous", key="ob_prev"):
            st.session_state["ob_step"] = step - 1
            st.rerun()
    if step < total - 1:
        if n2.button("Next", type="primary", key="ob_next"):
            st.session_state["ob_step"] = step + 1
            st.rerun()
    else:
        if n2.button("Start using the app", type="primary", key="ob_done"):
            st.session_state["onboarding_done"] = True
            st.rerun()
    if n3.button("Skip tutorial", key="ob_skip"):
        st.session_state["onboarding_done"] = True
        st.rerun()


# ── Sidebar ────────────────────────────────────────────────────────────────

def render_sidebar() -> tuple[bool, str | None, bool, str, str]:
    with st.sidebar:
        st.markdown('<div class="sidebar-logo">Deloitte<span>.</span></div>', unsafe_allow_html=True)
        st.markdown("**Learning & Development — Saba cleaning workflow**")
        st.markdown("---")

        # AI config — reads from Streamlit Cloud secrets or local .env
        api_key_input = _st_secret("OPENAI_API_KEY")
        ai_enabled    = bool(api_key_input)
        ai_model      = _st_secret("OPENAI_MODEL_GENERATION", "gpt-4.1")
        ai_effort     = _st_secret("OPENAI_REASONING_EFFORT", "medium")

        # ── Catalog Source ────────────────────────────────────────────────
        st.markdown("**Catalog Source**")
        source = st.radio("source", ["Use PoC sample (150 rows)", "Upload my catalog"],
                          label_visibility="collapsed")
        xlsx_path: str | None = None
        if source == "Use PoC sample (150 rows)":
            if POC_DEFAULT.exists():
                xlsx_path = str(POC_DEFAULT)
                st.caption(f"File: `{POC_DEFAULT.name}`")
            else:
                st.info("PoC sample not available in this environment — use Demo mode below to load pre-computed results instantly, or upload your own catalog.")
        else:
            up = st.file_uploader("Upload XLSX", type=["xlsx"], label_visibility="collapsed",
                                  help="Single-row or two-row header supported")
            if up:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
                tmp.write(up.read()); tmp.close()
                xlsx_path = tmp.name
                st.caption(f"Loaded: `{up.name}`")

        st.markdown("")

        demo_snap_exists = (OUTPUT_DIR / "demo_snapshot.json").exists() or BUNDLED_DEMO.exists()
        demo_mode = st.toggle(
            "Demo mode (load saved results)",
            value=False,
            key="demo_toggle",
            help="Skip the pipeline and load the last saved results instantly. "
                 "Useful for presenting without waiting for the AI to run.",
            disabled=not demo_snap_exists,
        )
        if not demo_snap_exists:
            st.caption("Run the pipeline once to enable Demo mode.")

        run_clicked = st.button(
            "Load Demo Results" if demo_mode else "Run Pipeline",
            type="primary",
            use_container_width=True,
            disabled=(xlsx_path is None and not demo_mode),
        )

        if st.session_state.get("onboarding_done") and not st.session_state.get("has_results"):
            if st.button("Show tutorial again", key="show_ob"):
                st.session_state["onboarding_done"] = False
                st.session_state["ob_step"] = 0
                st.rerun()

        if st.session_state.get("has_results"):
            st.markdown("---")
            # Cost summary
            df_now = st.session_state.get("df")
            pass  # cost display removed
            st.markdown("**Quick Downloads**")
            for fname, label, mime in [
                ("catalog_with_proposals.xlsx", "Proposals (.xlsx)",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ("changeset_audit_log.jsonl", "Audit Log (.jsonl)", "application/octet-stream"),
            ]:
                fpath = OUTPUT_DIR / fname
                if fpath.exists():
                    with open(fpath, "rb") as f:
                        st.download_button(label, f.read(), fname, mime,
                                           use_container_width=True, key=f"sb_{fname}")

    return run_clicked, xlsx_path, ai_enabled, ai_model, ai_effort


# ── TAB 1: Dashboard ───────────────────────────────────────────────────────

def tab_dashboard(df: pd.DataFrame, queue_summary: dict, quality: dict) -> None:
    n = len(df)
    n_in    = int((df["_scope"] == "In-Scope").sum())
    n_rev   = int((df["_scope"] == "Review").sum())
    n_out   = int((df["_scope"] == "Out-of-Scope").sum())
    n_ass   = int(df.get("_is_assessment", pd.Series(False, index=df.index)).sum())
    n_reg   = int(df.get("_is_regulatory", pd.Series(False, index=df.index)).sum())
    n_ph    = int(df.get("_description_placeholder", pd.Series(False, index=df.index)).sum())
    n_trans = int(df.get("_translation_needed",      pd.Series(False, index=df.index)).sum())
    ef_blk  = df.get("_eightfold_blocked", pd.Series(False, index=df.index)).astype(bool)
    n_efr   = int(((df["_scope"] == "In-Scope") & ~ef_blk).sum())
    n_efb   = int(ef_blk.sum())

    # AI run status banner
    ai_on    = st.session_state.get("ai_enabled", False)
    n_ai_gen = int((df["_ai_description_draft"].astype(str).str.strip() != "").sum()) if "_ai_description_draft" in df.columns else 0
    if ai_on and n_ai_gen > 0:
        st.markdown(
            f'<div style="background:#F0F7FF;border-left:4px solid #0057B8;border-radius:3px;'
            f'padding:10px 16px;font-size:.82rem;color:#003070;margin-bottom:14px;">'
            f'<span class="ai-badge">AI-generated</span>&nbsp;'
            f'AI pass completed — <strong>{n_ai_gen} descriptions drafted</strong> and '
            f'<strong>vocabulary researched</strong>. Go to HITL Review → Description Required to approve.</div>',
            unsafe_allow_html=True,
        )
    elif ai_on and n_ai_gen == 0:
        st.markdown(
            f'<div style="background:#FFF5EC;border-left:4px solid {C_AMBER};border-radius:3px;'
            f'padding:10px 16px;font-size:.82rem;color:#7A3A00;margin-bottom:14px;">'
            f'AI pass ran but generated 0 descriptions — the model may have returned unexpected output. '
            f'Check the terminal for errors and re-run the pipeline.</div>',
            unsafe_allow_html=True,
        )

    with st.expander("How it works — click to understand the three data roles", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"""
        <div class="how-card">
          <div class="how-title">Scope Signals</div>
          <div style="font-size:.76rem;color:{C_GRAY};margin-bottom:8px;">Which courses do we send to Eightfold?</div>
          <div class="how-item">FY24 / FY25 / FY26 completions</div>
          <div class="how-item">Last completion date (recency)</div>
          <div class="how-item">Available date (course age)</div>
          <div class="how-item">Discontinue date</div>
          <div class="how-item">Course type: assessment / regulatory / compliance</div>
          <div class="how-item">Strategy alignment (BL, Category)</div>
        </div>""", unsafe_allow_html=True)
        c2.markdown(f"""
        <div class="how-card amber">
          <div class="how-title">Eightfold AI Engine Inputs</div>
          <div style="font-size:.76rem;color:{C_GRAY};margin-bottom:8px;">What powers skill-to-course matching?</div>
          <div class="how-item">Course title (primary topic signal)</div>
          <div class="how-item">Course description (skill evidence)</div>
          <div class="how-item">Deloitte context: glossary definitions appended</div>
          <div style="font-size:.74rem;margin-top:10px;color:{C_AMBER};font-weight:600;">
            Placeholder descriptions block export — EF has nothing to work with.
          </div>
        </div>""", unsafe_allow_html=True)
        c3.markdown(f"""
        <div class="how-card gray">
          <div class="how-title">Search & Filter Signals</div>
          <div style="font-size:.76rem;color:{C_GRAY};margin-bottom:8px;">How do users find courses?</div>
          <div class="how-item">Provider / Vendor (filter panel)</div>
          <div class="how-item">Business Line (facet)</div>
          <div class="how-item">Category (taxonomy)</div>
          <div class="how-item">Delivery type</div>
          <div class="how-item">Language</div>
        </div>""", unsafe_allow_html=True)
        st.markdown("")
        st.markdown(f"""
        <div style="background:#F5F5F5;border-radius:4px;padding:14px 18px;font-size:.8rem;">
          <strong>How Assessment vs Regulatory is detected</strong><br><br>
          <span style="color:{C_AMBER}"><strong>Assessment</strong></span> &rarr;
          title contains "– Assessment", "– Test", "– Exam", or the Deloitte course code ends in
          <strong>A</strong> (e.g. TE715<strong>A</strong>).<br>
          <span style="color:{C_RED}"><strong>Regulatory</strong></span> &rarr;
          keyword scan across title + description + CPE Subject Area: if any regulatory term matches
          (Independence Matters, IFRS, PSAS, AML, Privacy…) <em>or</em> CPE Hours &gt; 0, the course is
          protected from automated retirement.<br><br>
          <strong>Business Line</strong> is inferred (not from the file) using keyword rules in
          <code>config/bl_rules.json</code>. Low-confidence BL assignments go to HITL queue Q4.
          The BL names and rules should be validated by L&D.
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown('<div class="section-h">Scope Breakdown</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    kpi_card(c1, "Total Courses", n, "in catalog")
    kpi_card(c2, "In-Scope", n_in, f"{n_in/n*100:.0f}% — send to Eightfold",
             tooltip="Courses scoring ≥ 0.65 on participation, recency, age, and metadata completeness")
    kpi_card(c3, "Review", n_rev, "needs human confirmation", "warn",
             tooltip="Score between 0.35–0.64 — pipeline is uncertain, human must confirm")
    kpi_card(c4, "Out-of-Scope", n_out, "proposed for retirement", "danger",
             tooltip="Score < 0.35 — zero completions, old, no recent activity")
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown('<div class="section-h">Data Quality</div>', unsafe_allow_html=True)
    c5, c6, c7, c8 = st.columns(4)
    kpi_card(c5, "Assessments", n_ass, "auto-classified", "neutral",
             tooltip="Detected via title regex (ends in '– Assessment') or course code suffix A (e.g. TE715A)")
    kpi_card(c6, "Regulatory Protected", n_reg, "cannot be auto-retired",
             tooltip="Keyword match in title/description (IFRS, PSAS, Independence…) or CPE Hours > 0")
    kpi_card(c7, "Placeholder Descriptions", n_ph,
             f"{n_ph/n*100:.0f}% of catalog", "danger",
             tooltip="Generic text like 'This course is designed to enable practitioners…' — blocks Eightfold export")
    kpi_card(c8, "Needs Translation", n_trans, "non-English descriptions", "warn",
             tooltip="Description language detected as non-English using langdetect library")
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown('<div class="section-h">Eightfold Export Readiness</div>', unsafe_allow_html=True)
    e1, e2, e3, e4 = st.columns(4)
    kpi_card(e1, "Export Ready", n_efr, "In-Scope + real description",
             tooltip="In-Scope AND has a non-placeholder description AND has a vendor mapped")
    kpi_card(e2, "Export Blocked", n_efb, "needs description or vendor fix", "danger",
             tooltip="Missing description, placeholder description, or vendor = Unknown")
    kpi_card(e3, "Active HITL Queues", sum(1 for v in queue_summary.values() if v > 0),
             "queues with items pending", "warn",
             tooltip="Each queue is a category of issue that needs a human decision")
    kpi_card(e4, "Total HITL Items", sum(queue_summary.values()),
             "course-queue assignments", "neutral",
             tooltip="One course can appear in multiple queues if it has multiple issues")
    st.markdown("---")

    left, right = st.columns(2)
    with left:
        st.markdown('<div class="section-h">Scope Distribution</div>', unsafe_allow_html=True)
        fig = go.Figure(go.Pie(
            labels=["In-Scope", "Review", "Out-of-Scope"],
            values=[n_in, n_rev, n_out], hole=0.58,
            marker_colors=[C_GREEN, C_AMBER, C_RED],
            textinfo="percent+label", textfont_size=12,
            hovertemplate="%{label}: <b>%{value}</b><extra></extra>",
        ))
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
                          paper_bgcolor="rgba(0,0,0,0)", height=260,
                          annotations=[dict(text=f"<b>{n}</b><br>courses",
                                            x=0.5, y=0.5, font_size=18, showarrow=False)])
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with right:
        st.markdown('<div class="section-h">HITL Queue Sizes</div>', unsafe_allow_html=True)
        q_data = {k: v for k, v in queue_summary.items() if v > 0}
        if q_data:
            colors = [{"danger": C_RED, "warn": C_AMBER}.get(_get_queue_meta(k)["variant"], C_GRAY)
                      for k in q_data]
            labels = [k.split("_", 1)[1].replace("_", " ") for k in q_data]
            fig2 = go.Figure(go.Bar(
                x=list(q_data.values()), y=labels, orientation="h",
                marker_color=colors, text=list(q_data.values()),
                textposition="outside", textfont_size=12,
                hovertemplate="%{y}: <b>%{x}</b> items<extra></extra>",
            ))
            fig2.update_layout(margin=dict(t=0, b=0, l=0, r=40),
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               xaxis=dict(showgrid=False, showticklabels=False,
                                          range=[0, max(q_data.values()) * 1.2]),
                               yaxis=dict(tickfont=dict(size=11), autorange="reversed"),
                               height=260)
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    if quality:
        st.markdown("---")
        st.markdown('<div class="section-h">Catalog Quality Metrics</div>', unsafe_allow_html=True)
        qdf = pd.DataFrame([
            {"Metric": k.replace("_", " ").title(), "Count": v,
             "% of Catalog": f"{v/n*100:.1f}%"}
            for k, v in quality.items()
        ])
        st.dataframe(qdf, use_container_width=True, hide_index=True)


# ── TAB 2: Course Proposals ────────────────────────────────────────────────

def tab_proposals(df: pd.DataFrame) -> None:
    title_col = next((c for c in ["Course Title", "Mandatory Field: Course Title"]
                      if c in df.columns), None)
    desc_col = "Catalog Item Description" if "Catalog Item Description" in df.columns else None

    st.markdown('<div class="section-h">Filter Courses</div>', unsafe_allow_html=True)
    f1, f2, f3, f4 = st.columns(4)
    scope_opts = ["In-Scope", "Review", "Out-of-Scope"]
    scope_sel  = f1.multiselect("Scope", scope_opts, default=scope_opts, key="p_scope")
    bl_opts    = sorted(df["_business_line"].dropna().unique()) if "_business_line" in df.columns else []
    bl_sel     = f2.multiselect("Business Line", bl_opts, default=bl_opts, key="p_bl")
    reg_sel    = f3.selectbox("Regulatory status", ["All", "Regulatory only", "Non-regulatory"], key="p_reg")
    issue_sel  = f4.selectbox("Issues", ["All", "Has HITL flags", "No issues"], key="p_issues")

    mask = df["_scope"].isin(scope_sel)
    if bl_sel and "_business_line" in df.columns:
        mask &= df["_business_line"].isin(bl_sel)
    if reg_sel == "Regulatory only":
        mask &= df["_is_regulatory"].astype(bool)
    elif reg_sel == "Non-regulatory":
        mask &= ~df["_is_regulatory"].astype(bool)
    if issue_sel == "Has HITL flags":
        mask &= df["_hitl_queues"].astype(str).str.strip().ne("")
    elif issue_sel == "No issues":
        mask &= df["_hitl_queues"].astype(str).str.strip().eq("")

    filtered = df[mask].copy()
    st.caption(f"Showing **{len(filtered)}** of {len(df)} courses")

    col_map = {
        "Original Title": title_col or "",
        "Proposed Title": "_clean_title",
        "Scope": "_scope",
        "Score": "_scope_score",
        "Business Line": "_business_line",
        "Vendor": "_clean_vendor",
        "Regulatory": "_is_regulatory",
        "Assessment": "_is_assessment",
        "EF Blocked": "_eightfold_blocked",
        "HITL Queues": "_hitl_queues",
    }
    avail   = {k: v for k, v in col_map.items() if v and v in filtered.columns}
    display = filtered[[v for v in avail.values()]].copy()
    display.columns = list(avail.keys())

    def row_color(row):
        bg = {"In-Scope": "#EEF8DE", "Out-of-Scope": "#FFEEEC", "Review": "#FFF5EC"}.get(
            row.get("Scope", ""), "")
        return [f"background-color:{bg}" if bg else ""] * len(row)

    styled = display.style.apply(row_color, axis=1).format({"Score": "{:.2f}"}, na_rep="")
    st.dataframe(styled, use_container_width=True, height=340, hide_index=True)

    # ── Course inspector ──────────────────────────────────────────────────
    st.markdown('<div class="section-h">Course Inspector</div>', unsafe_allow_html=True)

    st.markdown(f"""
    <div style="font-size:.8rem;color:#333;background:#F5F5F5;border-radius:3px;
    padding:10px 14px;margin-bottom:14px;">
      Select a course from the dropdown below to see:
      <strong>what the original data looks like</strong>,
      <strong>what the pipeline proposes to change</strong>, and
      <strong>why the scope decision was made</strong>.
      <br><br>
      <em>Note on descriptions:</em> If many courses show the same text
      ("This course is designed to enable practitioners…"), this is because that placeholder
      text was copy-pasted into <strong>{int(df.get('_description_placeholder', pd.Series(False)).sum())
      if '_description_placeholder' in df.columns else 'many'} courses</strong> in Saba.
      The pipeline detects all of them and flags them as "Description Required".
    </div>""", unsafe_allow_html=True)

    if not title_col:
        st.warning("No title column found.")
        return

    titles  = filtered[title_col].fillna("(no title)").astype(str).tolist()
    indices = filtered.index.tolist()

    if not titles:
        st.info("No courses match the current filters.")
        return

    idx_choice = st.selectbox(
        "Select course to inspect",
        range(len(titles)),
        format_func=lambda i: f"{titles[i]}",
        key="diff_sel",
    )

    row = filtered.loc[indices[idx_choice]]
    orig_title  = str(row.get(title_col, "") or "")
    clean_title = str(row.get("_clean_title", "") or "")
    orig_desc   = str(row.get(desc_col, "") or "") if desc_col else ""
    clean_desc  = str(row.get("_clean_description", "") or "")
    enr_desc    = str(row.get("_enriched_description", "") or "")
    change_type = str(row.get("_title_change_type", "NoChange") or "NoChange")
    is_ph       = bool(row.get("_description_placeholder", False))
    is_mm       = bool(row.get("_description_mismatch", False))
    is_missing  = bool(row.get("_description_missing", False))
    rationale   = str(row.get("_scope_rationale", "") or "")
    reg_topics  = str(row.get("_regulatory_topics", "") or "")
    bl          = str(row.get("_business_line", "") or "")
    scope       = str(row.get("_scope", "") or "")
    score       = row.get("_scope_score", 0)
    desc_lang   = str(row.get("_description_language", "") or "")
    hitl_qs     = str(row.get("_hitl_queues", "") or "")

    dc1, dc2 = st.columns(2)

    with dc1:
        st.markdown("**Title**")
        if orig_title == clean_title:
            st.markdown(
                f'<div class="diff-box">'
                f'<div class="diff-label" style="color:{C_GRAY}">No title change proposed</div>'
                f'<div class="diff-same">{orig_title or "(empty)"}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="diff-box">'
                f'<div class="diff-label" style="color:{C_GRAY}">Original title (in Saba today)</div>'
                f'<div class="diff-orig">{orig_title}</div>'
                f'</div>'
                f'<div class="diff-box">'
                f'<div class="diff-label" style="color:{C_DARK_GREEN}">Proposed title ({change_type})</div>'
                f'<div class="diff-new">{clean_title}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("**Why was this scope decision made?**")
        score_fmt = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
        reg_line  = f"<br>Regulatory topics: {reg_topics}" if reg_topics else ""
        bl_line   = f"<br>Business Line (inferred): {bl}" if bl else ""
        st.markdown(
            f'<div class="q-rationale">'
            f'Scope: <strong>{scope}</strong> (confidence score: {score_fmt} / 1.0)<br>'
            f'{rationale}{reg_line}{bl_line}'
            f'</div>',
            unsafe_allow_html=True,
        )

        if hitl_qs.strip():
            st.markdown("**HITL queues for this course:**")
            for q in hitl_qs.split(","):
                q = q.strip()
                if q and q in QUEUE_META:
                    v = QUEUE_META[q]["variant"]
                    bc = {"danger": "b-danger", "warn": "b-warn"}.get(v, "b-neutral")
                    st.markdown(f'<span class="badge {bc}">{q}</span>&nbsp;',
                                unsafe_allow_html=True)

    with dc2:
        st.markdown("**Description**")

        if not orig_desc.strip():
            st.markdown(
                f'<div class="diff-box">'
                f'<div class="diff-label" style="color:{C_RED}">No description in Saba</div>'
                f'<div class="diff-same" style="color:{C_GRAY};font-style:italic;">(empty field)</div>'
                f'<div class="diff-detect ph">DETECTED: Description field is empty — '
                f'must be filled before Eightfold export</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            # Show original
            st.markdown(
                f'<div class="diff-box">'
                f'<div class="diff-label" style="color:{C_GRAY}">Original (in Saba today, first 300 chars)</div>'
                f'<div class="diff-same">{orig_desc[:300]}</div>',
                unsafe_allow_html=True,
            )
            # Detection flags
            if is_ph:
                n_ph_total = int(df.get("_description_placeholder", pd.Series(False)).sum()) if "_description_placeholder" in df.columns else "?"
                st.markdown(
                    f'<div class="diff-detect ph">DETECTED: Generic placeholder '
                    f'(identical text found in {n_ph_total} of {len(df)} courses in this catalog) — '
                    f'blocks Eightfold export</div></div>',
                    unsafe_allow_html=True,
                )
            elif is_mm:
                st.markdown(
                    f'<div class="diff-detect mm">DETECTED: Topic mismatch — '
                    f'title and description appear to be about different subjects '
                    f'(possible copy-paste error)</div></div>',
                    unsafe_allow_html=True,
                )
            elif desc_lang not in ("en", "unknown", ""):
                st.markdown(
                    f'<div class="diff-detect mm">DETECTED: Non-English description '
                    f'(language: {desc_lang}) — needs translation before Eightfold export'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="diff-detect ok">No description issues detected</div></div>',
                    unsafe_allow_html=True,
                )

        # Show enriched description if vocabulary context was added
        if enr_desc and enr_desc.strip() and enr_desc != clean_desc:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(
                f'<div class="diff-box">'
                f'<div class="diff-label" style="color:{C_DARK_GREEN}">'
                f'Eightfold-enriched version (Deloitte glossary context appended)</div>'
                f'<div class="diff-new" style="font-size:.77rem;">{enr_desc[:500]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ── TAB 3: HITL Review ─────────────────────────────────────────────────────

def tab_hitl(df: pd.DataFrame, queue_summary: dict) -> None:
    title_col = next((c for c in ["_clean_title", "Course Title"] if c in df.columns), "Course Title")
    resolved  = st.session_state.get("resolved_keys", set())
    actions   = st.session_state.get("resolved_actions", {})

    non_empty = {k: v for k, v in queue_summary.items() if v > 0}
    if not non_empty:
        st.info("No HITL items — all courses passed automated checks.")
        return

    total_items = sum(non_empty.values())
    done_items  = sum(1 for k in resolved if k.split("::")[1] in non_empty)
    pct = int(done_items / total_items * 100) if total_items else 0
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
      <div style="flex:1;background:{C_LGRAY};border-radius:4px;height:8px;">
        <div style="background:{C_GREEN};width:{pct}%;height:8px;border-radius:4px;"></div>
      </div>
      <div style="font-size:.8rem;color:{C_GRAY};white-space:nowrap;">
        <strong>{done_items}</strong> of {total_items} items reviewed ({pct}%)
      </div>
    </div>""", unsafe_allow_html=True)

    # Show known queues first (in canonical order), then any dynamic/AI queues
    canonical = [k for k in QUEUE_ORDER if k in non_empty]
    dynamic   = [k for k in non_empty if k not in QUEUE_ORDER]
    ordered_queues = canonical + dynamic

    selected = st.radio(
        "Select a queue to review:",
        ordered_queues,
        format_func=lambda k: (
            f"{k.split('_',1)[-1].replace('_',' ')} ({non_empty[k]} items)"
            + (" ✦" if k not in QUEUE_META else "")   # mark AI/dynamic queues
        ),
    )
    if not selected:
        return

    meta = _get_queue_meta(selected)
    variant      = meta.get("variant", "neutral")
    detected_lbl = meta.get("detected", "")
    action_lbl   = meta.get("action", "")
    approve_ctx  = meta.get("approve", "")
    reject_ctx   = meta.get("reject", "")
    edit_field   = meta.get("edit_field")
    edit_label   = meta.get("edit_label", "Your correction")
    badge_cls    = {"danger": "b-danger", "warn": "b-warn"}.get(variant, "b-neutral")

    st.markdown(
        f'<div class="section-h">'
        f'<span class="badge {badge_cls}">{non_empty[selected]} items</span>&nbsp;'
        f'{selected.replace("_", " ")}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Queue context box
    st.markdown(f"""
    <div style="background:#FAFAFA;border:1px solid {C_LGRAY};border-radius:3px;
    padding:12px 16px;margin-bottom:16px;font-size:.8rem;">
      <div style="margin-bottom:6px;"><strong>What was detected:</strong> {detected_lbl}</div>
      <div style="margin-bottom:6px;"><strong>What to do:</strong> {action_lbl}</div>
      <div style="margin-bottom:4px;color:{C_DARK_GREEN};">
        <strong>Approve</strong> = {approve_ctx}
      </div>
      <div style="color:{C_RED};">
        <strong>Reject</strong> = {reject_ctx}
      </div>
    </div>""", unsafe_allow_html=True)

    queue_rows = df[df["_hitl_queues"].astype(str).str.contains(selected, na=False)]

    for i, (_, row) in enumerate(queue_rows.iterrows()):
        cid      = _course_key(row)
        rkey     = f"{cid}::{selected}"
        is_done  = rkey in resolved
        done_act = actions.get(rkey, "")

        title   = str(row.get(title_col, "Untitled") or "Untitled")
        scope   = str(row.get("_scope", "") or "")
        cmts    = str(row.get("MF Comments", "") or "")
        rat     = str(row.get("_scope_rationale", "") or "")
        score   = row.get("_scope_score", "")

        # AI-generated description (if available)
        ai_draft       = str(row.get("_ai_description_draft", "") or "")
        ai_rationale   = str(row.get("_ai_description_rationale", "") or "")
        ai_confidence  = float(row.get("_ai_description_confidence", 0.0) or 0.0)
        has_ai_desc    = bool(ai_draft.strip())

        # Build what the pipeline proposes for THIS item
        proposal_text = ""
        if selected == "Q3_VendorRemap":
            proposal_text = f"Proposed vendor: <strong>{row.get('_clean_vendor', '?')}</strong> (confidence: {row.get('_vendor_confidence', 0):.0%})"
        elif selected == "Q4_BLMapping":
            proposal_text = f"Business Line: <strong>{row.get('_business_line', 'Unknown')}</strong> (confidence: {row.get('_bl_confidence', 0):.0%}) — <em>pipeline could not determine BL</em>"
        elif selected == "Q6_LowConfidenceScope":
            sc = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
            proposal_text = f"Proposed scope: <strong>{scope}</strong> (score {sc}) — {rat[:120]}"
        elif selected == "Q1_HighRiskRetirement":
            proposal_text = f"Proposed retirement date: <strong>{row.get('_proposed_discontinue_date', 'TBD')}</strong>"
        elif selected in ("Q5b_DescriptionRequired", "Q5c_DescriptionMismatch"):
            if has_ai_desc:
                proposal_text = ""  # shown separately as AI proposal block below
            else:
                proposal_text = "Click <strong>Edit & save correction</strong> to write or paste the real description for this course."
        elif selected == "Q5_Translation":
            proposal_text = f"Proposal: <strong>route to translator</strong> (detected language: {row.get('_description_language', '?')})"
        elif selected == "Q7_VocabClarification":
            proposal_text = f"Unknown terms flagged: <strong>{row.get('_vocab_pending', '')}</strong> — go to Vocabulary tab to add definitions"
        elif selected == "Q2_RegulatoryOverride":
            proposal_text = f"Proposed regulatory topics: <strong>{row.get('_regulatory_topics', '')}</strong> (confidence {row.get('_regulatory_confidence', 0):.0%})"

        card_cls  = "q-card done" if is_done else (
            "q-card " + ("warn" if variant == "warn" else "danger" if variant == "danger" else "q-card")
        )
        sb = scope_badge(scope)
        score_str = f" | Score: {score:.2f}" if isinstance(score, (int, float)) else ""

        action_badge = ""
        if is_done:
            action_badge = {
                "approve": f'<span class="badge b-green">Approved</span>',
                "reject":  f'<span class="badge b-danger">Rejected</span>',
                "edit":    f'<span class="badge b-warn">Edited</span>',
            }.get(done_act, f'<span class="badge b-done">Done</span>')

        ai_badge_html = '<span class="ai-badge">AI-generated</span>' if has_ai_desc else ""
        st.markdown(f"""
        <div class="{card_cls}">
          <div class="q-title">{sb}&nbsp;{title}&nbsp;{action_badge}{ai_badge_html}</div>
          <div style="font-size:.72rem;color:{C_GRAY};margin-bottom:6px;">{score_str}</div>
          {"" if is_done else f'<div class="q-issue">{cmts[:280]}</div>'}
          {"" if is_done or not proposal_text else f'<div class="q-proposal">{proposal_text}</div>'}
        </div>""", unsafe_allow_html=True)

        # AI description proposal block (shown when AI ran)
        if not is_done and has_ai_desc and selected in ("Q5b_DescriptionRequired", "Q5c_DescriptionMismatch"):
            conf_cls = "ai-conf-high" if ai_confidence >= 0.75 else ("ai-conf-med" if ai_confidence >= 0.5 else "ai-conf-low")
            conf_pct = f"{ai_confidence:.0%}"
            st.markdown(
                f'<div class="ai-proposal">'
                f'<strong>AI draft description:</strong><br>{ai_draft}'
                f'<div class="ai-rationale">Reasoning: {ai_rationale} &nbsp;|&nbsp; '
                f'Confidence: <span class="{conf_cls}">{conf_pct}</span></div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        if not is_done:
            bt1, bt2, bt3 = st.columns(3)
            if bt1.button("Approve", key=f"app_{i}_{selected}", use_container_width=True):
                _write_feedback(cid, selected, "approve")
                _mark_resolved(cid, selected, "approve")
                st.rerun()

            edit_key = f"edit_mode_{i}_{selected}"
            if bt2.button("Edit & save correction", key=f"edb_{i}_{selected}", use_container_width=True):
                st.session_state[edit_key] = True

            if bt3.button("Reject proposal", key=f"rej_{i}_{selected}", use_container_width=True):
                _write_feedback(cid, selected, "reject")
                _mark_resolved(cid, selected, "reject")
                st.rerun()

            if st.session_state.get(edit_key):
                # Determine edit default — prefer AI draft for description queues
                if selected in ("Q5b_DescriptionRequired", "Q5c_DescriptionMismatch", "Q5_Translation") and has_ai_desc:
                    default_val = ai_draft   # pre-fill with AI draft for human to refine
                elif edit_field and edit_field in row.index:
                    default_val = str(row.get(edit_field, "") or "")
                elif edit_field == "proposed_discontinue_date":
                    default_val = str(row.get("_proposed_discontinue_date", "") or "")
                elif edit_field == "regulatory_topics":
                    default_val = str(row.get("_regulatory_topics", "") or "")
                else:
                    default_val = ""

                if selected == "Q4_BLMapping":
                    opts = ["Audit/A&A", "Tax", "Consulting", "Advisory", "Enabling Areas", "Cross-LoS"]
                    new_val = st.selectbox(edit_label, opts, key=f"sel_{i}_{selected}")
                else:
                    new_val = st.text_area(
                        edit_label,
                        value=default_val,
                        key=f"ta_{i}_{selected}",
                        height=100 if selected in ("Q5_Translation", "Q5b_DescriptionRequired", "Q5c_DescriptionMismatch") else 60,
                    )

                sv1, sv2 = st.columns([1, 3])
                if sv1.button("Save", key=f"sv_{i}_{selected}", type="primary"):
                    _write_feedback(cid, selected, "edit", edit_label, str(new_val))
                    _mark_resolved(cid, selected, "edit")
                    if edit_key in st.session_state:
                        del st.session_state[edit_key]
                    st.rerun()
                if sv2.button("Cancel", key=f"cv_{i}_{selected}"):
                    if edit_key in st.session_state:
                        del st.session_state[edit_key]
                    st.rerun()

        st.markdown("&nbsp;", unsafe_allow_html=True)


# ── TAB 4: Vocabulary Manager ──────────────────────────────────────────────

def tab_vocab(df: pd.DataFrame) -> None:
    st.markdown(f"""
    <div style="background:#FFFBF0;border-left:4px solid {C_AMBER};border-radius:3px;
    padding:12px 16px;margin-bottom:12px;font-size:.82rem;">
      <strong>Human-validated glossary only.</strong>
      The pipeline detects Deloitte-specific codes and abbreviations it does not recognise
      and lists them below. <strong>Only you know what these mean</strong> — type the
      plain-language definition and click Save. The AI will never invent a definition.
      On the next Run Pipeline, each saved definition is appended to the course description
      so Eightfold AI has the context it needs to match skills correctly.
    </div>
    <div style="font-size:.8rem;color:{C_GRAY};margin-bottom:20px;">
      <strong>Two ways to add a definition:</strong>&nbsp;
      1. Type in the field below and click Save.&nbsp;
      2. Edit <code>config/deloitte_vocab.json</code> directly (key = term, value = definition),
      then click Run Pipeline.
    </div>""", unsafe_allow_html=True)

    vocab: dict[str, str] = {}
    if VOCAB_FILE.exists():
        vocab = json.loads(VOCAB_FILE.read_text(encoding="utf-8"))

    term_counts: dict[str, int] = {}
    if "_vocab_pending" in df.columns:
        for cell in df["_vocab_pending"].dropna().astype(str):
            for t in cell.split(","):
                t = t.strip()
                if t:
                    term_counts[t] = term_counts.get(t, 0) + 1

    # Also collect terms from _vocab_flags (detected but already in vocab)
    if "_vocab_flags" in df.columns:
        for cell in df["_vocab_flags"].dropna().astype(str):
            for t in cell.split(","):
                t = t.strip()
                if t and t not in term_counts:
                    term_counts[t] = term_counts.get(t, 0) + 0

    unknown = {k: v for k, v in term_counts.items() if k not in vocab}
    known   = {k: v for k, v in term_counts.items() if k in vocab}

    # Collect AI vocab proposals (dataset-level, stored on first row)
    ai_proposals: dict[str, dict] = {}
    if "_ai_vocab_proposals" in df.columns:
        raw_prop = str(df.at[df.index[0], "_ai_vocab_proposals"] or "{}")
        try:
            ai_proposals = json.loads(raw_prop) if raw_prop.strip() not in ("", "{}") else {}
        except Exception:
            ai_proposals = {}

    if unknown:
        has_ai = bool(ai_proposals)
        st.markdown('<div class="section-h">Unknown Terms — Definition Needed</div>',
                    unsafe_allow_html=True)
        st.caption(
            f"{len(unknown)} term{'s' if len(unknown) > 1 else ''} found across "
            f"{sum(unknown.values())} course occurrences — no validated definition yet"
        )
        if has_ai:
            st.markdown(
                f'<div style="background:#F0F7FF;border-left:4px solid #0057B8;border-radius:3px;'
                f'padding:10px 14px;font-size:.8rem;color:#003070;margin-bottom:12px;">'
                f'<span class="ai-badge">AI-researched</span>&nbsp;'
                f'The AI has proposed definitions for {len(ai_proposals)} term(s) below. '
                f'<strong>These are drafts — review each one carefully, edit if needed, then Save. '
                f'The AI may be wrong about Deloitte-specific meanings.</strong>'
                f'</div>',
                unsafe_allow_html=True,
            )

        for term, count in sorted(unknown.items(), key=lambda x: -x[1]):
            ai_prop = ai_proposals.get(term, {})
            ai_def  = ai_prop.get("definition", "")
            ai_conf = float(ai_prop.get("confidence", 0.0))
            ai_src  = ai_prop.get("source", "")
            ai_rat  = ai_prop.get("rationale", "")
            needs_human = ai_prop.get("needs_human_validation", True)

            st.markdown("---")
            c_left, c_right = st.columns([3, 7])
            ai_draft_tag = '<br><span class="ai-badge">AI draft</span>' if ai_def else ""
            c_left.markdown(
                f'<div style="padding:4px 0;">'
                f'<div class="vocab-term">{term}</div>'
                f'<div class="vocab-count">{count} course{"s" if count>1 else ""} affected</div>'
                f'{ai_draft_tag}'
                f'</div>', unsafe_allow_html=True)

            if ai_def:
                conf_cls = "ai-conf-high" if ai_conf >= 0.75 else ("ai-conf-med" if ai_conf >= 0.5 else "ai-conf-low")
                c_right.markdown(
                    f'<div class="ai-proposal" style="margin-bottom:6px;">'
                    f'<strong>AI-proposed definition:</strong> {ai_def}'
                    f'<div class="ai-rationale">{ai_rat}'
                    f'{" | Source: " + ai_src if ai_src else ""}'
                    f' | Confidence: <span class="{conf_cls}">{ai_conf:.0%}</span>'
                    f'{"  | ⚠ AI flagged as uncertain — validate carefully" if needs_human else ""}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

            defn = c_right.text_input(
                f"def_{term}", key=f"vi_{term}",
                value=ai_def,
                placeholder=f'What does "{term}" mean at Deloitte? (plain language)',
                label_visibility="collapsed",
                help="Edit the AI draft or type your own. Only saved definitions are used.",
            )
            sc1, sc2 = c_right.columns([1, 5])
            if sc1.button("Save", key=f"vsave_{term}", type="primary") and defn.strip():
                vocab[term] = defn.strip()
                VOCAB_FILE.write_text(json.dumps(vocab, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
                _vr._VOCAB_CACHE = None
                run_pipeline_cached.clear()
                st.success(f'Saved "{term}". Re-run the pipeline to apply to all {count} course(s).')
                st.rerun()
            sc2.caption("Saving accepts the definition as human-validated.")
    else:
        st.success("No unrecognised Deloitte terms — all detected terms have been validated by a reviewer.")

    if known:
        st.markdown("---")
        st.markdown('<div class="section-h">Human-Validated Terms</div>', unsafe_allow_html=True)
        st.caption("These definitions were saved by a reviewer and are applied on each pipeline run.")
        for term, count in sorted(known.items(), key=lambda x: -x[1]):
            col1, col2, col3 = st.columns([2, 6, 1])
            col1.markdown(
                f'<div style="padding:8px 0;">'
                f'<div class="vocab-term">{term}</div>'
                f'<div class="vocab-count">{count} course{"s" if count>1 else ""}</div>'
                f'</div>', unsafe_allow_html=True)
            col2.markdown(f'<div class="vocab-existing">{vocab.get(term,"")}</div>',
                          unsafe_allow_html=True)
            if col3.button("Edit", key=f"vedit_{term}"):
                st.session_state[f"vedit_mode_{term}"] = True
            if st.session_state.get(f"vedit_mode_{term}"):
                new_defn = st.text_input(f"Update: {term}", value=vocab.get(term, ""),
                                         key=f"vupd_{term}")
                ec1, ec2 = st.columns([1, 5])
                if ec1.button("Save", key=f"vupdsave_{term}", type="primary") and new_defn.strip():
                    vocab[term] = new_defn.strip()
                    VOCAB_FILE.write_text(json.dumps(vocab, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
                    _vr._VOCAB_CACHE = None
                    run_pipeline_cached.clear()
                    del st.session_state[f"vedit_mode_{term}"]
                    st.success(f"Updated '{term}'.")
                    st.rerun()
                if ec2.button("Cancel", key=f"vcancel_{term}"):
                    del st.session_state[f"vedit_mode_{term}"]
                    st.rerun()

    with st.expander(f"View full glossary ({len(vocab)} term{'s' if len(vocab)!=1 else ''})",
                     expanded=False):
        if vocab:
            gdf = pd.DataFrame([{"Term": k, "Definition": v} for k, v in sorted(vocab.items())])
            st.dataframe(gdf, use_container_width=True, hide_index=True, height=400)
        else:
            st.info("Glossary is empty — add definitions above.")


# ── TAB 5: Downloads ───────────────────────────────────────────────────────

def tab_downloads(queue_summary: dict) -> None:
    st.markdown('<div class="section-h">Pipeline Output Files</div>', unsafe_allow_html=True)
    for fname, mime in [
        ("catalog_with_proposals.xlsx",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("changeset_audit_log.jsonl", "application/octet-stream"),
    ]:
        fpath = OUTPUT_DIR / fname
        if fpath.exists():
            with open(fpath, "rb") as f:
                st.download_button(f"Download {fname}", f.read(), fname, mime,
                                   use_container_width=True, key=f"dl_{fname}")
    if FEEDBACK_FILE.exists():
        with open(FEEDBACK_FILE, "rb") as f:
            st.download_button("Download feedback.jsonl (reviewer decisions)",
                               f.read(), "feedback.jsonl", "application/octet-stream",
                               use_container_width=True, key="dl_feedback")

    st.markdown('<div class="section-h">HITL Queue Files</div>', unsafe_allow_html=True)
    queues_dir = OUTPUT_DIR / "hitl_queues"
    for qname in QUEUE_ORDER:
        count = queue_summary.get(qname, 0)
        if count == 0:
            continue
        q_file = queues_dir / f"{qname}.json"
        if not q_file.exists():
            continue
        meta = _get_queue_meta(qname)
        bc   = {"danger": "b-danger", "warn": "b-warn"}.get(meta.get("variant", ""), "b-neutral")
        c1, c2 = st.columns([4, 1])
        c1.markdown(
            f'<div style="padding:8px 0;">'
            f'<span class="badge {bc}">{count} items</span>'
            f'&nbsp;<strong style="font-size:.88rem">{qname}</strong><br>'
            f'<span style="font-size:.76rem;color:{C_GRAY}">{meta.get("detected","")}</span></div>',
            unsafe_allow_html=True)
        with open(q_file, "rb") as f:
            c2.download_button("Download", f.read(), f"{qname}.json", "application/json",
                               use_container_width=True, key=f"dlq_{qname}")


# ── Welcome screen ─────────────────────────────────────────────────────────

def render_welcome() -> None:
    st.markdown(f"""
    <div style="text-align:center;padding:50px 40px 30px;">
      <div style="font-size:3rem;font-weight:900;color:{C_LGRAY};letter-spacing:-1px;">Deloitte.</div>
      <div style="font-size:1.3rem;font-weight:800;color:{C_BLACK};margin:12px 0 8px;">
        Saba LMS Catalog Cleaning
      </div>
      <div style="font-size:.9rem;max-width:480px;margin:0 auto 28px;color:{C_GRAY};">
        Select a catalog source in the sidebar and click <strong>Run Pipeline</strong>.
      </div>
    </div>""", unsafe_allow_html=True)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    run_clicked, xlsx_path, ai_enabled, ai_model, ai_effort = render_sidebar()
    render_header()

    demo_mode = st.session_state.get("demo_toggle", False)

    if run_clicked and demo_mode:
        result = _load_demo_results()
        if result:
            df, qs, quality = result
            st.session_state.update({
                "df": df, "queue_summary": qs, "quality": quality,
                "has_results": True, "ai_enabled": True,
                "pipeline_running": False,
                "onboarding_done": st.session_state.get("onboarding_done", False),
                "run_ts": f"Demo mode — saved results loaded | {len(df)} courses",
                "resolved_keys": set(), "resolved_actions": {},
            })
            st.rerun()
        else:
            st.error("No demo snapshot found. Run the pipeline first.")

    elif run_clicked and xlsx_path:
        _reset_agent_caches()

        # Live progress — update these elements directly from within the pipeline
        st.markdown(f'<div style="font-size:.9rem;font-weight:700;color:{C_BLACK};">'
                    f'Pipeline running…</div>', unsafe_allow_html=True)
        prog_bar  = st.progress(0.0)
        prog_text = st.empty()
        prog_pct  = st.empty()

        def upd(pct: float, msg: str):
            prog_bar.progress(min(float(pct), 1.0))
            prog_text.markdown(
                f'<div style="font-size:.83rem;color:{C_GRAY};padding:2px 0;">{msg}</div>',
                unsafe_allow_html=True,
            )
            prog_pct.markdown(
                f'<div style="font-size:.72rem;color:{C_LGRAY};">{int(pct*100)}% complete</div>',
                unsafe_allow_html=True,
            )

        upd(0.01, "Starting…")
        try:
            df, qs, quality = run_pipeline_with_progress(
                xlsx_path, ai_enabled, ai_model, ai_effort, upd
            )
            st.session_state.update({
                "df": df, "queue_summary": qs, "quality": quality,
                "has_results": True,
                "ai_enabled": ai_enabled,
                "pipeline_running": False,
                "onboarding_done": st.session_state.get("onboarding_done", False),
                "run_ts": (f"Last run: {pd.Timestamp.now().strftime('%d %b %Y %H:%M')}"
                           f" | {len(df)} courses | AI: {'ON' if ai_enabled else 'OFF'}"),
                "resolved_keys": set(),
                "resolved_actions": {},
            })
            _save_demo_snapshot(df, qs, quality)
            st.rerun()
        except Exception as exc:
            st.error(f"Pipeline error: {exc}")
            raise

    # Onboarding (shown before first results, or if user re-opens)
    if not st.session_state.get("onboarding_done"):
        render_onboarding()
        if st.session_state.get("has_results"):
            st.markdown("---")
        else:
            return

    if not st.session_state.get("has_results"):
        render_welcome()
        return

    df      = st.session_state["df"]
    qs      = st.session_state["queue_summary"]
    quality = st.session_state["quality"]

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "  Dashboard  ",
        "  Course Proposals  ",
        "  HITL Review  ",
        "  Vocabulary  ",
        "  Downloads  ",
    ])
    with tab1: tab_dashboard(df, qs, quality)
    with tab2: tab_proposals(df)
    with tab3: tab_hitl(df, qs)
    with tab4: tab_vocab(df)
    with tab5: tab_downloads(qs)


if __name__ == "__main__":
    main()
