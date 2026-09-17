# Ingestion testing progress

This document tracks the first ingestion-only testing phase. It follows the
pipeline benchmark guide in `C:\Users\ABHISHEK\Downloads\pipeline-benchmarking.md`:
deterministic tests run without live providers, and stress/provider tests remain
separate.

## Phase 1 — admission, extraction, and provenance matrix

Test files: `tests/component/test_ingestion_matrix.py` and
`tests/component/test_ingestion_http.py`

| # | Case | Expected behaviour | Test / supporting implementation | Status before execution |
|---:|---|---|---|---|
| 1 | Valid text | Admit, extract exact text, create evidence, preserve scope | `test_valid_text_file_is_extracted_with_scope_and_evidence`; `source_safety.py`, `extract.py`, `ingest.py` | PASS |
| 2 | Empty file | Reject clearly at admission | `test_empty_or_whitespace_only_text_is_rejected_clearly`; `source_safety.py` | PASS |
| 3 | Whitespace-only | Reject as no usable content | `test_empty_or_whitespace_only_text_is_rejected_clearly` | PASS |
| 4 | Very short / insufficient context | Preserve input and add no generated claims; minimum-context policy is not yet defined | `test_short_input_is_preserved_without_generated_content` | PASS for preservation; policy not implemented |
| 5 | Large file | Process within configured limit without truncation | `test_large_text_file_is_processed_with_exact_content` | PASS |
| 6 | Extremely large | Reject a file just over the configured 50 MiB boundary without reading it | `test_extremely_large_text_file_is_rejected_before_reading_content` | PASS |
| 7 | Malformed/corrupted | Reject mismatched file content before extraction | `test_malformed_file_is_rejected_at_admission`; existing corrupted PDF/PPTX tests | PASS |
| 8 | Unsupported type | Reject by extension | `test_unsupported_and_missing_files_are_rejected`; `extract.py` | PASS |
| 9 | Missing file | Reject with a missing-file error | `test_unsupported_and_missing_files_are_rejected` | PASS |
| 10 | Duplicate file | One logical ingestion for the same admission identity | `test_duplicate_admission_uses_one_logical_ingestion`; `test_np10_ingestion.py` | PASS |
| 11 | Same bytes, different names | Same content hash, distinct filename provenance; deduplication semantics need a decision | `test_same_content_has_same_hash_but_keeps_filename_provenance` | PASS for current behavior; policy undecided |
| 12 | Unicode/special characters | Preserve UTF-8 content exactly | `test_unicode_and_special_characters_round_trip` | PASS |
| 13 | Very long line | Do not silently truncate | `test_very_long_individual_line_is_not_truncated` | PASS |
| 14 | Metadata missing | Reject missing User/Case/Task admission metadata | `test_missing_and_invalid_ingestion_metadata_are_rejected`; `application.py:submit_ingestion` | PASS |
| 15 | Invalid metadata | Reject invalid classification or identity metadata | `test_missing_and_invalid_ingestion_metadata_are_rejected` | PASS |
| 16 | Extraction failure | Surface failure; never report success | `test_extraction_failure_is_not_silently_converted_to_success` | PASS |
| 17 | Partial extraction | Mark fallback and quality degradation explicitly | `test_partial_extraction_is_labeled_as_fallback_evidence`; existing image fallback test | PASS |
| 18 | Size boundary | Accept exactly `max_bytes`; reject one byte over | `test_file_size_boundary_accepts_exact_limit_and_rejects_one_byte_over`; `source_safety.py` | PASS |
| 19 | Normalization | Keep raw text; trim evidence representation deterministically | `test_content_normalization_trims_evidence_but_preserves_raw_text`; `evidence.py` | PASS |
| 20 | Provenance | Preserve source reference, hash, extractor provenance, and User/Case/Task scope | `test_provenance_and_scope_survive_indexing`; `evidence_index.py` | PASS |

HTTP boundary coverage is in `test_ingestion_http.py`: empty input is rejected
with a clear response, unsupported types are rejected, and a valid asynchronous
upload reaches admission with its bytes, hash, filename, and scope intact.

## Quality-engineering checklist mapping

The leader's checklist is broader than ingestion. The current phase has
completed items 0–5; items 6–45 belong to later memory, resolver, pipeline,
artifact, reliability, observability, and evaluation phases.

| Item | Area | Status | Evidence / boundary |
|---:|---|---|---|
| 0 | Inspect architecture/tests | PASS | Repository inspection and this tracker |
| 1 | Ingestion test matrix | PASS | `test_ingestion_matrix.py`, 20 requested cases |
| 2 | Empty/blank/low-context input | PASS for empty/blank and no invented text; policy not implemented | `source_safety.py`, `test_short_input_is_preserved_without_generated_content` |
| 3 | Large-file behaviour | PASS for configured admission limit | Sparse-file and 1 MiB tests |
| 4 | Malformed/unsupported input | PASS | Safety and HTTP tests |
| 5 | Provenance | PASS | Hash, filename, extractor, and User/Case/Task tests |
| 6–16 | Memory, isolation, stale/conflicting data, resolver | NOT STARTED | Later phases; outside ingestion |
| 17–21 | Pipeline and artifact contracts/quality | NOT STARTED | Later phases; outside ingestion |
| 22 | PPT benchmarking | NOT STARTED | Later presentation phase |
| 23–33 | Provider/reliability/concurrency/recovery | NOT STARTED | Later reliability phase |
| 34–38 | Status/DAG/trajectory/observability/telemetry | NOT STARTED | Later orchestration phase |
| 39–45 | Regression, golden/holdout, baselines, metrics, charts, report | PARTIALLY PREPARED | Existing benchmark modules; final report remains later |

## Repeated-run metrics

For this project, record both the individual outcomes and these summaries:

- **Pass@k**: at least one acceptable success in `k` attempts. This is useful
  for retryable or variable agent/provider work, but it must never hide the
  failed attempts.
- **pass^k**: every one of `k` repeated attempts passes. This is the stronger
  consistency gate for deterministic ingestion and safety behavior.

Example: if a case passes 4 of 5 attempts, it has `Pass@5 = true` but does not
meet `pass^5`. For deterministic ingestion, the release gate should normally
require `pass^k`, while later agent/provider experiments may report both.

The current ingestion matrix was repeated three times with these outcomes:

```text
Run 1: 17 passed, 1 skipped
Run 2: 17 passed, 1 skipped
Run 3: 17 passed, 1 skipped
```

After expanding the matrix and HTTP/fixture checks, the complete ingestion
focused run recorded `83 passed, 1 skipped`. The skipped case is an existing
opt-in live-provider test, not a failed ingestion assertion.

## Decisions deliberately not made

- No minimum character/token threshold was invented for “insufficient
  context.” A future decision must specify whether it is a hard rejection,
  a quality warning, or a downstream pipeline responsibility.
- Same bytes under different names currently retain separate source references
  while sharing a content hash. Whether this should deduplicate across names is
  a policy decision, because filenames are part of provenance.
- The normal deterministic extreme-size test uses a sparse file just over the
  configured 50 MiB admission limit. A true extraction stress benchmark still
  needs an agreed execution-time and memory budget.

## Execution note

The local test environment now uses Python 3.13.15, a repository `.venv`, and
the locked dependencies from `uv.lock`. The focused matrix and HTTP tests ran
with `25 passed`. The complete ingestion-focused regression command, including
the API server tests under explicit local Cognee configuration, ran with
`83 passed, 1 skipped`, with one unrelated Starlette deprecation warning. No
provider credentials were required.

The default API test environment selects Cognee Cloud and therefore requires
`COGNEE_API_KEY`. For deterministic local testing, set
`COGNEE_BACKEND=local` and `COGNEE_BASE_URL=http://localhost:8011` in the test
shell. This does not contact a live Cognee service in the covered tests.

For Windows hands-on runs, use a fresh user-owned temporary directory. A
fixed `--basetemp` directory inside the repository may have been created by a
different execution identity and then fail cleanup with `WinError 5`.

```powershell
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$base = Join-Path $env:TEMP "sudarshan-ingestion-$runStamp"
python -m pytest tests/component/test_ingestion_matrix.py -q --basetemp=$base -p no:cacheprovider
```
