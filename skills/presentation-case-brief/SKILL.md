# Presentation case brief

Create an evidence-grounded, editable deck. First produce a narrative and
slide plan, then delegate only structured visual work (flowchart, chart, or
table) to a bounded child skill. Render through the deterministic PPT adapter;
never return a draft as final until schema, evidence, overflow, and rendered
visual checks pass. Keep uncertainty and source bindings visible in the IR.

## Child routing

Use `visual.flowchart` when a process, dependency, decision tree, or lifecycle
is central to a slide. Pass a typed graph request and consume its artifact
reference; do not ask the child to edit PPTX XML directly.
