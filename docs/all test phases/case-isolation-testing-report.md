# User/Case/Task isolation test report

## Mentor vocabulary

**Isolation** means that an authorized request can see only the evidence and
memory permitted by its identity and current case/task. In this repository the
identity is `AccessContext`; exact evidence is owned by `EvidenceIndex`; memory
recall is governed by `MemoryManager`; public artifact access is checked by
`api.server` before download.

## Scenario

```text
User A
├── Case A
│   ├── Evidence A1 / task-a1
│   └── Evidence A2 / task-a2
└── Case B
    ├── Evidence B1 / task-b1
    └── Evidence B2 / task-b2

User B
└── Case C
    └── Evidence C1 / task-c1
```

Every evidence item contains a case-specific sentinel such as `evidence-a1`,
so the tests inspect returned content and not merely different identifiers.

## WHAT / WHY / WHERE / INPUT / OUTPUT / TEST / RESULT

| WHAT | WHY | WHERE | INPUT → expected output | Test / result |
|---|---|---|---|---|
| Case A evidence resolution | A case request must not be polluted by a sibling case or user | `EvidenceIndex.search_text()` | Case A query → only A1/A2 content | `test_case_requests_return_only_authorized_evidence_content` — PASS |
| Deliberate cross-case/user reads | Authorization must reject direct attempts, not only normal queries | `EvidenceIndex.get_evidence()` | A asks for B; B asks for A; User B asks for A → empty/`EvidenceNotFoundError` | `test_deliberate_cross_case_and_cross_user_evidence_access_is_denied` — PASS |
| Task isolation | Task working information is narrower than case information | `EvidenceIndex._scope_rows()` + `MemoryManager` | Task A1 query → A1/task A1 only; Task A2 cannot see A1 note | `test_task_requests_do_not_receive_sibling_task_evidence` — PASS |
| Memory resolver scope | Retrieved prompt context must contain only allowed case facts | `MemoryManager.recall()` → `ContextBuilder` | Case A query → A1/A2 context; no B/C sentinel text | `test_memory_resolver_returns_case_a_content_without_case_b_or_user_b` — PASS |
| Memory write scope | Writes must be tagged to the exact case node set | `MemoryManager.remember()` | A/B/C projections → matching case node sets | `test_memory_writes_use_the_exact_case_node_set` — PASS |
| Generated artifact content | A Case A output must not contain B/C evidence | `ArtifactStore.register()` + downloaded file | A-authorized evidence → artifact with only A content | `test_case_a_generated_artifact_contains_only_case_a_evidence` — PASS |
| Public artifact access | A wrong case or user must not download another case's output | `api.server` artifact route | Correct headers → 200; wrong case/user → 403 and no artifact body | `test_public_artifact_access_denies_wrong_case_and_user` — PASS |
| Evidence-reference validation | Artifact evidence IDs should also belong to the artifact case | `ArtifactStore.register()` | Case A artifact with B evidence ID → reject before side effects | `test_artifact_registration_rejects_foreign_evidence_ids` — PASS |

## Result

Latest run: **8 passed**.

The memory and evidence isolation boundaries passed with content-level
assertions. Case A context did not contain Case B or User B sentinels; task
siblings were also excluded. Public artifact download authorization passed for
wrong case and wrong user attempts.

`ArtifactStore.register()` now checks every supplied `evidence_id` through the
authoritative `EvidenceIndex` before copying the artifact, writing a manifest,
or creating a quality-report side effect. A Case A artifact naming Case B
evidence is rejected. Artifacts without evidence bindings remain compatible.

The public artifact route still performs its independent owner/case/task check.
These are separate protections: registration protects lineage, while download
protects access.

## Credentials and next action

No model, MongoDB, Cognee, or `.env` credentials are needed for this matrix.
Live Cognee isolation testing can be added later with `COGNEE_API_KEY`,
`COGNEE_TENANT_ID`, and a disposable tenant/dataset containing sanitized test
sentinels.
