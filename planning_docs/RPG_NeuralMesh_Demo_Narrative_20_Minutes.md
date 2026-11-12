# RPG NeuralMesh: 20-Minute Demo Narrative and Expected Questions

## The 20 Minutes at a Glance

The demo follows the left menu from top to bottom. The numbers quoted are the ones the screens showed on 11 November 2026. Read the number from the screen on the day.

| Time | Part | Screen | The one point to land |
|---|---|---|---|
| 0:00 to 2:00 | The problem | Sign-in page, no clicks | Each RPG company knows things the others need, and nobody can find them |
| 2:00 to 3:30 | Why NeuralMesh | Sign-in page, then sign in | Sharing fails when a company loses control of its documents, so the documents stay where they are |
| 3:30 to 5:00 | What NeuralMesh provides | Dashboard | 8 of 8 nodes online, 0 source records copied to the centre |
| 5:00 to 8:30 | A question across companies | Ask NeuralMesh | Every sentence of the answer points at a numbered evidence card |
| 8:30 to 10:00 | A question the company refuses | Ask NeuralMesh | CEAT shares the title of a formulation record and nothing more |
| 10:00 to 11:30 | Finding a person | Expert Finder | Role, skills and evidence first, the name only after approval |
| 11:30 to 13:00 | The companies and the map | Mesh Nodes | One node per company, and a map of names and links at the centre |
| 13:00 to 14:30 | The owner's controls | Governance | Approve, deny, and a log of every decision |
| 14:30 to 17:00 | Adding knowledge | Context graph | Upload a file, see it linked to group topics, download the graph |
| 17:00 to 18:15 | Applications on the mesh | Applications, Domains | SkillForge and Snap and Score read the same map |
| 18:15 to 19:00 | Help inside the app | Help chat button | A new user asks where to start and gets steps |
| 19:00 to 20:00 | Where it stands and what is next | Dashboard | What runs, what is synthetic, what the companies need to bring |

## Before the Demo

- Start the stack from `app` with `scripts/dev_stack.sh start`, then run `scripts/dev_stack.sh status`. Eight nodes, the API, the gateway and the UI should be up.
- The stack starts with a stand-in model by default. The stand-in copies the first line of each evidence item, so the answer on Ask NeuralMesh reads as a list of quoted lines. For an answer written by Claude Sonnet 5.5, start the stack with `NEURALMESH_MODEL_POLICY=config/model_policy.json` set and the Anthropic key in the environment. The Admin page names the model in use under "Answer model".
- Sign in at `http://127.0.0.1:5173` as the presenter with the one-click account on the sign-in page. The accounts are listed in `app/scripts/DEMO_ACCOUNTS.md`.
- Keep "All connected companies" in **Scope** in the top bar.
- Ask the two demo questions once before the audience arrives.
- Keep `~/Projects/RPG-NeuralMesh/Docs - rpg neuralmesh/01_Inputs_for_Testing/Upload_Input_Samples/07_zensar_knowledge_transfer_handover_playbook.md` ready for the upload.
- Open the help chat and press the bin icon, so no old messages show.
- The footer of the menu reads "Synthetic data pilot". Say once, early, that all content is synthetic.

## The Narrative

### 0:00 to 2:00. The problem

Stay on the sign-in page. Talk to the room.

- "RPG is many companies: tyres, power infrastructure, IT services, plantations, pharma, cable accessories, sustainability services. Each one has solved problems the others still have."
- "Take one example. A Harrisons Malayalam estate manager loses latex to spoilage before it reaches the factory. CEAT, which buys that rubber, already tracks quality per supplier lot at receipt and has written down what works. The estate manager does not know that document exists."
- "The same happens with people. Leadership asks who in the group has run an overseas integration. The answer is an email round that takes days, and names get passed around without anyone's consent."
- "And it happens with applications. SkillForge, Snap and Score and the next application each build their own knowledge base and their own vocabulary. That gives three copies of the same facts, and they drift apart."
- "So the lesson gets learned twice, the decision waits, and knowledge the group already has is not used."

### 2:00 to 3:30. Why NeuralMesh

- "The obvious fix is one big shared store. Put every company's documents in one place and search it."
- "That fails because a company that hands over a document loses control of it. It gets copied, forwarded and never retired. CEAT will not put tyre compound formulations in a group store, and a listed company cannot share finance figures before its results. So companies stop sharing."
- "NeuralMesh turns it around. The documents stay inside each company, on a server that company runs. We call it a Mesh Node. The question travels to the node, and the node decides what may leave, for this person and this purpose."
- "The centre holds a map only: topics, skills, roles, document titles and who owns each. It holds no document text."

Sign in as the presenter.

### 3:30 to 5:00. What NeuralMesh provides (Dashboard)

The page opens on **Dashboard**, titled "Group knowledge, connected".

| On the screen | What it means |
|---|---|
| "8/8 Independent nodes online" | Each company's server answered a health check just now |
| "0 Source records copied to the centre" | The centre holds titles, topics and links. No document text sits there |
| "7 Companies in your scope" | The seven companies your questions can reach. The eighth node, Others, holds shared inputs and is not counted as a company |
| "4 Pending approvals" | Requests that wait for a data owner |
| "Pilot companies" table | Each node with its level. "L2 · Summaries and passages" means the company releases summaries and text passages. "L1 · Summaries only" means summaries only |
| "Node activity" and "Search decisions by node" | The latest allow and block decisions, counted from each node's own audit log. The question text is never shown |
| "Decision outcomes" | 75 search decisions recorded: 69 allowed, 5 blocked |
| "Potential monthly value" | Marked "Illustrative only". It is a scenario estimate from the assumptions printed under it, and no saving was measured. Skip it, or say exactly that |

Say:

- "This is the group in one view. CEAT, KEC International, Zensar, Harrisons Malayalam, Raychem RPG, RPG Life Sciences and Asvata each run a node."
- "NeuralMesh gives four things. One place to ask a question across the companies, with sources. A way to find people who have done the work, without exposing names. Control for each company over every item it shares. And one context service that applications read, so they stop building their own copies."
- "All content you will see is synthetic. It was written for this build."

### 5:00 to 8:30. A question across companies (Ask NeuralMesh)

Open **Ask NeuralMesh**. The question box already holds the example question.

1. Read the question aloud: "What rubber-compound learnings from CEAT could reduce Harrisons Malayalam's latex spoilage?"
2. Point at **Purpose** (Problem solving, Compliance, Bid support, Learning, Career mobility). "Each company decides which purposes may see which item."
3. Leave **Choose nodes myself** off. Press **Ask NeuralMesh**.

Walk the result from top to bottom:

| On the screen | What it means |
|---|---|
| Green badge "All routed nodes responded" | Every node the question went to answered |
| "Routed by the mesh graph", with "CEAT, Harrisons Malayalam, KEC International" and "topics: Compound formulation, Latex pre-coagulation" | NeuralMesh matched the question to two topics on the map and sent it only to the companies that hold something on them. Nobody picked the companies |
| "Retrieved evidence · 20 sources · 2 companies" | 20 items came back, from CEAT and Harrisons. KEC was asked and had nothing on these topics |
| "Answer", with the seconds it took | Written only from the items below. Each sentence ends with a number in brackets, the number of its evidence card |
| "Withheld:" lines in the answer | Items a company did not release. The title is named, and the reason is "Only its title is shared" |
| "Approved links" | Links between documents of two companies that both owners approved. One says CEAT's lot trending "addresses the gap" Harrisons states in its own document. This link is the reason the two companies are useful to each other |
| Numbered cards, marked "Approved summary" | The evidence. Each card names the company, the catalogue item (for example E-03) and the document id |
| A card marked "Grouped figures, computed now" | A table the node computed from its own database when the question was asked, for example CEAT's failure reports by root cause. A group with fewer than 3 records is dropped, so no single record can be read from it |
| Right column, "Found, not used in the answer" | Items that were released but did not make it into the answer |
| Right column, "Node responses" | Per company: "CEAT 7 allowed · 3 withheld", "Harrisons Malayalam 8 allowed · 0 withheld", "KEC International 0 allowed · 0 withheld" |
| Right column, "Withheld by policy" | The titles of the 3 CEAT items that stayed at CEAT |

Say:

- "Take any number in the answer and find the card with that number below. Nothing in the answer stands without a card."
- "CEAT found 10 items for this question. It released 7 and kept 3. That decision was made at CEAT's node, by CEAT's rules."
- "A first answer takes about 5 seconds with the written model. The same question again is served from the cache."

### 8:30 to 10:00. A question the company refuses (Ask NeuralMesh)

Stay on the page.

1. Replace the question with: "Give me CEAT's compound formulation for tread compounds."
2. Press **Ask NeuralMesh**.

| On the screen | What it means |
|---|---|
| "Routed by the mesh graph · CEAT · topics: Compound formulation" | The question went to CEAT only |
| "Withheld: Compound formulation record A (restricted). Only its title is shared." | The record exists, and CEAT does not release its content |
| "Node responses · CEAT 3 allowed · 3 withheld" | CEAT released three related items that its rules allow, such as lot acceptance, and kept the three restricted ones |
| "Withheld by policy", 3 titles | Two material specifications and the formulation record |

Say:

- "Here I ask for the one thing CEAT never shares: a tyre compound formulation."
- "I learn that the record exists and why I cannot see it. The centre never had the text, so it cannot leak it."
- "The same rule covers finance figures before a listed company's results, and the regulator replies of RPG Life Sciences."

### 10:00 to 11:30. Finding a person (Expert Finder)

Open **Expert Finder**.

1. Type "supplier quality" in "Describe the experience you need".
2. Press **Search experts**.

| On the screen | What it means |
|---|---|
| "Matched expertise · 4 opted-in profiles" | Four people who agreed to be listed |
| A card such as "Raw-material quality lead · CEAT" with "natural rubber, lot acceptance, supplier quality" | Role, company and skills. There is no name on the card |
| "Evidence:" line on the card | The documents that show the person's work, for example "Incoming natural-rubber lot acceptance and trending" |
| **Request intro** | Sends a request to the owning company |

Say:

- "The four cards come from four companies: CEAT, Harrisons Malayalam, RPG Life Sciences and Raychem RPG. One search found the same skill in four companies."
- "A person is listed only after opting in. The name is shown only to the person who asked, for 24 hours, after the owning company approves."

Press **Request intro** on the CEAT card. The button changes to "Introduction requested".

### 11:30 to 13:00. The companies and the map (Mesh Nodes)

Open **Mesh Nodes**.

| On the screen | What it means |
|---|---|
| "8 / 8 nodes responding now" | A live check of every node |
| One card per company, for example "CEAT · L2 · Summaries and passages · 9 Datapoints · 6 Knowledge packs" | A datapoint is one catalogue item with its sharing rule. A knowledge pack is the company's content for one domain, with its own search index |
| "Others · Shared inputs, read by every connected company" | The node for material that belongs to no single company |
| **View capabilities** | The catalogue items of the company and what each releases |
| "Mesh graph", with counts such as "Document 111 · Concept 61 · Skill 44 · Role 17 · Expert 23" | The map at the centre. It holds 111 document titles and the topics, skills and roles they link to. It holds no document text |
| The six lines under the graph marked "ok" or "found" | Checks that run after every reload, for example "Both ends of every live link are live entities" |

Say:

- "Each company publishes a catalogue, and the catalogue says what may leave. The documents stay at the node."
- "The map is how a question finds the right company. A topic such as 'Latex pre-coagulation' is linked to documents at Harrisons and at CEAT."

Double-click the CEAT entry in the graph to open its connections.

### 13:00 to 14:30. The owner's controls (Governance)

Open **Governance**. Point at the line "POC review controls. Decisions below simulate the configured subsidiary owner role for local demo accounts only."

| Tab | What it shows | What it means |
|---|---|---|
| **Approvals** (4) | For example "KEC International · Post-mortem annex - claims and labour (full text) · Asked by Zensar · Decided by the PMO head", with **Deny** and **Approve 24 hours** | A request for passages of a document. The named owner decides, and an approval lasts 24 hours |
| **Approvals**, the request you just made | "CEAT · Expert directory (consent-based) · Introduction to an expert · Decided by the CHRO" | Your Request intro from Expert Finder, waiting for CEAT |
| **Links between companies** (1) | A proposed link between documents of two companies | It is shown to others only after both companies approve it |
| **Application entries** (201) | Entries that Snap and Score proposed for the map | Each one waits for the companies on both of its ends |
| **Decision log** (100) | One row per decision of a node, with the rule that decided it | The record holds no document content and no question text |

Say:

- "This is the data owner's page. Every request names who asked, for what purpose, and who decides."
- "In this build the decisions are made with local demo accounts. Corporate sign-in comes with deployment."

### 14:30 to 17:00. Adding knowledge (Context graph)

Open **Context graph**. It has three tabs: **Uploaded inputs**, **Upload input** and **Ingest data**.

On **Uploaded inputs**:

| On the screen | What it means |
|---|---|
| The list on the left, for example "Natural rubber storage and ageing · 3 inputs · CEAT, Harrisons Malayalam" | A context graph is a named set of uploaded files on one subject. This one holds inputs from two companies |
| "What these inputs are linked to · 1 input · 7 entities · 10 links" | The part of the map this graph made: the document, its catalogue item, its company and the topics found in it |
| "Download this context graph as" | Structured JSON, GraphML, CSV, or a knowledge pack with the documents |
| **Add input to this graph** and **Drop graph** | For mesh admins |

Click "Natural rubber storage and ageing" and say: "Three files, from CEAT and Harrisons, joined by the topics they share."

On **Add input**:

1. Press **Choose File** and pick `07_zensar_knowledge_transfer_handover_playbook.md`. The form fills the title, the tags and the context graph from the file.
2. Set **Company** to Zensar and **Catalogue item** to C-05 Delivery and integration playbooks. The line under the item says how far it is shared.
3. In **Context graph** choose "New context graph" and name it "Handover and onboarding".
4. Press **Add to the graph**.

Say:

- "The form read the file. I did not type a title or choose a kind."
- "The catalogue item carries the sharing rule. I choose the item, and the rule comes with it."
- "The playbook is now linked to group topics such as knowledge transfer and employee onboarding. Those links are how a question from another company reaches this Zensar document."
- "The browser downloaded the graph as a JSON file. Every graph gives the same structure: documents, nodes and edges."
- "The file stays on the Zensar node. Uploading is for mesh admins in this build."

On **Uploaded inputs**, type "onboarding" in the search box and wait a moment. There is no Search button.

- "Matches outside the uploaded inputs are under More in the graph, such as the topic Employee onboarding. An uploaded input is listed once, under its graph. A topic shows its links when I click it, and Ask about this opens the Ask page with the question written."

### 17:00 to 18:15. Applications on the mesh (Applications, Domains)

Open **Applications**.

| On the screen | What it means |
|---|---|
| "SkillForge · Talent domain · 17 roles · 44 skills" | The group's skills and learning application sent its roles and skills to the map |
| "Tools it calls", 10 names such as role_context, skill_context, ask, learning_sources, find_mentors | The requests SkillForge may make. When a learner opens a role, SkillForge asks what that company's documents say about the role's skills |
| "Packs it sends · 8 kept" and "Every pack it sent is loaded" | The latest import from SkillForge |
| "Reads evidence records by reference... Nothing about people." | SkillForge holds no copy of another company's documents |
| "Snap and Score · Inspection domain · 20 assets · 201 proposed entries" | The photo inspection application brought its own vocabulary. Its entries are proposed until the owners approve them |

Say: "Both applications call one contract. An application is registered in one file that says which companies it may speak for, which purposes it may use and what it may read."

Open **Domains**.

- "This is the rulebook of the map. The core layer has 347 entities and 732 links. The inspection layer, which Snap and Score added, has 81 entities and 188 links."
- "Each row is a kind of link with the count of approved and proposed ones. A new application adds a layer here. It does not build a new store."

### 18:15 to 19:00. Help inside the app (help chat)

Press the round button at the bottom right.

1. Click "I am new here. Where do I start?"

Say:

- "This chat answers questions about using NeuralMesh. It answers only from the app's own guides, and lists the guide sections it used under the answer."
- "It is separate from Ask NeuralMesh. Ask NeuralMesh answers from company knowledge through the nodes. The help chat never reads company documents."

### 19:00 to 20:00. Where it stands and what is next

Back on **Dashboard**.

- "What runs today: seven company nodes and the shared node, cited answers across them, expert search with consent, owner approvals and the decision log, uploads into named context graphs, and two applications on one contract."
- "How it was checked: 237 automated tests, 15 scripted scenarios that include five refusal cases, and a set of 162 labelled questions where search finds the right document in the top 10 every time."
- "What is not there yet: real documents, corporate sign-in, a node inside each company's own network, and a node for RPG Ventures."
- "What we need from the companies: an owner for each catalogue, a first set of real documents, and a decision per item on how far it is shared."
- "The question to take away: which two companies start, and with which problem?"

If someone asks how a question is processed, open **Admin**. It shows the steps in order (resolve, route, fanout, scope, expand, build, answer, check), the registry of the eight nodes, the answer model in use and the shared vocabulary with the other names of each topic.

## Expected Questions and Answers

### Data and control

| # | Question | Answer |
|---|---|---|
| 1 | Where do our documents sit? | On your company's own node. The centre keeps titles, topics, links, owners and counts. It keeps no document text. In this build all nodes run on one machine. In deployment each node runs inside its company's network. |
| 2 | Who decides what leaves a company? | The company. Each catalogue item has a rule: title only, approved summary, passages, or a live lookup. The node applies that rule to every question, for the asker's company and purpose. |
| 3 | Can a restricted item leak through the AI answer? | The answer model receives only what the node released, so a restricted text never reaches it. Each restricted file also carries a marker string, and the tests search answers, logs, downloads and the search index for it. A clean test run shows the marker did not leak in the tested cases. It is not proof for every possible question. |
| 4 | Is our data sent to an outside AI model? | In this build, yes, and only synthetic data: the model policy allows the cloud model in development for synthetic content. The policy file names a model for each step and has a strict mode. Which model real data may go to is a decision for deployment, and the policy can point every step at a model hosted inside the group. |
| 5 | Can we take back something we shared? | Yes. A removed document is retired in the map and rebuilt out of the node's search index. The answer cache is keyed by the evidence the nodes release, so a question asked after the removal gets a new answer without that document. |
| 6 | What is recorded about a question? | The node that decided, the asker's company, the purpose, the item, the decision and the rule. The audit record holds no document content and no prompt text. |
| 7 | How is personal data handled in Expert Finder? | A person is listed only after opting in. The card shows role, company, skills and evidence. The name is shown to the requester only, for 24 hours, after the owning company approves the introduction. |

### Answer quality

| # | Question | Answer |
|---|---|---|
| 8 | How do we know the answer is not invented? | The model writes only from the released evidence. Every sentence must cite an evidence card, and a sentence without support is marked "Not in the evidence:". Seven code checks run on each answer before it is shown, and an answer that fails is not shown. |
| 9 | How good is the search? | On 162 labelled questions, the expected document is in the top 10 results for all of them. On 28 questions reworded to avoid the words of the document titles, it is found for 22. Both sets were written by an AI model from synthetic documents, so the figures say how the search behaves on this content, not on real documents. |
| 10 | How fast is it? | Measured on 10 November on one machine: a first answer has a median of 5.3 seconds, and a repeated question 0.2 seconds from the cache. The two model calls take almost all of that time. The nodes together take about 70 milliseconds. |
| 11 | What happens when a company's node is down? | The other companies still answer. The answer names the node that was not reached, so the reader knows the answer is incomplete. |
| 12 | What if someone hides an instruction inside a document? | Sentences that address the model are removed from the text the user receives, and the record is flagged. |

### How it is built

| # | Question | Answer |
|---|---|---|
| 13 | Why not put everything in one search index or one chat assistant? | One index means one copy of every document outside its company, with one access rule set to maintain centrally. Here each company enforces its own rules at its own node, and the centre cannot leak text it does not hold. |
| 14 | What is a Mesh Node technically? | A server per company that speaks the Model Context Protocol, an open standard for giving AI applications access to tools and data. It holds the company's documents, a keyword index, a vector index (Chroma) per knowledge pack and the company's sharing rules. |
| 15 | Is there a graph database? | No. The map is small enough for an embedded store today. A graph database is planned for when the map outgrows it. |
| 16 | How does an application connect? | Through one contract (version 1.1) with 14 tools, over REST or over the MCP gateway. The application is registered in one file that lists its companies, purposes, tools and readable entity types. SkillForge passes its live contract test of 10 calls against the running mesh. |
| 17 | How does a new company join? | It gets a registry entry, a catalogue of items with a sharing rule for each, and a node. Raychem RPG, RPG Life Sciences and Asvata were added this way on 8 November. |

### Rollout

| # | Question | Answer |
|---|---|---|
| 18 | Is the content real? | No. Every document, expert and figure is synthetic and marked so. Real documents need an owner in each company. Raychem's also need the terms with its joint-venture partner. |
| 19 | What is missing before a pilot with real data? | Corporate sign-in, a node running inside each pilot company's network, a model decision for real data, real documents with owners, and uploads by people other than mesh admins with a review by the item's owner. |
| 20 | Who does the work in each company? | A data owner per catalogue, who sets the sharing rules and approves requests, and a reviewer for links between companies. The time this takes per week is not measured yet. |
| 21 | What does it cost to run? | Not measured. The cost drivers are two model calls per new question and one small server per company. A cached answer makes no model call. |
| 22 | Which companies are not connected? | RPG Ventures has no node. A question does not reach a company without a node, and an application that sends data for such a company is refused with the reason. |
| 23 | How is this different from the help chat? | Ask NeuralMesh answers from company knowledge through the nodes, under each company's rules. The help chat answers from the app's own guides and never reads company documents. |
