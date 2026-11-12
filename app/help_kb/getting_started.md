# Getting started with NeuralMesh

## Quick overview of NeuralMesh: what it is and how it helps you

NeuralMesh lets a person in one RPG company ask a question and get an answer from what the other RPG companies have written down: lessons learned, procedures, failure analyses, playbooks and test results. Each company keeps its documents on its own node, a server it runs, and the node decides what may leave the company. The answer cites the documents it comes from, so you can see where every statement stands. NeuralMesh also helps you find people in other companies who have done the work before.

## Where to start as a new user

A first visit usually follows the menu in this order:

1. **Dashboard:** check that the company nodes are online and see recent activity.
2. **Ask NeuralMesh:** ask your question in your own words and choose a purpose.
3. **Expert Finder:** find people who have solved the same problem.
4. **Governance:** for data owners, approve or deny requests for their company's information.
5. **Mesh Nodes** and **Applications:** see which companies and applications are connected and what each shares.

Use **Scope** in the top bar to choose which companies your questions go to. The help chat (this chat) answers questions about using the app at any time.

## How to ask a question across RPG companies

1. Open **Ask NeuralMesh**.
2. Type the question in your own words, for example "What went wrong in the first 100 days of our overseas acquisitions?"
3. Choose a purpose: problem solving, compliance, bid support, learning or career mobility. Each company decides which purposes may see which information.
4. Leave the companies to NeuralMesh, or pick them yourself. NeuralMesh chooses them from the topics of the question.
5. Read the answer. Each statement carries the number of its evidence card. A sentence the evidence does not support starts with "Not in the evidence:". Items a company did not release are listed with a plain reason.

## How to find an expert in another company

1. Open **Expert Finder** and describe the problem or skill, for example "supplier quality" or "overseas integration".
2. The list shows people who opted in, with their role, skills, company and the documents that show their work. Names are not shown.
3. Press **Request intro**. The owning company reviews the request. When it approves, the name is shown to you only, for 24 hours.

## Why some information is withheld

Each company decides what leaves its node, item by item. An item can be withheld because:

- it is restricted and shared as a title only (for example formulations, bid prices, pre-results finance figures or legal files),
- your purpose is not one the company allows for that information,
- it is in a blackout window, such as the weeks before a listed company's results,
- it needs the owner's approval first ("Owner approval is required"),
- the company's node is not available at the moment.

The withheld list shows the reason for each item. Withheld is the company's decision and not an error.

## How to share a document with other companies

Open **Context graph**, choose **Upload input** and upload the file (.txt, .md, .csv, .json, .pdf or .docx, up to 20 MB) under your company and the right catalogue item. The catalogue item sets how far the document is shared: title only, approved summary or passages. Choose **Others** as the company only for material that belongs to no one company and may be read by every connected company. The document stays on your company's node and is linked to the topics named in it.

## How to upload many files at once

A mesh admin opens **Context graph**, chooses **Upload input** and chooses several files, a .zip of a folder, or a folder with **Choose a folder**. Each subfolder becomes one context graph named after it. The form lists every file with its graph, title and kind, and the files that cannot be kept with the reason, before anything is kept. **Add to the graph** then keeps the files listed as "will be added". The Company and the Catalogue item of the form apply to every file. A file inputs.csv at the top of the folder may give a file its topic, title, company, item and whether it is real data. At most 100 files and 200 MB are taken at once, and each file follows the rules of a single upload.

## How to add your own graph as JSON

Open **Context graph** and choose **Upload input**. Choose a .json file with nodes and edges, or press **Paste a graph JSON** and paste it, then press **Ingest**. Ingest checks the JSON and keeps nothing yet: it lists each place to fix, or closes the box and fills the company and the context graph from the JSON. Then press **Add to the graph** for a new graph, or **Append to the graph** to replace the graph chosen. A mesh admin may also choose a document first and add a JSON to it: Add or Append then keeps the document and the JSON as the drawing of its graph. Anyone who is not a mesh admin gives a JSON only. The JSON names the graph ("graph"), the company that owns the data ("company"), the nodes (each with "type" and "name") and the edges (each with "type", "source" and "target"). **Download sample** gives a small invented example in the format. Missing ids are made from the type and the name. A missing sensitivity is Restricted, a missing sharing keeps the graph to your company and mesh admins, and a missing "synthetic" means the data is treated as real, so no cloud model reads it. Only a mesh admin marks a graph as invented with "synthetic": true. A graph of **Others** is read by every company, so its JSON says "sharing": "group" and a sensitivity of Internal or Public. When a node type, an edge end or another needed field is missing, nothing is kept and each place to fix is listed, counting from 0. The answer gives the graph id, and the graph is queried by that id with POST /api/v1/context-graphs/<id>/query and a signed-in person's token. An application's service token reads only the graphs shared with the group. The JSON file of a graph made from documents on **Upload input** carries that graph's "graph_id". A mesh admin may change the file, ingest it on **Upload input** and press **Append to the graph** with that graph chosen: it corrects that graph, shown under it as "Corrected with JSON", and a later file replaces the correction. The file is taken when it names one company. An ingested graph is kept by the central service as written, not at your company's node.

## Is my company's data safe when I use NeuralMesh

- Uploaded documents stay on their own company's node. The centre keeps only their titles, topics, links and counts, and the Dashboard shows that no source record was copied to the centre.
- A graph ingested as JSON on **Upload input** is the exception: the central service keeps it as written and shows it only as its sharing rule allows. The Dashboard shows how many such graphs it keeps.
- Your company's node applies your company's rules to every question, including questions from other companies.
- Restricted information never leaves the node, only its title.
- Every decision of a node is recorded in its audit log with the rule that decided it, without the content.
- People appear in Expert Finder only when they opted in, and their names only after an approved introduction.
