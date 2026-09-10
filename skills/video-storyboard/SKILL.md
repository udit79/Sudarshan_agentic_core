# Video storyboard

Split work into script, storyboard, scene media, composition, and QA stages.
Scenes are independently fingerprinted and retryable. Keep narration,
visual intent, duration, evidence IDs, and provider constraints in the
storyboard IR. Never regenerate successful scenes when a later scene fails;
the composer consumes immutable scene references and preserves order.
