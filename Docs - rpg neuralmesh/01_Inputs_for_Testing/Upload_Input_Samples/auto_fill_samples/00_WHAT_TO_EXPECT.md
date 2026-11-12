# Auto-fill samples: what the Add input form should fill in

All files are synthetic. On Context graph, Add input, choose a file at the top of the form. The form reads it without keeping it and fills Title, Tags and the context graph. Every field can still be changed, and a field you typed in is not replaced. Company and Catalogue item stay your choice, because they decide what may leave the company.

The values below were read on the development stack with the sample set loaded. A main concept is one the file names by its full name, or by an other name of at least two words. A graph is suggested for appending when it shares at least 2 of the file's main concepts, otherwise a new graph named after the title. Tags are the main concepts. A concept found only through a one-word other name, such as "checklist" or "claims", is still linked to the document but makes no tag and does not choose the graph.

| File | Title | Kind | Context graph | Tags (the main concepts the file names) |
|---|---|---|---|---|
| 01_bale_storage_humidity_check.md | Bale storage humidity check, Plant 3 | Report | Append: Natural rubber storage and ageing, 5 shared main concepts | raw-material-storage, material-ageing, lot-acceptance, contamination-and-moisture-control, time-to-use-limit |
| 02_cable_joint_moisture_review.txt | Moisture entry in 33 kV cable joints, field review October 2026 | Report | Append: 33 kV cable joint failures, 4 shared main concepts | cable-accessory-failure-analysis, root-cause-analysis, cable-joint-installation, pre-energising-tests, installation-quality-records |
| 03_ai_pair_programming_trial.docx | AI pair programming trial in two delivery teams | Report | Append: AI-assisted delivery pilots, 2 shared main concepts | ai-assisted-delivery, responsible-ai-use |
| 04_solar_inverter_maintenance_plan.md | Solar inverter maintenance plan, rooftop sites | Report | New: Solar inverter maintenance plan, rooftop sites, because no graph shares 2 of its main concepts | none, it names no concept of the vocabulary |
| 05_supplier_lot_rejections_q3_2026.csv | Supplier lot rejections Q3 2026 | Aggregate figures | Append: Natural rubber storage and ageing, 3 shared main concepts | incoming-quality-control, lot-acceptance, time-to-use-limit |
| 06_overseas_unit_month4_status.json | Overseas unit integration, month 4 status | Report | Append: Overseas acquisition integration, 3 shared main concepts | acquisition-integration, integration-checklist, process-ownership-before-system-cut-over |

## What to check

- The line under File says what was read, for example "Read from the file and confirmed by the model: kind Report, 5 concepts. It fits the context graph "Natural rubber storage and ageing", which also covers Contamination and moisture control, Lot acceptance, Material ageing and 2 more. Every field below can be changed". The concepts named are the ones the file and the graph share.
- Type your own title, then choose another file: your title stays.
- Open the form with "Add input to this graph" on Uploaded inputs, then choose a file about another topic: the graph you came from stays chosen.
- Output template needs no change: the JSON of the graph is downloaded after Add or Append.
- Nothing is kept until you click Add to the graph or Append to the graph.
