# Sudarshan Quality Engineering Progress

This is the working project board for the staged testing effort. A checked item
means the current implementation has an automated test result recorded in the
linked phase document. It does not mean that every future live-provider,
multi-agent, load, or human-review scenario is complete.

## Current branch handoff

The current Phase 11 checkpoint and route for another developer or agent are
documented in `phase-11-branch-handoff.md`. The latest post-repair offline
regression is **729 passed, 8 skipped, 47 warnings**. The final authorized live
G01 presentation attempt reached the real provider but released no artifact;
Phase 11 remains open until a future explicitly authorized live run proves the
PPTX artifact path.

## Completed through the memory phase

- [x] 0. Inspect existing architecture/tests
- [x] 1. Ingestion test matrix
- [x] 2. Empty / blank / low-context input
- [x] 3. Large-file behaviour
- [x] 4. Malformed/unsupported input
- [x] 5. Provenance
- [x] 6. User memory
- [x] 7. Case memory
- [x] 8. Task memory
- [x] 9. Memory write rules (current lifecycle boundary)
- [x] 10. Memory retrieval
- [x] 11. Cross-user isolation
- [x] 12. Cross-case isolation
- [x] 13. Cross-task isolation
- [x] 14. Stale information
- [x] 15. Conflicting information
- [x] 16. Resolver relevance (conservative zero-score guard)

## Not started

- [x] 17. Pipeline contracts (deterministic route/request/output matrix; live provider lifecycle remains pending)
- [ ] 18. Insufficient-context generation (partial: explicit missing-information clarification passes; empty-context policy remains open)
- [x] 19. Malformed model output (typed schema boundary; live model injection remains pending)
- [x] 20. Artifact correctness (PPTX/SVG/PNG/PDF/video integrity, manifest provenance, tamper detection)
- [ ] 21. Artifact quality (objective proxies exist; human visual review and final-slide evidence policy remain open)
- [ ] 22. PPT benchmarking
- [x] 23. Provider failure (deterministic provider/HTTP boundary; live provider failures remain pending)
- [x] 24. Timeout
- [x] 25. Cancellation
- [x] 26. Retry (bounded deterministic retry paths)
- [x] 27. Duplicate retry (admission/cache protection)
- [x] 28. Partial/degraded output
- [x] 29. Memory outage (deterministic fallback; live backend outage remains pending)
- [x] 30. Cache miss
- [x] 31. Concurrent execution (duplicate submission and parallel case-scoped runs)
- [x] 32. Restart/recovery (deterministic durable queue/DAG/progress fixtures; live process-kill test remains pending)
- [x] 33. Artifact duplication (stable same-run/content manifest identity)
- [x] 34. Status (deterministic projection agreement; crash-authority policy remains open)
- [x] 35. DAG (public dependency/status/output projection)
- [x] 36. Trajectory (safe event timeline and parallel lanes)
- [x] 37. Observability (memory/provider/error visibility with redaction)
- [x] 38. Telemetry (latency/usage/cost projection with duplicate receipt protection)
- [x] 39. Full regression (latest: 705 passed, 8 skipped, 32 warnings; Cloud-configured API run remains pending)
- [ ] 40. Golden cases (G01 live recall recovered; quality gate rejected the final draft; replay fixture added)
- [ ] 41. Holdout cases
- [ ] 42. External AI baseline
- [x] 43. Quality metrics (sanitized objective dataset separates measured, unavailable, and human-review fields; live quality remains open)
- [x] 44. Matplotlib charts (traceable CSV/PNG export and chart manifest; repeated live percentiles remain open)
- [ ] 45. Final test report

## Evidence

- Ingestion evidence: `ingestion-testing-progress.md`
- Memory evidence: `memory-testing-progress.md`
- Memory matrix: `tests/component/test_memory_behaviour_matrix.py`
- Latest memory matrix result: **20 passed**
- Latest memory-focused regression result: **53 passed**
- Isolation matrix: `tests/component/test_case_isolation_matrix.py`
- Pipeline contract matrix: `tests/component/test_pipeline_contract_matrix.py`
- Pipeline contract report: `pipeline-contract-testing-report.md`
- Artifact report: `artifact-testing-report.md`
- Failure/recovery report: `failure-recovery-testing-report.md`
- Execution safety report: `execution-safety-testing-report.md`
- Observability/telemetry report: `observability-telemetry-testing-report.md`
- Latest Phase 9 matrix result: **7 passed**; affected regression: **149 passed, 1 warning**
- First-half audit: `first-half-quality-audit.md`
- Latest full deterministic local regression: **705 passed, 8 skipped, 32 warnings**
- Phase 11 golden/holdout catalogue: `phase-11-golden-and-holdout-cases.md`
- Agentic performance/cost measurement report: `agentic-system-performance-and-cost-report.md`
- Live G01 checkpoint: same-case bounded context recovered and other-case
  isolation passed after the Cognee adapter fix; `run-g01-live-04` reached the
  real agents but failed the quality gate twice and produced no artifact
- Offline G01 replay fixture: **1 passed**; it verifies expected facts,
  unknowns, case scope, source reference, and absence of foreign context
- Agentic usage instrumentation: **4 focused tests passed**; affected
  telemetry/pipeline regression **134 passed**; provider cost remains
  explicitly unavailable until pricing/billing reconciliation is configured
- First measured live G01 usage run: **HTTP 202 in 114 ms; 35,330
  provider-reported tokens; 69,177 ms CrewAI wall time; quality gate failed;
  no artifact**. Spend-control and normal-route DAG gaps remain open.
- Phase 11 sanitized benchmark-record matrix: **3 passed**; queue, wall, and
  provider timing remain distinct, and unavailable fields stay `null`.
- Offline retry-spend guard matrix: **5 passed**; explicit provider budgets
  deny a second provider attempt, while provider-native first-request caps
  remain open.
- GPT-5 provider-parameter compatibility: **14 focused tests passed**; the
  budgeted GPT-5 request contains `max_completion_tokens` and no legacy
  `max_tokens`, while legacy model routing remains unchanged.
- Budgeted prompt/output-bound matrix: **9 passed**; dynamic fields are
  bounded and completion caps are applied without changing the default path.
- Latest isolation result: **8 passed**; artifact-evidence ownership validation
  is now enforced before registration side effects.
- Current evidence is application-level and deterministic; live Cognee and
  multi-agent consistency are intentionally later phases.
- Benchmark results checkpoint: `benchmark-results/benchmark-results-report.md`
- Benchmark source dataset: `benchmark-results/benchmark-results.json`
- Benchmark charts and traceability manifest: `benchmark-results/*.png`,
  `benchmark-results/benchmark-results.csv`, and `benchmark-results/chart-manifest.json`
- One-run live artifact runbook: `phase-11-live-artifact-runbook.md`; the
  sanitized G01 presentation request contract passed **33 focused tests**.

## Open decisions carried forward

- Add a first-class memory approval/promotion operation, or keep
  `PENDING_REVIEW` as the boundary.
- Decide whether remote Cognee writes require exactly-once idempotency.
- Define semantic relevance thresholds for positive provider scores.
- Provide Cognee Cloud credentials before live integration tests; the current
  deterministic memory phase does not require them.
- Re-run one controlled G01 generation request after the compatibility fix;
  only then record real provider latency, usage, cost, and artifact quality.
- Corrected live G01 rerun: **provider parameter accepted; 1,385 provider-
  reported tokens; 23,559 ms wall time; structured response hit the 240-token
  cap; no artifact**. The remaining issue is budget allocation, not the old
  `max_tokens` incompatibility.
- G01 budget experiments: **600-token cap failed after 33,247 ms; 1,200-token
  cap failed after 59,266 ms**. The first two analysis stages completed at
  1,200, but the final structured response still exceeded the cap. A
  contract-specific `provider_output_token_budget` override is now tested
  offline; no further paid run was started.
- Final G01 controlled budget run: **12,000 configured vs 66,084 observed
  provider tokens; 55,399 ms wall time; no artifact**. All four pipeline
  stages reached completion events, but the spend guard correctly failed the
  run. Phase 11 live artifact generation remains open and cost-bounding is now
  the priority.
- Phase 11A token-optimization route: `phase-11-token-optimization.md`.
  The additive reservation ledger and benchmark-only preflight switch are now
  implemented. Focused preflight/profile/audit tests passed **28**, affected
  regression passed **111**, and the latest full offline regression after the
  audit boundary check passed **722 passed, 8 skipped, 32 warnings**. The LLM
  key should remain disabled until a
  pipeline-specific profile is reviewed.
- The executive-summary diagnostic profile is now recorded in
  `pipelines/orchestrator/budget_profiles.py`. It is deliberately unapproved
  and rejects the current G01 receipt-derived reservation before provider
  execution; no cheaper live budget has been invented.
- The sanitized G01 dynamic-input audit measured **165 estimated tokens**
  (including 97 tokens for the 387-character memory context). This shows that
  the previous 54,165 input-token receipt is dominated by provider/system,
  tool, or intermediate-task context rather than the raw G01 evidence. The
  remaining source is not guessed; stage-level provider receipt measurement is
  still required.
- Stage-level usage capture is now attached to task callbacks using sanitized
  counters only; it does not add stage values to aggregate totals. Focused
  usage/audit/budget tests passed **39**, and the latest full regression passed
  **723 passed, 8 skipped, 32 warnings**. A live run is still required to
  populate real stage receipts.
- Benchmark-only intermediate context compaction is now available through
  `provider_context_compaction=true`; it keeps validated structured output and
  removes verbose raw task text before downstream task context. Focused tests
  passed **45**, and the latest full regression passed **724 passed, 8 skipped,
  32 warnings**. The default path remains unchanged.
- The next live gate is deliberately one `presentation` run only. It has a
  two-slide constraint, compaction enabled, a declared one-run provider ceiling,
  and a manifest/download verification path. The LLM key remains disabled until
  the operator explicitly starts that run.
- Live presentation attempts are tracked in `phase-11-live-artifact-runbook.md`:
  the first stopped at a local Cognee socket permission error; the network
  recovery reached the PPT flow but exposed and fixed the missing `constraints`
  template input. The post-fix full regression is **728 passed, 8 skipped,
  47 warnings**. A post-fix live artifact is still pending.
- The post-fix live presentation attempt reached the real provider and all PPT
  agent stages, recording **42,040 provider tokens** and **32,406 ms** provider
  latency, but failed at artifact rendering because the model selected an
  unvalidated template. The PPT prompt now defaults to `native-default`; the
  follow-up focused tests passed **40**, and the full offline regression now
  passes **729 passed, 8 skipped, 47 warnings**. The server is stopped and no
  further paid attempt was started.
- The offline repair normalizes unsupported model-selected PPT template IDs to
  `native-default` when no validated custom template contract exists. It
  preserves slide content and passed **6** focused tests plus **32** affected
  PPT/artifact regression tests. The post-repair full offline regression is
  **729 passed, 8 skipped, 47 warnings**. No further paid provider call was
  made.
- The final authorized G01 presentation retry (`run-g01-presentation-live-final-01`)
  reached routing, memory, prompt crafting, and all three PPT agent stages, but
  failed again at the renderer boundary because the model selected a
  non-default template without a validated contract. It recorded **31,735 input
  tokens**, **10,225 output tokens**, **21,760 cache-read tokens**, and **29,915
  ms** provider latency. No artifact was released; Phase 11 remains open until
  this boundary is fixed and re-tested under an explicitly authorized run.
