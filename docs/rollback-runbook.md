# Sudarshan 2.0 rollback runbook

Rollback is a controlled operation owned by the release operator and backend
owner.

1. Stop new admissions at the gateway while allowing already accepted runs to
   finish or be cooperatively cancelled.
2. Record the active release ID, queue leases, run IDs, artifact manifests, and
   the latest tamper-evident audit cursor.
3. Restore the last approved application/renderer/skill package versions.
4. Restore databases and object storage only from the matching verified
   snapshot; never delete audit rows to make a rollback appear clean.
5. Reconcile queued jobs against the restored run state. Requeue only jobs with
   an unexpired lease and valid input lineage; otherwise mark them for review.
6. Run health, authorization, artifact integrity, and one synthetic end-to-end
   transformation before reopening admissions.
7. Publish the rollback report with cause, affected run IDs, replay decisions,
   data-loss window, and follow-up owner.
