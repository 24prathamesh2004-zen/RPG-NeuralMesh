# Sample inputs for the Context graph page (SYNTHETIC)

Ten invented files that the mesh admin uploads through the route of the Add input form, so the Context graph page shows
what it shows after three months of use: four context graphs, five companies and the shared node Others, six file
formats, one removed draft. No
real RPG data.

Run from `app`, with the stack started (`bash scripts/dev_stack.sh start`) and the sample accounts seeded:

    python -m scripts.sample_inputs status      # which sample inputs are loaded, and which other uploads exist
    python -m scripts.sample_inputs load        # upload the sample inputs that have no record yet    (make samples-load)
    python -m scripts.sample_inputs remove      # take them out again, after the question "Type yes"  (make samples-remove)

The commands are refused outside `APP_ENV=development`. `load` signs in as `presenter@neuralmesh.local`, the one mesh
admin of the sample accounts. A load takes about 5 seconds and a removal about 4 seconds.

## The ten inputs

| Id | File in `files/` | Format | Company and catalogue item | Kind | Context graph | Upload date in the list |
|---|---|---|---|---|---|---|
| B1 | integration_review_first_100_days.pdf | PDF | KEC International, L-02 | Post-mortem | Overseas acquisition integration | 29 Jul 2026 |
| B2 | systems_cutover_runbook.md | Markdown | Zensar, C-05 | Playbook | Overseas acquisition integration | 11 Aug 2026 |
| A4 | plant3_warehouse_storage_audit_draft.txt | Text | CEAT, E-03 | Report | Natural rubber storage and ageing | 14 Aug 2026, removed 19 Aug 2026 |
| A1 | plant3_warehouse_storage_audit_apr_jun_2026.pdf | PDF | CEAT, E-03 | Report | Natural rubber storage and ageing | 19 Aug 2026 |
| A2 | natural_rubber_grades_material_specification_rev4.docx | Word | CEAT, E-01 (never leaves CEAT) | Standard | Natural rubber storage and ageing | 2 Sep 2026 |
| B3 | integration_forum_minutes_2026_09.docx | Word | Others (shared), G-01 | Note | Overseas acquisition integration | 17 Sep 2026 |
| A3 | latex_spoilage_monsoon_weeks_2026.csv | CSV | Harrisons Malayalam, O-05 | Aggregate | Natural rubber storage and ageing | 24 Sep 2026 |
| C1 | ai_code_review_pilot_results.json | JSON | Zensar, R-02 | Report | AI-assisted delivery pilots | 8 Oct 2026 |
| C2 | responsible_ai_use_group_guidance.txt | Text | Others (shared), G-01 | Policy | AI-assisted delivery pilots | 15 Oct 2026 |
| D1 | failed_joint_teardown_findings.pdf | PDF | Raychem RPG, O-02 | RCA | 33 kV cable joint failures | 4 Nov 2026 |

`manifest.json` is the list the loader reads: file, company, catalogue item, kind, title, tags, context graph, upload
date, and the concept links each file is expected to get (`expect_concepts`). `load` prints a line when the links of an
upload differ from that list.

After a load the mesh admin sees these four context graphs beside any graph a person added:

| Context graph | Inputs | Removed | Companies |
|---|---|---|---|
| Overseas acquisition integration | 3 | 0 | KEC International, Zensar, Others |
| Natural rubber storage and ageing | 3 | 1 | CEAT, Harrisons Malayalam |
| AI-assisted delivery pilots | 2 | 0 | Zensar, Others |
| 33 kV cable joint failures | 1 | 0 | Raychem RPG |

A company account sees the inputs of its own company and the two shared ones. Of the sample inputs, `kec.expert` sees
3 in 2 graphs, `ceat.expert` sees 5 in 3 graphs (one of the 5 is the removed draft), and `harrisons.expert` sees 3 in
3 graphs. The CEAT specification A2 sits under a
never-leave item, so no other company sees it, and only its title is searched.

## How the load works

- Every file goes through `POST /api/v1/mesh/uploads`, in the order of the upload dates. The text reading, the concept
  links, the pack rebuild and the graph refresh are the ones of the application.
- The first input of a graph opens it by name. Each later input joins it by its id, the way "Add input to this graph" does.
- Two values are written into the upload record after the upload, because no route sets them: the upload date, and
  the mark `sample_input` with the file name. The mark is how the loader knows its own records.
- The draft A4 is uploaded and then removed through `DELETE /api/v1/mesh/uploads/{id}`, so the list shows one removed input.
- `remove` first lists the inputs that go and the uploads that stay, and waits for the word "yes". It touches only
  records with the mark. An input a person added stays. `--yes` skips the question.
- `remove` takes each input out through the application and then deletes its record file, so a later `load` starts
  from U001 again.

## Other folders

- `spare/` holds two files that are not loaded. They are for adding an input by hand: a check sheet for the graph
  "33 kV cable joint failures" (Raychem RPG, item E-01, kind SOP) and a review that opens a fifth graph
  (RPG Life Sciences, item F-01, kind Report).
- `source/` holds the HTML pages and the style sheet from which the three PDF files were printed.

## While the sample inputs are loaded

- Git shows modified files in `data_pack`: `index.db` of CEAT, Harrisons Malayalam, KEC International, Raychem RPG and
  Zensar, and six `pack.json` files. After `remove` the six pack files have the same bytes as before the load. The
  `index.db` files hold the same rows as before, but not the same bytes, so git still lists them.
- The tests do not depend on the loaded inputs: `tests/conftest.py` takes every upload out of its copy of the data pack.
- The two checks with a pass count stay the same: `make live-check` 37 of 37 and `make eval-golden` 15 of 15.
- The two search measurements change, because an uploaded document counts for its catalogue item and takes places in
  the first ten results. Measured on 2026-11-10 (both runs with the one input a person added on 2026-11-09):

| Measurement | Without the sample inputs | With the sample inputs |
|---|---|---|
| `make eval-recall`, keyword search alone, questions with every required item in the first ten | 12 of 28 | 14 of 28 |
| `make eval-recall`, hybrid search | 22 of 28 | 26 of 28 |
| `python -m evaluations.labelled_questions`, keyword search, recall at 10 and nDCG at 10 over 162 questions | 0.94 and 0.85 | 0.93 and 0.83 |
| `python -m evaluations.labelled_questions`, hybrid search | 1.00 and 0.90 | 0.99 and 0.89 |

  Run `remove` before a search measurement that is to be compared with an earlier one.
- `make packs` deletes the whole `data_pack` folder and builds it again, which also deletes every upload record. Run
  `load` again after it. An input a person added is lost by `make packs`.
