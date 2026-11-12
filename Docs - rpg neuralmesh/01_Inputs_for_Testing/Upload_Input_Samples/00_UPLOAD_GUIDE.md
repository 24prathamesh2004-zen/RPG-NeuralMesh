# Upload guide for the 10 sample inputs

All files are synthetic. Upload each one on Context graph, Add input, as the presenter (mesh admin), with the settings below.

- **Add** means: choose "New context graph" in "Context graph", type the name in "Name of the new graph" and click **Add to the graph**. The form does this itself for a file that fits no graph, with the name taken from the title. Type the name in the table instead to match this guide.
- **Append** means: choose the graph in "Context graph" and click **Append to the graph**. The form chooses it itself when the file shares at least 2 concepts with it. Upload the "Add" files first, because a later file appends to a graph an earlier file opened.
- There is no Kind field. The kind is read from the file. The last but one column says the kind it should get on the development stack.
- "Output template" shows the one standard structure of the JSON file that every context graph gives. "View" opens it read-only and "Download" saves it. After Add or Append the browser downloads the context graph as JSON in this structure. A value a graph does not have is written as null.

| File | Company | Catalogue item | Context graph | Kind it should get | Concepts it should link to |
|---|---|---|---|---|---|
| 01_ceat_mixer_gearbox_breakdown_rca.md | CEAT | O-01 Maintenance and breakdown RCAs | Add: Plant breakdown patterns | Root cause analysis | breakdown-rca, root-cause-analysis, recurring-pattern |
| 02_kec_site_delay_log_jul_sep_2026.csv | KEC International | O-06 Site progress and delay notes | Add: Project delays across sites | Aggregate figures | project-delay-pattern, overseas-mobilisation-terms, monsoon-operations |
| 03_kec_tower_erection_near_miss_summary_q3_2026.txt | KEC International | O-02 HSE incidents (anonymised) | Add: Safety near misses | Report | near-miss-pattern, recurring-pattern, root-cause-analysis, monsoon-operations |
| 04_harrisons_monsoon_collection_checklist_2026.docx | Harrisons Malayalam | F-01 Estate SOPs | Append: Natural rubber storage and ageing | Playbook | monsoon-operations, anticoagulant-preservation, latex-pre-coagulation, latex-collection-and-transport |
| 05_ceat_supplier_quality_scorecard_q3_2026.json | CEAT | E-02 Test and field-failure reports and RCAs | Append: Natural rubber storage and ageing | Report | supplier-quality, supplier-feedback-loop, lot-quality-trending, lot-acceptance, incoming-quality-control, contamination-control |
| 06_raychem_lessons_from_33kv_joint_failures_2026.pdf | Raychem RPG | L-01 Lessons from field failures | Append: 33 kV cable joint failures | Post-mortem | cable-accessory-failure-analysis, cable-joint-installation, pre-energising-tests, installation-quality-records, field-service-routine |
| 07_zensar_knowledge_transfer_handover_playbook.md | Zensar | C-05 Delivery and integration playbooks | Add: Handover and onboarding | Playbook | knowledge-transfer, employee-onboarding, integration-checklist, process-ownership-before-cut-over |
| 08_rpgls_out_of_specification_investigation_summary.pdf | RPG Life Sciences | E-01 Quality control and validation procedures | Add: Quality investigations | Root cause analysis | out-of-specification-handling, deviation-and-capa, cleaning-validation |
| 09_asvata_carbon_inventory_method_note.docx | Asvata | R-01 Carbon accounting and data analysis methods | Add: Carbon accounting methods | Note | carbon-inventory-boundary, emission-factor-selection, data-quality-check |
| 10_ceat_tread_compound_change_request_RESTRICTED.txt | CEAT | E-01 Compound formulations and material specs | Add: Restricted upload test | Report | compound-formulation |

## Output template

Every context graph gives its JSON file in one standard structure. Only the values differ from graph to graph. The structure is the file `json_templates/structured_json.json`, the same one "View" shows on the form.

| Part of the file | What it holds |
|---|---|
| graph, companies | The name of the context graph and the companies of its inputs |
| documents | Each document: id, title, company, kind, catalogue item, sharing rule, upload date and concepts |
| nodes | Every node of the graph: id, type, name and company |
| edges | Every edge: id, type, the ids of its two ends (source, target), their names (from, to) and status |

- A value a graph does not have is written as null, and an empty list as [ ]. No key is ever left out.
- An edge whose end is not among the nodes brings that end in as a node of type "Unknown", so the file is always a whole graph.
- The output holds only what you may see.

The files `evidence_register.json` and `concepts_and_sources.json` in `json_templates/` are examples of a changed template. Changing the template is switched off, so the form does not take them.

The line templates in `output_templates/` are from an earlier form and are not used by it any more.

## What to check

- **Files 01 to 09:** each lands in the graph shown, and "What these inputs are linked to" lists the concepts in the last column.
- **Files 04, 05 and 06** append to graphs that already exist, so the input count of those graphs should rise by one.
- **The kind:** the note under the buttons ends with "Kind …, detected by the model" or "detected by word rules", and the input row on Uploaded inputs shows that kind.
- **The output:** after each upload the browser downloads the context graph as JSON in the chosen template. "Preview" shows it first when an existing graph is chosen.
- **Over-broad aliases:** a simple phrase match also finds a few extra concepts. Expect these and decide whether to keep them:
  - File 02 and file 07 match local labour, contract and payment terms, through "labour" and "payment cycle".
  - File 04 matches integration checklist, through "checklist".
  - File 07 matches client service desk.
  - File 08 matches materials handling, through "handling", and recurring pattern.
  - File 10 matches regulatory change control, through "change request".
- **File 10, the policy test:** E-01 never leaves CEAT. The upload is kept at the CEAT node, and other companies see at most its title, named as withheld. The marker CANARY-UPLOAD-TEST-4417 must not appear anywhere outside the CEAT node: not in a search result, an answer, a graph download, a log or the search on Uploaded inputs.
