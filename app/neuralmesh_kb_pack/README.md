# NeuralMesh mock knowledge-base pack (SYNTHETIC)

Everything here is invented for prototyping. No real RPG data. Fictional names are marked "(fictional)".

    pip install pyyaml
    python kbgen.py          # rebuilds data_pack/ from kb/*.yaml and validates it

| Path | What |
|---|---|
| kb/<node>.yaml | Hand-authored knowledge base: datapoints, documents, gold facts, experts, canaries |
| kb/golden.yaml | Demo scenarios S1-S8 with expected citations, refusals and forbidden strings |
| data_pack/<node>/source/ | The subsidiary's "source system" documents (private to the node) |
| data_pack/<node>/gated/ | Bodies that need an approval grant (never indexed) |
| data_pack/<node>/index.db | Exposure-capped SQLite FTS5 index: only text allowed to cross |
| data_pack/<node>/policy.yaml, experts.yaml, node.yaml, results_calendar.yaml | Node config for node_core |
| data_pack/<node>/{qms,projects,estate_mis}.db | Mock structured data (Harrisons exposes only v_* aggregate views) |
| data_pack/gold/ | facts.json (computed from the data) and golden.yaml for evals |

Validator checks: canaries never in index/policy/public expert fields; canaries planted in source or gated; at least one
opted-out expert per node; Harrisons small cells exist (suppression test) and pre-coagulation is the largest cause in every season;
the Zensar injection page is present in the index (so the guardrail can be tested).
