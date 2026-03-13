# Saba LMS Catalog Cleaning Pipeline

Automated cleaning pipeline for the Saba LMS catalog, preparing data for
Eightfold AI, Storefront, and Galaxy.  All automated proposals are routed
to human review queues before any write-back to Saba.

## Quick Start

```bash
# 1. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 2. Run on the PoC file (default)
python pipeline.py

# 3. Run on any catalog XLSX
python pipeline.py "path/to/catalog.xlsx" "data/output"
```

## Outputs

| File | Contents |
|------|----------|
| `data/processed/catalog_raw.parquet` | Cleaned, typed DataFrame |
| `data/processed/profile_report.json` | Data quality KPIs |
| `data/output/catalog_with_proposals.xlsx` | Full working copy with all agent columns |
| `data/output/hitl_queues/<Q>.json` | One file per HITL queue |
| `data/output/changeset_audit_log.jsonl` | Row-level audit trail |

## HITL Queues

| Queue | Description |
|-------|-------------|
| Q1_HighRiskRetirement | Regulatory or active courses flagged for retirement |
| Q2_RegulatoryOverride | Regulatory classification below 75% confidence |
| Q3_VendorRemap | Fuzzy or unknown vendor name mapping |
| Q4_BLMapping | Unknown or low-confidence Business Line |
| Q5_Translation | Non-English description without approved translation |
| Q5b_DescriptionRequired | Placeholder or missing description (blocks Eightfold) |
| Q5c_DescriptionMismatch | Title and description appear to cover different topics |
| Q6_LowConfidenceScope | Scope is Review or score < 0.60 |
| Q7_VocabClarification | Unknown Deloitte abbreviations found in title/description |

## Agent Pipeline

```
XLSX
 |
 v
[1] IngestProfiler         load + encoding repair + date parsing + profile
 |
 v
[2] AssessmentDetector     identify assessments (title regex, code suffix A)
[3] RegComplianceClassifier flag regulatory/compliance courses (keyword + CPE)
 |
 v
[4] ScopeClassifier        score and label: In-Scope / Review / Out-of-Scope
[5] SunsetPlanner          propose retirement dates, flag implausible dates
 |
 v
[6] TitleNormalizer        strip placeholders, version noise, apply title-case
[7] DescriptionSanitizer   strip HTML, detect placeholders & topic mismatches
[8] VendorResolver         alias dict + fuzzy matching → controlled vendor list
[9] BLMapper               domain/keyword rules → Business Line assignment
[10] VocabResolver         detect Deloitte codes/acronyms, enrich descriptions
 |
 v
[11] ChangeSetWriter       HITL queue assignment + Excel output + audit log
```

## Configuration Files

| File | Purpose |
|------|---------|
| `config/deloitte_vocab.json` | Deloitte abbreviation glossary (grows with HITL feedback) |
| `config/regulatory_keywords.json` | Keyword lists per regulatory topic |
| `config/bl_rules.json` | Business Line mapping rules |
| `config/vendor_alias_dict.json` | Vendor name normalisation dictionary |
| `config/eightfold_defaults.json` | URL template and image/currency maps for Eightfold export |
| `config/skills_taxonomy.json` | Starter skills list for Eightfold skill tagging |

## PoC Results (150-row sample)

| Metric | Count |
|--------|-------|
| Rows processed | 150 |
| In-Scope | 59 |
| Review | 90 |
| Out-of-Scope | 1 |
| Assessments detected | 44 |
| Regulatory courses | 90 |
| Placeholder descriptions | 95 (63%) |
| Description mismatches | 47 (31%) |
| Needs translation | 35 (23%) |
| Eightfold export ready | 14 |
| Eightfold blocked (needs fix) | 117 |

## Next Steps

1. **Unblock course URL** — confirm Saba deep-link pattern with IT and update
   `config/eightfold_defaults.json` → enables `EightfoldExporter` agent (Phase 3)
2. **Work the HITL queues** — open each JSON in `data/output/hitl_queues/` and
   resolve items; approved changes feed back into `config/deloitte_vocab.json`
   and `config/vendor_alias_dict.json` for the next run
3. **Run on full catalog** — replace the PoC file path with the full XLSX and
   re-run `python pipeline.py`
