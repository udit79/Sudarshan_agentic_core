# Sudarshan 2.0 release runbook

This is the operator checklist for a release candidate. The release is not
approved until the report from `api.release.run_release_checks` is green and
the environment-specific gates below have been recorded.

1. Freeze the release ID, Python/Node lockfiles, renderer versions, skill
   manifests, and benchmark corpus version.
2. Run the Python, Node gateway, frontend projection, Harness, MCP, A2A,
   sandbox, ingestion restart, backup/restore, and failure-injection suites.
3. Run the sanitized multimodal benchmark. Record quality, evidence
   faithfulness, tokens, cost, P50/P95 latency, queue wait, cache savings,
   repair rate, and human-correction time per artifact type.
4. Confirm Redis, object storage, MongoDB, provider credentials, telemetry,
   and Cognee health checks. Never paste credentials into the release report.
5. Inspect the generated PPTX/PDF/SVG/raster/video previews and record the
   visual-QA report IDs and human approval/rejection reasons.
6. Confirm rollback owner, restore point, migration notes, and the maximum
   acceptable data-loss/replay window.
7. Tag and publish only after every required gate is explicitly passed.

The release report is evidence, not a promise that a provider or external
service will remain available.
