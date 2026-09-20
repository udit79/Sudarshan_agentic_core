# Phase 11 checkpoint — ingestion to resolver evidence binding

Status: **offline binding verified; one controlled live run remains**

## WHAT

Make the selected output run consume the exact evidence produced by ingestion.
The run accepts an `evidence_refs` list containing evidence IDs from the
ingestion status receipt. The application resolves those IDs through the
existing scoped `EvidenceIndex` and puts bounded records into the existing
`ContextPack`.

## WHY

An ingestion success only proves that a source was parsed, indexed, and (when
available) projected to memory. It does not by itself prove that a later PPT,
video, infographic, or advisory request used that source. This binding step is
the missing evidence for the product flow:

`upload -> ingest -> evidence_id -> run evidence_refs -> resolver ContextPack -> pipeline -> artifact`

## WHERE

- Binding: `integrations/deepseek_harness/application.py`
- Exact evidence and scope checks: `ingestion_pipelines/evidence_index.py`
- HTTP boundary: `api/server.py` (`POST /runs`)
- MCP boundary: `integrations/deepseek_harness/mcp_server.py`
- Tests: `tests/component/test_evidence_binding.py`,
  `tests/component/test_ingestion_http.py`, and
  `tests/component/test_ingestion_application_cache.py`

## INPUT

Use the `evidence_ids` returned by `GET /ingestions/{ingestion_id}` after the
upload finishes. A run may send either an ID string or an object with an ID and
optional matching `document_id`:

```json
"evidence_refs": [
  {"evidence_id": "<ID_FROM_INGESTION_STATUS>", "document_id": "<DOCUMENT_ID>"}
]
```

The `user_id` and `case_id` on the run must match the ingested evidence. A
later task in the same case may reuse source evidence; provenance keeps the
original ingestion task visible as `source_task_id`. This does not loosen
task-memory isolation.

## OUTPUT

The resolver creates a bounded `ContextPack` containing:

- selected evidence content, bounded by the request token budget;
- `evidence_id` and `document_id`;
- source reference and original ingestion task provenance;
- User/Case/Task scope metadata;
- a deterministic retrieval trace ID.

The run does not accept raw file content through `evidence_refs`. Foreign User
or Case evidence is rejected with a generic permission error, without
revealing whether the foreign ID exists.

## TEST

With the LLM key disabled, run:

```powershell
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$base = Join-Path $env:TEMP "sudarshan-evidence-binding-$runStamp"
.venv\Scripts\python.exe -m pytest `
  tests/component/test_evidence_binding.py `
  tests/component/test_ingestion_application_cache.py `
  tests/component/test_ingestion_http.py `
  tests/component/test_application_boundary.py `
  tests/component/test_harness_parity.py `
  -q --basetemp=$base -p no:cacheprovider
```

Observed checkpoint result: **24 passed, 2 warnings**.

The first attempt without `--basetemp` was not a product result: Windows
denied access to the default `pytest-of-ABHISHEK` directory. Always use the
explicit temporary directory command above on this workstation.

## LIVE CLOSEOUT STILL REQUIRED

This change is not yet a live artifact pass. The next controlled run should:

1. ingest the sanitized G01 file;
2. poll ingestion status and copy `document_id` plus `evidence_ids[0]`;
3. submit the same G01 presentation request with `evidence_refs`;
4. inspect telemetry and the released artifact;
5. confirm the deck contains only G01 evidence and its source reference.

Keep the LLM key disabled until the offline test command passes and the memory
health probe is reachable. Then restore it for one explicitly authorized run,
record actual usage/latency, and disable it again.
