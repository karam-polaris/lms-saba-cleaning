"""Agent 1 -- IngestProfiler

Loads the catalog XLSX, normalises headers (single-row or two-row),
repairs encoding corruption, deduplicates delivery types, parses dates,
and emits:
  - data/processed/catalog_raw.parquet
  - data/processed/profile_report.json
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import ftfy
import openpyxl
import pandas as pd

DATE_COLS = [
    "Cat Item Available Date", "Discontinue Date", "Last Completion Date",
    "Last Enrollment Date", "Latest Class Date", "Course Creation Date",
]

NUMERIC_COLS = [
    "FY24 Completions", "FY25 Completions", "FY26 Completions",
    "FY26 Enrollments", "Learning Hours", "Cpe Hours",
]

TEXT_COLS = [
    "Course Title", "Mandatory Field: Course Title",
    "Catalog Item Description",
    "Course Vendor Name", "Course Category", "Course Classification",
    "Full Delivery Type", "Intended Audience", "Course Audience Type Name",
    "Cpe Subject Area", "Reference: Domain", "Course Number",
]

ENCODING_SENTINEL = "\ufffd"


# -- Header helpers --

def _detect_two_row_header(rows: list) -> bool:
    """True when row-1 looks like group labels and row-2 looks like field labels."""
    if len(rows) < 3:
        return False
    row1 = rows[1]
    for v in row1:
        if isinstance(v, (int, float)):
            return False
        if hasattr(v, "year"):       # datetime value -> it's data, not a header
            return False
    return True


def _combine_headers(row0: tuple, row1: tuple) -> list[str]:
    headers, prev_group = [], None
    for g, d in zip(row0, row1):
        g = str(g).strip() if g else ""
        d = str(d).strip() if d else ""
        if g:
            prev_group = g
        group = prev_group or ""
        if group and d and group.lower() not in d.lower() and d.lower() not in group.lower():
            headers.append(f"{group}: {d}")
        elif d:
            headers.append(d)
        elif group:
            headers.append(group)
        else:
            headers.append(f"_col_{len(headers)}")
    return headers


# -- Core transforms --

def _fix_cell(val: object) -> str:
    if val is None:
        return ""
    return ftfy.fix_text(str(val))


def repair_encoding(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    repaired = 0
    for col in TEXT_COLS:
        if col not in df.columns:
            continue
        before = df[col].astype(str)
        df[col] = df[col].apply(lambda v: _fix_cell(v) if pd.notna(v) else v)
        after = df[col].astype(str)
        repaired += int((before != after).sum())
    return df, repaired


def flag_encoding_issues(df: pd.DataFrame) -> pd.DataFrame:
    mask = pd.Series(False, index=df.index)
    for col in TEXT_COLS:
        if col in df.columns:
            mask |= df[col].astype(str).str.contains(ENCODING_SENTINEL, na=False)
    df["_encoding_issues"] = mask
    return df


def dedup_delivery_types(df: pd.DataFrame) -> pd.DataFrame:
    col = "Full Delivery Type"
    if col not in df.columns:
        return df

    def _dedup(val):
        if pd.isna(val) or not str(val).strip():
            return val
        parts = [p.strip() for p in str(val).split(",")]
        return ",".join(list(dict.fromkeys(parts)))

    df[col] = df[col].apply(_dedup)
    return df


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    for col in DATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def parse_numerics(df: pd.DataFrame) -> pd.DataFrame:
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


# -- XLSX loader --

def load_xlsx(path: str) -> pd.DataFrame:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        raise ValueError(f"Empty worksheet in {path}")

    if _detect_two_row_header(rows):
        headers = _combine_headers(rows[0], rows[1])
        data_rows = rows[2:]
        print("[IngestProfiler] Detected two-row header structure -- combining group + detail labels")
    else:
        headers = [str(h).strip() if h is not None else f"_col_{i}" for i, h in enumerate(rows[0])]
        data_rows = rows[1:]
        print("[IngestProfiler] Single-row header detected")

    df = pd.DataFrame(data_rows, columns=headers)
    df = df.dropna(axis=1, how="all")          # drop spacer columns
    df.columns = [c.strip() for c in df.columns]
    return df


# -- Profile --

def compute_profile(df: pd.DataFrame, repaired: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    profile: dict = {
        "generated_at": now,
        "total_rows": len(df),
        "encoding_cells_repaired": repaired,
        "columns": {},
        "quality_metrics": {},
    }

    for col in df.columns:
        if col.startswith("_"):
            continue
        is_null = df[col].isna() | (df[col].astype(str).str.strip() == "")
        null_count = int(is_null.sum())
        null_pct = round(null_count / len(df) * 100, 1) if len(df) else 0
        top_vals = (
            df.loc[~is_null, col].astype(str)
            .value_counts().head(5).to_dict()
        )
        profile["columns"][col] = {
            "null_count": null_count,
            "null_pct": null_pct,
            "top_values": top_vals,
        }

    # Key quality KPIs (mirrors HighLights 1 sheet)
    q = profile["quality_metrics"]
    fy_cols = ["FY24 Completions", "FY25 Completions", "FY26 Completions"]
    if all(c in df.columns for c in fy_cols):
        zero_all = int(
            ((df["FY24 Completions"].fillna(0) == 0) &
             (df["FY25 Completions"].fillna(0) == 0) &
             (df["FY26 Completions"].fillna(0) == 0)).sum()
        )
        q["zero_completions_all_fy"] = zero_all
        q["zero_completions_pct"] = round(zero_all / len(df) * 100, 1) if len(df) else 0

    for check_col, key in [
        ("Course Business Owner1", "missing_business_owner"),
        ("Discontinue Date",        "missing_discontinue_date"),
        ("Course Vendor Name",       "missing_vendor"),
        ("Course Category",          "missing_category"),
    ]:
        if check_col in df.columns:
            null_mask = df[check_col].isna() | (df[check_col].astype(str).str.strip() == "")
            q[key] = int(null_mask.sum())

    if "_encoding_issues" in df.columns:
        q["encoding_issues_rows"] = int(df["_encoding_issues"].sum())

    return profile


# -- Main entry point --

def run(xlsx_path: str, output_dir: str = "data/processed") -> pd.DataFrame:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[IngestProfiler] Loading: {xlsx_path}")
    df = load_xlsx(xlsx_path)
    print(f"[IngestProfiler] Shape: {len(df)} rows × {len(df.columns)} columns")

    df, repaired = repair_encoding(df)
    print(f"[IngestProfiler] Encoding repair: {repaired} cells fixed")

    df = flag_encoding_issues(df)
    enc_rows = int(df["_encoding_issues"].sum())
    if enc_rows:
        print(f"[IngestProfiler] [WARN] {enc_rows} rows still have encoding issues -> _encoding_issues=True")

    df = parse_dates(df)
    df = parse_numerics(df)
    df = dedup_delivery_types(df)

    # Write parquet
    parquet_path = out / "catalog_raw.parquet"
    df.to_parquet(parquet_path, index=False)
    print(f"[IngestProfiler] [OK] {parquet_path}")

    # Write profile
    profile = compute_profile(df, repaired)
    profile_path = out / "profile_report.json"
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, default=str)
    print(f"[IngestProfiler] [OK] {profile_path}")

    # Print quick quality summary
    q = profile["quality_metrics"]
    print(f"\n  -- Quality snapshot --")
    for k, v in q.items():
        print(f"     {k}: {v}")
    print()

    return df


if __name__ == "__main__":
    import sys
    xlsx = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\karam\Downloads\PoC_Saba_Catalog_Clean_Format_150.xlsx"
    out  = sys.argv[2] if len(sys.argv) > 2 else "data/processed"
    run(xlsx, out)
