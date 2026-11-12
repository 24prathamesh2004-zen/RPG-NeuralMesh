# RPG NeuralMesh: Real Data and Use Case Improvement Plan

Goal: move NeuralMesh from the invented knowledge packs it runs on today to the real documents, people and figures of the RPG companies, with controls that stop a record leaving its owning company against that company's rules, and with a real-data path for each of the seven use cases (two of them, contract precedents and materials science, start at metadata only until the legal decisions in section 11 are taken).

## Contents

1. Problem statement (Diagram 1: the path of one real document today)
2. Step 1: Stop the application from treating real data as synthetic (Diagram 2: the model gate after this step)
3. Step 2: Corporate sign-in, roles and per-node tokens (Diagram 3: from sign-in to node)
4. Step 3: Node-side ingestion of real documents (Diagram 4: ingestion inside one node)
5. Step 4: Sensitivity, personal data and insider information gate (Diagram 5: the gate for one document)
6. Step 5: Models allowed for real data (Diagram 6: routing one question by its evidence)
7. Step 6: Approvals, audit and deletion in production (Diagram 7: an approval from request to decision)
8. Step 7: Evaluation on real data (Diagram 8: the weekly evaluation run)
9. Step 8: Use case improvements (Diagram 9: use cases against their real sources)
10. Step 9: Staged rollout by node and data class (Diagram 10: the four stages)
11. Decisions needed from RPG and each company
12. Roadmap (Diagram 11: 26 weeks)
13. Sources
14. Glossary

## 1. Problem statement

NeuralMesh today is a proof of concept on invented data. Its 88 source and gated files hold 9,019 words in total. Of the 84 catalogue documents, 52 have a body of 21 to 95 words, 9 are a placeholder of 4 to 5 words and 23 hold only a summary. They were written by a generator script, `kbgen.py`, which also writes every node's catalogue, policy, expert list and results calendar, and which deletes the whole data folder when it runs. Every model step (answer, re-rank, classify, kind, map) runs on a public cloud model, Claude Sonnet 5.5, and is allowed to because a constant in four places tells the policy that all data is synthetic. Anyone can sign up with any email and pick any company. Approvals work only in development. The central API process writes directly into the node folders. None of this is a defect of the proof of concept. The synthetic flag, the open sign-up, the generator's deletion and the git tracking (Steps 1 and 2) change before the first real file is loaded. The other items change before the stage of Step 9 that needs them.

Where the synthetic data came from: the packs were written with an AI assistant during the build sessions, in the form and tone of real company documents (quality notes, incident records, estate reports, playbooks), because the public web holds no internal documents of these companies, only annual reports, press releases and trade press, and the figures found there were too few and too uncertain to use as data. Every document, expert, figure, date and database row in the packs is therefore invented. They look realistic by design, so that the pipeline, the policy point and the use cases could be built and tested, and none of their numbers may be quoted as a fact about any RPG company. The 162 labelled test questions were also written by the answer model from those documents. This is why the plan treats the move to real data as a separate programme and not as a swap of files.

The seven use cases are UC1 expert finder, UC2 integration lessons (the Camso and SAE Towers acquisitions), UC3 incident and root-cause patterns, UC4 AI delivery playbooks, UC5 contract and claims precedents, UC6 materials-science exchange and UC7 latex spoilage prevention, the flagship question, which joins a CEAT latex-receipt quality document (catalogue item E-03) with a Harrisons spoilage record (catalogue item O-05). Four words are used with one meaning each. A check is an automatic rule that runs on every answer. A test is a set of questions with known right answers. A measure is a number computed from tests or events. A gate is a rule that decides whether a record or a model may be used.

The real data is large, mixed and governed. One real document, the Harrisons Malayalam annual report for the year ended 31 March 2026, is 193 pages and 99,787 words, eleven times the whole synthetic corpus. Under the present chunking rule it becomes 1,611 chunks of up to 600 characters, 90 of them cut at the 600-character limit mid-sentence and 9 of them cut between the two halves of a number (for example "349." and "75"). Real documents also carry duties the synthetic packs never had: personal data under the Digital Personal Data Protection Act, 2023 (DPDP Act), unpublished price sensitive information under the SEBI insider trading regulations for the five listed companies, joint venture rights at Raychem RPG (a 50:50 joint venture with TE Connectivity), and third-party copyright on standards and research papers.

### Pain points and their impact

| Pain point today | Where it is in the code | Impact with real data |
|---|---|---|
| The generator deletes the data folder and is the only writer of catalogue, policy, experts and calendar | `kbgen.py` line 271 `shutil.rmtree(OUT)`, lines 217 to 223 | A rebuild erases every real record. No node can be set up without the generator |
| "All synthetic" is a constant, not a fact read from the data | `services/uploads.py:311`, `services/neuralmesh.py:217` and `:292`, `services/help_chat.py:230`, `shared/config.py:17` default environment development | In the default environment, development, real confidential text goes to a public cloud model with no refusal. Outside development the policy refuses cloud models, but no model is approved for real data |
| Open sign-up with the company chosen from a list, one shared HS256 secret for user and node tokens | `api/routers/auth.py:13`, `api/account_store.py:82`, `api/auth.py:15`, `services/neuralmesh.py:68` | Anyone can claim any company. A leaked secret acts as anyone at every node |
| Approvals only in development and only for `@neuralmesh.local` addresses | `api/routers/mesh.py:244`, `:310`, `:563` | No data owner can approve anything in a real deployment |
| The central API writes uploads into node folders and rebuilds the node's index | `api/routers/mesh.py:358, 474, 501, 537, 572`, `services/uploads.py:13` | A company's node serves what the centre wrote. Nodes on separate networks cannot take a contribution |
| An upload is released at once with its first 400 characters as the shared summary | `services/uploads.py:48` and `:355` | A name, a price or a client in the first 400 characters leaves the company unread |
| Every node policy allows one role, `group_user`, and ignores sensitivity and the caller's company. The caller sends the `as_of` date used for the blackout | `mcp_nodes/policy.py:38`, `:45`, `:72` | A caller can pick a date outside the results blackout. Sensitivity has no effect at the node |
| Chunks of 600 characters with no structure, one English-only embedder cut at 256 word pieces | `knowledge/packgen.py:271`, `knowledge/embedder.py:46` | Tables and numbers split across chunks. A long table row is cut at 256 word pieces. The embedder is an English model and search on Malayalam and Hindi text has never been tested |
| Personal data step is two regular expressions on the typed question and the answer only | `services/context/pii.py:6-7`, `services/context/check.py:80` | Uploaded text is never scanned. The phone pattern flags dates such as "2026-03-15" and lets PAN and GSTIN through |
| Leak check compares against canary strings that exist only in synthetic packs | `services/mesh_runtime.py:68`, `check.py` rule 2 | In any environment but development the leak check compares against nothing |
| Real data under git: 182 files tracked under `data_pack` | `.gitignore:24` and `:26` ignore only `app/.neuralmesh/` and the Chroma `build/` folders | Real documents would be committed and pushed |
| No answer rating, no per-question record, no cost per company | `services/context/llm.py:132` and `:146`, `DashboardPage.tsx:39` and `:54` | The pilot's main exit test (60% of answers rated useful) cannot be measured |

### Examples with real numbers

- Size: the synthetic corpus is 60 KB of text and 127 vector chunks. One annual report (Harrisons Malayalam, 2025-26) is 646,000 characters of text after whitespace is collapsed and makes 1,611 chunks under the present rule. If each of the four annual reports named in Step 9 were that size, they would give about 6,400 chunks, fifty times today's index of 127. The other three reports were not measured.
- Cost: in the central model-call events of 2026-11-06 to 2026-11-10 (691 questions on the synthetic corpus), one question used a median of 3,309 input and 626 output tokens across its Claude steps. At the public list price of Claude Sonnet 5.5 ($2 per million input tokens and $10 per million output tokens, read 2026-11-11) that is $0.013 a question. At the configured step limits (at most 11,100 input and 2,500 output tokens for answer, re-rank and classify together) it is $0.047. Real documents fill more of the evidence budget of 24,000 characters set in the build step (`builder.py:16`), so real questions sit nearer the limit than the median.
- Recall: hybrid search finds every required document for 22 of 28 reworded questions (78.6%). With 28 questions the 95% Wilson score interval (the range the true rate is likely to be in) is 60.5% to 89.8%. The upper end is just under the 90% target of the strategy plan, so this test gives no evidence that the target is met, and 28 questions are too few to say how far below it the true rate is.
- Legal clock: the main duties of the DPDP Rules, 2025 start 18 months after 13 November 2025. The Rules say only "eighteen months after publication", and law-firm sources read that as 12 May 2027 or 13 May 2027, so the plan works to the earlier date, 12 May 2027.
- Model location: Anthropic's own API offers only "us" and "global" inference. Amazon Bedrock offers an India inference profile (Mumbai and Hyderabad) for Claude Sonnet 5, Opus 5 and Haiku 4.5, and global routing only for the 5.5 models (AWS model cards and price list of 2026-11-09). Keeping prompts in India therefore means Sonnet 5 at $2.20 and $11 per million tokens, 10% above the global price. Anthropic's own Bedrock page lists Mumbai as global only and disagrees with the AWS model cards, so the India profile is confirmed in RPG's AWS account before it is relied on.

### Diagram 1: the path of one real document today

```
Company system          Centre (API process)             Node folder            Question
(SharePoint, SAP,  -->  reads the file in memory    -->  pack, index.db,   -->  search, re-rank on
file share)             summary = first 400 chars        Chroma vectors         Claude Sonnet 5.5
     |                        |                              |                      |
  no connector            no owner review              written by the           all_synthetic=True
  (manual upload          no PII scan of the           centre, not the          so the cloud model
  by mesh admin)          uploaded text                node                     is allowed
```

| Case | What happens today | Action in this plan |
|---|---|---|
| A real file is uploaded by a mesh admin | Indexed and released at once, first 400 characters shared | Step 3 (node-side ingest, owner review, quarantine) |
| A real file contains a name, a phone number or a PAN | Not scanned at ingest | Step 4 (personal data gate) |
| A question's evidence holds Confidential or Restricted text | Sent to a public cloud model | Step 1 and Step 5 (model gate from the data, India profile, in-network model) |
| An employee signs in | Any email, any company | Step 2 (corporate sign-in) |
| A data owner must approve a request | Impossible outside development | Step 6 (approval service) |
| A real document is deleted or re-permissioned in its source | Stays searchable | Step 3 (connector record with delete and ACL sync) |
| The pilot asks whether answers are useful | No record exists | Step 7 (rating field, baseline, expert question set) |
| Harrisons latex question (the flagship) runs on real data | Not possible, no real E-03 or O-05 document | Step 8 and Step 9 (owner picks the documents, stage 2) |

## 2. Step 1: Stop the application from treating real data as synthetic

The application decides whether a cloud model may see a question by a flag, `all_synthetic`, that is written as the literal `True` in four places. The same flag feeds the leak check, because canary strings load only in development and only from synthetic packs. The generator that creates every node's catalogue also deletes the data folder when it runs. These three facts mean a real file loaded today is treated exactly like an invented one. This step removes the possibility, before any other work, by making the synthetic status a property stored on each record and computed, never assumed.

Size in every table of this plan is elapsed calendar time for one engineering team working on that row alone.

| Change | Today | After this step | Size |
|---|---|---|---|
| Synthetic status | Literal `True` at `uploads.py:311`, `neuralmesh.py:217` and `:292`, `help_chat.py:230` | Each pack and each upload carries `synthetic: true` or `false` from its source. `all_synthetic` is the AND over every evidence record of the question. A record without the field counts as real | 2 to 5 working days |
| Policy default | `development_cloud_for_synthetic_confidential: true`, environment defaults to development | Default environment is production. The flag is false unless the deployment sets it. In production the public cloud API is refused for any real record. Confidential records may go only to the India inference profile and Restricted records only to the in-network model (Step 5 gives the tiers) | 2 to 5 working days |
| Generator | `kbgen.py` `main()` deletes the data folder and writes policy, experts, calendar and catalogue for every node | `kbgen.py` writes only into a folder named `synthetic/`, refuses to run when a node folder holds any record with `synthetic: false`, and the four YAML files become editable by the node owner through the node (Step 3) | 2 to 5 working days for the guard, 3 to 6 weeks for the editors |
| Git and disk | 182 files tracked under `data_pack`, `.gitignore` covers only `build/` folders | `data_pack/` ignored except the synthetic folder, a commit hook that refuses any file with `synthetic: false`, node data folders encrypted at rest with a key held by the node company | 2 to 5 working days |
| Canaries | Loaded only in development from synthetic packs | Each node owner plants at least three marker strings in real documents of each sensitivity tier. The markers load in every environment and the leak check reads them from the node, not from the synthetic packs | 1 to 2 weeks |

### Diagram 2: the model gate after this step

```
Question evidence collected (records from one or more nodes)
   |
   v
Every record has synthetic: true? --no--> real data present
   |                                       |
  yes                                      v
   |                             Highest sensitivity of the real records?
   v                                 |            |              |
Development                      Public or    Confidential    Restricted
environment?                     Internal                     (never-leave records
   |      |                          |            |           are metadata only,
  yes     no                      India       India profile   no text to any model)
   |      |                    profile or     only (Step 5)      |
cloud    gateway               gateway                      in-network model
allowed  or local              tier                         only (Step 5)
```

Key insight: the gate must read the data, not a setting, because a setting is what let synthetic and real data look the same.

## 3. Step 2: Corporate sign-in, roles and per-node tokens

Today a person types any email address, picks a company from a list and receives a 12-hour token signed with one HS256 secret that every node also uses to verify its own one-hour node tokens. The mesh admin role comes from an environment variable list of emails. Every node policy allows one role, `group_user`. With real data the company in the token decides which documents a person may see, so the company must come from the company's own identity provider and never from a form. Each node must be able to check a token without holding a secret that would let it forge tokens for other nodes.

| Change | Design | Standard used | Size |
|---|---|---|---|
| Sign-in | OpenID Connect (the standard corporate sign-in protocol) with PKCE (Proof Key for Code Exchange, a step that stops a stolen sign-in code from being reused) against each company's identity provider. The company and the directory groups come from the identity token. Sign-up is removed | OpenID Connect, OAuth 2.1 (an IETF draft that the MCP specification follows) | 3 to 6 weeks |
| Roles | Group user, data owner (per catalogue item), node owner, Mesh Council member, group auditor, mesh admin. Each role is a directory group mapped in a file per company, not an email list | Directory groups | Included above |
| Tokens to nodes | The centre exchanges the user's token for a short token per node with the user as subject, the centre as actor and the node as audience. Nodes verify with the issuer's public keys (JWKS). No shared secret | RFC 8693 token exchange, RFC 8707 resource indicators | 1 to 2 weeks |
| Node protocol | Nodes move to MCP 2026-07-28: no session ids, Protected Resource Metadata published, audience checked on every request, no token forwarded | MCP specification 2026-07-28 | 1 to 2 weeks |
| Applications (SkillForge, Snap and Score) | Client credentials per application, the end user asserted in a signed token, never in the request body | OAuth 2.1 client credentials | 1 to 2 weeks |
| Revocation | Token id (`jti`) and a deny list checked at the centre and at the node, 15-minute node tokens | Standard JWT claims | 2 to 5 working days |
| Open views | `GET /governance` returns every node's pending requests and audit lines to any signed-in user today. It returns only the caller's company unless the caller is a group auditor | None | 2 to 5 working days |

Open point for RPG: which identity provider each company runs and whether the seven companies share one tenant (one sign-in directory). If they share one Microsoft Entra tenant, the on-behalf-of flow, which lets the centre call a node as the signed-in user, is enough. With separate tenants, RFC 8693 token exchange or federation is needed, and cross-tenant exchange has not been tested here. The MCP enterprise-managed authorization extension documents Okta and Ping Identity among its supported providers, says its list is not complete, and does not name Entra, so Entra support is checked.

### Diagram 3: from sign-in to node

```
Employee --> company identity provider --> identity token (company, groups)
                                                 |
                                                 v
                                     Centre maps groups to roles
                                                 |
                                                 v
                              Token exchange: subject user, actor centre,
                              audience node X, 15 minutes, jti
                                                 |
                                                 v
                    Node X verifies signature by JWKS, audience, expiry, jti
                                                 |
                                                 v
                    Node policy: role x sensitivity x exposure mode x purpose x company
```

Key insight: the company in a token is the whole access model, so it must be asserted by the company's directory and checked by the node with a public key.

## 4. Step 3: Node-side ingestion of real documents

The proof of concept takes one file per request, read into memory by the central API, parsed with pypdf or python-docx, cut into 600-character chunks, embedded with all-MiniLM-L6-v2 and written into the node folder by the centre. Real documents arrive in thousands from company systems, change, get deleted, carry access lists, and are written in English, Hindi and Malayalam. Ingestion must therefore run inside the node, from a connector that tracks every item by id, through a parser that keeps structure, into a quarantine that the data owner releases.

| Component | Design | Evidence for the choice | Size |
|---|---|---|---|
| Connector record | One record per source item: source system, immutable item id, version or etag, delta token, last-seen time, hash of the access list, parser version, chunk ids, `synthetic: false`. Deleted flag removes text, vectors and graph metadata. A full relisting on HTTP 410 | Microsoft Graph delta returns deleted items by id and expires tokens with 410 Gone (Graph documentation, 2026-06-06) | 3 to 6 weeks |
| First connectors | SharePoint and OneDrive by Graph delta with sensitivity labels read from the item (Step 4). File share by path walk with hashes. SAP only after the SAP basis team names an allowed extraction route, starting with a nightly export of owner-approved views | A SAP security patch (SAP Note 3255746) blocks third-party ODP RFC calls, and timestamp watermarks miss deletions (Azure Data Factory documentation, 2026-09-11) | 3 to 6 weeks each |
| Parser | Docling (MIT licence) for PDF, DOCX, XLSX, PPTX and images. Pages without a text layer go to an OCR queue running Tesseract with English, Hindi, Marathi and Malayalam data. A page whose mean word confidence from Tesseract is below a floor set on a 100-page sample of each company's scans (for example 70 of 100) is flagged for a person | Docling ran 1.27 pages per second without OCR on a MacBook M3 Max at 4 threads and upwards of 30 seconds per page with EasyOCR on CPU (Docling technical report, 2024, laptop figures). The speed of Tesseract and of Docling on node hardware has not been measured and is re-measured before the OCR queue is sized. Docling's own OCR language list for Hindi, Marathi and Malayalam was not found. A 2024 study found Tesseract the only open library of five with Malayalam support (ICON 2024) | 3 to 6 weeks |
| Parsers not used | Marker and Surya, whose model weights are free only for research, personal use and companies under 5 million dollars in funding or revenue | Surya README licence terms | None, a legal question if a need appears |
| Read report | Every ingested file records pages read, pages with no text, pages OCRed, tables found, characters kept. A file whose text is empty or whose pages were dropped is held, not indexed | Today pypdf drops empty pages without notice (`uploads.py:82`, `:123`) | 1 to 2 weeks |
| Chunking | Split on Docling headings, one section per chunk, at most 400 tokens, a heading path and document title prefixed to each chunk, page number stored. A table stays whole or splits by rows with the header repeated. Numbers never split | Chroma's chunking study (vendor research, one embedding model, public data) found the best and the worst chunking method differ by up to 9 percentage points of recall. Anthropic's contextual retrieval (its own data sets) cut top-20 retrieval failures by 35% to 67% (2024-09-19), but it writes a model-generated context for every chunk and is not what this step proposes. The plain heading prefix proposed here has no measured gain yet, so the 100-question test decides. On the Harrisons report the present rule splits 9 numbers and hard-cuts 90 of 1,611 chunks | 1 to 2 weeks |
| Embedder | BGE-M3 (dense and sparse vectors, 8,192 tokens, more than 100 languages) run inside each node, FTS5 kept for keywords. all-MiniLM-L6-v2 is dropped if BGE-M3 finds the required document in the top 10 for at least as many of 100 real-document questions in each language (English, Hindi, Marathi, Malayalam) as multilingual-e5-large does | all-MiniLM-L6-v2 truncates at 256 word pieces. On IndicMSMarco (web passages translated by a model and post-edited by people) BGE-M3 and e5-large tie on Malayalam and Hindi, and BGE-M3 has the higher mean reciprocal rank in 8 of 13 languages (IndicRAGSuite, 2025). No score on company documents exists. The BGE-M3 weights licence has not been read, only the MIT licence of its code, so RPG legal confirms it before any node runs it | 1 to 2 weeks plus the test |
| Access lists | The source's user and group ids are stored on every chunk. The caller's groups are resolved at question time and filtered before ranking. Link-shared and guest-shared files are not searchable until the owner decides | Microsoft's preview SharePoint indexer for Azure AI Search documents that parent-scope permission changes need a manual resync, and Glean (a search vendor) advises storing groups, not flattened users. Both are vendor documentation, and no measured permission-sync delay was found for any product | 1 to 2 weeks |
| Quarantine and owner review | A new or changed document is in state `draft` until the item's data owner approves its summary and exposure mode. Nobody sees a draft. The owner sees the proposed summary (not the first 400 characters but the document's own abstract or Docling's first section) and the near-duplicate matches | PoisonedRAG reached 90% attack success with five injected texts per question (USENIX Security 2025). Today's upload releases at once | 1 to 2 weeks |
| Duplicates and versions | MinHash signatures (a compact fingerprint of a document's word sequences) at ingest. Pairs with an estimated similarity of 0.8 or more, a threshold tuned on 50 pairs of real versions per node, go to the data owner, who marks one superseded (kept, not answered from) | datasketch MinHash LSH finds similar sets but not which is newer | 2 to 5 working days |
| Build and swap | The node builds a new version folder and swaps by one rename. The centre never writes into a node folder. Upload, remove, rebuild, governance snapshot and audit verification become node tools | Architecture design review of 2026-11-10, first risk | 3 to 6 weeks |
| Scale | Streamed reads instead of the whole file in memory under the global lock, a batch queue, no re-validation of all 37 packs per upload (today 1,369 `json.dumps` calls), no refresh of all 8 nodes per upload | `uploads.py:58`, `packgen.py:314-319`, `mesh_runtime.py:91-111` | 1 to 2 weeks |

Languages: all content today is English. The Harrisons estates may write in Malayalam, English or Tamil, and no public source says which. Before Malayalam content is ingested, a 30-question Malayalam and English test is run on a sample of real files, and the tokenizer (`porter unicode61`), the stopword list and the sentence-end rule (`[a-z0-9]+`, `_SENTENCE_END`) are extended for Devanagari and Malayalam script.

### Diagram 4: ingestion inside one node

```
Source (SharePoint / file share / SAP export)
   |  delta by item id, deletes, access list, label
   v
Connector record  -->  Parser (Docling)  -->  no text layer?  --yes-->  OCR queue (Tesseract)
                                                   |                          |
                                                  no                          v
                                                   v                    confidence below floor
                                           Read report (pages,          --> hold for a person
                                           tables, characters)
                                                   |
                                                   v
                              Chunk by headings, prefix title and path, page numbers
                                                   |
                                                   v
                       Personal data and sensitivity gate (Step 4)  --> hold or mask
                                                   |
                                                   v
                       Near-duplicate check  -->  Draft (nobody sees it)
                                                   |
                                        data owner approves summary and mode
                                                   |
                                                   v
                       BGE-M3 and FTS5 index in a new version folder, swap by rename
```

Key insight: a document that the centre cannot write, a draft that nobody sees and a chunk that keeps its heading are the three changes that make real ingestion safe and searchable.

## 5. Step 4: Sensitivity, personal data and insider information gate

Today every sensitivity label is typed by hand into a YAML file by the generator, and personal data is looked for only in the typed question and in the answer, with two regular expressions. Real documents arrive with their own labels, hold names, phone numbers, PAN and GSTIN numbers, and some hold unpublished price sensitive information (UPSI, the information defined in regulation 2(1)(n) of the SEBI Prohibition of Insider Trading Regulations, 2015) of the five listed companies. This step puts one gate in front of every node index that reads the label from the source, scans the text, and withholds the document whenever it is in doubt.

| Rule | Design | Basis |
|---|---|---|
| Sensitivity from the source | The Microsoft 365 sensitivity label is read from each item where the tenant has enabled labels for SharePoint and OneDrive (`extractSensitivityLabels`, permission `Files.Read.All`, not supported for SharePoint Embedded containers). The node owner approves a table from each company label name to Public, Internal, Confidential or Restricted. No label, an unreadable label (Graph returns 423 for some encrypted files) or a connector error means Restricted plus a review task. Nothing is ever defaulted to Public | Microsoft Graph documentation, pages updated 2026-07-24 and 2026-11-04. ISO/IEC 27002:2022 control 5.12 makes the information asset owner (the data owner in this plan) responsible for classification |
| Personal data scan | Presidio with its Indian recognisers (IN_AADHAAR, IN_PAN, IN_PASSPORT, IN_VOTER, IN_VEHICLE_REGISTRATION, IN_GSTIN), the email and phone patterns of today with the phone pattern fixed so that dates and amounts no longer match, and a named-entity model trained on Indian languages for person names. A hit sends the document to the data owner's review queue with the hits highlighted, and the data owner masks or approves | Presidio supported entities list. Its default configuration is English only. A 2026 benchmark that merged ten data sets and 48 kinds of personal data (PIIBench) gave every tool a span-level F1 (a score from 0 to 1 that balances precision and recall) below 0.14, with Presidio the best at 0.1385. It has no Indian-language split and its labels may not match Presidio's, so no recall figure is taken from it, and the recall is measured on each node's own documents |
| Measure before trusting | On each node, 200 of its own documents are hand-labelled for personal data and the scan's recall is measured and reported with its Wilson interval before the node leaves stage 1 (Step 9) | Naamapadam reports an F1 score (0 to 100) above 80 for 7 of the 9 Indian languages it tested, counted over person, location and organisation names together, with no separate person-name score |
| What never leaves | Restricted records, UPSI, personal data beyond the consented expert fields, joint venture and partner intellectual property (TE Connectivity material at Raychem RPG), client-confidential material (Zensar), legally privileged files (Step 8, UC5). These are capped at metadata (title and owner) in every exposure mode | The design plan, section B4, the workshop transcripts, SEBI regulation 3(1) |
| UPSI guard | Each listed company's node holds its trading-window calendar (closed from the end of each quarter until 48 hours after results, with the 2025 exemption for UPSI that does not originate inside that company, confirmed by each compliance officer) and a tag list of UPSI classes from regulation 2(1)(n). A record tagged UPSI is withheld from every other company during the window. Outside the window it is withheld unless the owning company has written a legitimate-purpose entry, a dated line naming who received it and why. That entry holds the names and identifiers regulation 3(5) requires, is written inside the owning company's node, is kept eight years and is not erased on request while that duty runs. The node reads the date from its own server clock in Asia/Kolkata and ignores any date sent by the caller | SEBI regulations 3(5) and 3(6): the structured digital database "shall not be outsourced and shall be maintained internally", kept at least eight years. Today the caller's `as_of` date is used (`mcp_nodes/policy.py:72`) |
| Licensed third-party text | BIS and ISO standards, journal papers and Rubber Board publications are held as metadata records only (number, title, edition, status, link). No clause text and no embeddings until a written licence or permission exists. Each catalogue item gets a `licence_status` field (company-owned, open licence, permission obtained, metadata only) and text is never exposed when the field is empty | Section 11 of the Bureau of Indian Standards Act, 2016 and the ISO help centre ("standards cannot be shared with other users or posted on a company intranet") |
| Audit without personal data | Audit lines keep a keyed hash of the user reference, never a name or email. The key is held by the company. Erasure of a person's trace is proposed by deleting their key, which works only if the key was never leaked and the hash algorithm is unbroken. Counsel confirms this against the DPDP Act before it is relied on. The UPSI sharing entry above is the one record that keeps names | EDPB Guidelines 02/2025 version 2.0 (adopted 7 July 2026), written for blockchains and applied here by analogy: a keyed hash is not linkable once the key is deleted. Whether GDPR applies to an RPG entity is a legal question |

What a passed gate does not show: a clean scan is not proof that a document holds no personal data (the measured recall of the tools is below 100%), and a label from the source is only as right as the person who set it. Both are reasons for the owner review in Step 3 and the labelled-sample measure above.

### Diagram 5: the gate for one document

```
Document arrives from the connector
   |
   v
Label readable? --no--> Restricted + review task
   |
  yes
   v
Personal data hits? --yes--> owner review queue (mask or approve)
   |
  no
   v
UPSI tag or in trading window? --yes--> withheld from other companies, entry in the owning node
   |
  no
   v
Licence status set? --no (third-party text)--> metadata only
   |
  yes
   v
Draft for the data owner (Step 3) --> approved --> indexed at its ceiling (MD, SUM, RAG or LIVE)
```

Key insight: at every branch a doubt means the document is withheld and sent to the data owner, because withholding costs about one day of delay, while a release cannot be undone.

## 6. Step 5: Models allowed for real data

Every step of a question today runs on Claude Sonnet 5.5 through the public API, which offers inference only in "us" or "global" geography. The policy file has three tiers (gateway, local, cloud) but only the cloud tier is checked against sensitivity, and the gateway entry is a placeholder address. For real data the model a question may use must follow from the highest sensitivity of its evidence, as Diagram 2 shows, and the price must be known in advance.

| Evidence class | Model | Where it runs | Dated list price per million tokens (input and output) | Source |
|---|---|---|---|---|
| Public and Internal (real) | Claude Sonnet 5 for the answer, Claude Haiku 4.5 for re-rank and classify | Amazon Bedrock, India inference profile (Mumbai and Hyderabad), `in.anthropic.*` | Sonnet 5 regional $2.20 and $11. Haiku 4.5 regional $1.10 and $5.50 | AWS Price List for ap-south-1, published 2026-11-09, and AWS model cards |
| Confidential (real) | Same as above, under an AWS service control policy (SCP, an account-wide rule that denies named actions) that denies every non-India inference profile for the NeuralMesh account, and a contract term on retention | Same | Same | Same |
| Restricted (real), at the exposure mode its data owner allows | gpt-oss-120b (open-weight model under the Apache 2.0 licence, 117 billion parameters with 5.1 billion active, served by vLLM on one 80 GB GPU) inside the group network. Never-leave records are metadata only and no text of them is sent to any model | One GPU server operated by group IT | No per-token price. Server cost is a decision for RPG | openai/gpt-oss README |
| Synthetic (development only) | Claude Sonnet 5.5 as today | Public API | $2 and $10 (public pricing page, read 2026-11-11) | Anthropic pricing page |

Why Sonnet 5 and Haiku 4.5 and not Sonnet 5.5 and Haiku 5.5: the AWS model cards list only global routing, which can serve a request from outside India, for the 5.5 models in Mumbai. Vertex AI regional endpoints serve Claude Sonnet 4.6 and earlier only. Azure Foundry data zones are US, EU and Asia Pacific, with no India pinning for Claude. The India profile moves to a 5.5 model only when AWS publishes one for it.

Cost per question at the configured step limits (answer 8,000 in and 1,200 out on Sonnet 5 regional, re-rank and classify 3,100 in and 1,300 out on Haiku 4.5 regional): $0.0414. At 600 questions a week, the start of the Dashboard slider, that is $24.82 a week for Public, Internal and Confidential questions. If every token of the measured synthetic median (3,309 input and 626 output) ran on Sonnet 5 regional the cost would be $0.0142, but real evidence is longer, so the limit figure is the budget. Not in these figures: cached answers (no model call), the extra answer call made when the answer check fails (15 of 691 questions between 2026-11-06 and 2026-11-10), the two intake calls that detect an uploaded document's kind and map its fields, questions on Restricted records (in-network model, no per-token price), the GPU server, and conversion to rupees.

Changes in the code: the policy file gets `max_sensitivity` and `data_location` per model entry, every tier is checked against the evidence (today only the cloud tier is), a model missing from the file stops the service at start in every environment, the model call writes company, user hash, model and the dated price into the central event, and the Dashboard shows cost per company from those events. The README line that says a cloud model may be used is aligned with the policy file.

Retention: the Anthropic API documentation says conversation content is not retained by default except for Covered Models, which require 30-day retention, and the privacy centre says inputs and outputs are deleted within 30 days. The AWS contract position on retention and abuse-detection storage for the chosen model is an open question for the AWS account team. The design rule proposed here: the answer model gets no tools and no write access, every evidence record is marked as untrusted data, and code (not the model) chooses nodes, records and citations. Today the only injection defence in the code is one regular expression with two phrases, and twelve published defences were bypassed by adaptive attacks with success above 90% for most (2025), so the rule is containment by design first and a classifier (Llama Prompt Guard 2) only as a flag.

### Diagram 6: routing one question by its evidence

```
Evidence records  -->  highest sensitivity among real records
                             |
          +------------------+------------------+
          |                  |                  |
     Public/Internal     Confidential      Restricted (never-leave:
          |                  |              metadata only, no model)
     Sonnet 5 India     Sonnet 5 India     gpt-oss-120b in-network
     Haiku 4.5 India    + SCP deny list    (never a cloud model)
          |                  |                  |
          +------------------+------------------+
                             |
                   model event: company, user hash, tokens, dated price
```

Key insight: the model is chosen by the data in front of it, and the cheapest option that keeps prompts in India is Sonnet 5, the version before the Sonnet 5.5 used today.

## 7. Step 6: Approvals, audit and deletion in production

Approving an access request, a link between companies or an application entry works today only in development and only for an address ending in `@neuralmesh.local`. The command-line approval tool accepts any text as the approver. The API passes the owner's role text as the approver, so the reviewer's email is never written. There is no route by which a user can ask for an approval-gated document. Audit files are hash chains with no key and no outside anchor, re-read in full on every append (9,448 lines for CEAT), and the justification text is kept in clear with no expiry. Nothing erases a person. With real data four of these gaps are legal duties: erasure, consent withdrawal and one-year logs under the DPDP Act and Rule 6, eight-year sharing entries under the SEBI regulations, and the six-hour incident report and 180-day logs under the directions of CERT-In (the Indian Computer Emergency Response Team). The others are needed for the approvals and the audit to work at all.

| Function | Design | Size |
|---|---|---|
| Request access | A "Request access" button on every withheld card of the Ask page, with a typed reason of 10 to 500 characters and a purpose from the `purposes_allowed` list of the node policy. Stored in the owning node | 1 to 2 weeks |
| Approve | A data owner signed in through Step 2 approves or denies from Governance, in every environment. The owner's hashed user reference, decision, time and reason are written to the node ledger. The time from request to decision is computed and shown, with the 24-hour target | 3 to 6 weeks |
| Notify | Email first, Microsoft Teams later, to the data owner on a new request and to the asker on a decision | 1 to 2 weeks for email, 3 to 6 weeks for Teams |
| Expert introduction | The asker types the reason. The expert is asked and answers yes or no before any name is shown. Consent is dated, with purpose and a withdrawal function | 3 to 6 weeks |
| Audit integrity | Each node ledger is an HMAC chain with a company-held key, constant-time append (last hash kept in memory), a daily anchor of the last hash written to a store outside the node, and a verify tool. Audit lines hold ids and hashes only, no text, no name | 1 to 2 weeks |
| Retention | Node ledgers and access entries one year minimum (DPDP Rule 6, which requires logs kept one year to detect unauthorised access), UPSI sharing entries eight years (SEBI regulation 3(5)), security logs 180 days at least (CERT-In). One India-hosted log store | 1 to 2 weeks |
| Erasure and withdrawal | A person's expert record, consent and keyed audit identity can be erased on request. Removing an upload removes its body from the record (today the body stays, `uploads.py:621`). The graph store gets a delete, not only retire | 3 to 6 weeks |
| Incident runbook | One runbook with two clocks: the CERT-In six-hour report and the DPDP 72-hour report to the Board, plus notice to each affected person. Owner named per company | 2 to 5 working days |
| Per-node stop | A stop setting per node that the node owner or the mesh admin can turn on. The centre stops sending questions to that node within one minute (today the registry is cached for the process lifetime) | 2 to 5 working days |
| Policy version check | A policy version in each node's health reply. The centre refuses to use a node whose policy version it has not loaded | 1 to 2 weeks |

### Diagram 7: an approval from request to decision

```
hour 0        asker presses Request access, types reason
hour 0        owning node stores the request, email to the data owner
hour 0 to 24  owner opens Governance, reads reason, approves or denies
              ledger line: request id, owner hash, decision, time
hour 24       target line: requests older than 24 hours are shown in red on the Dashboard
decision      asker notified, the gated text is served at its ceiling to that asker only
```

Key insight: an approval that cannot be given outside development is not a control, so the owner's signed decision, written to the owning node, is the first governance feature to build.

## 8. Step 7: Evaluation on real data

The evaluation today rests on three sets that share their origin with the thing they test: 162 labelled questions written by the answer model from each document's title and summary (found in the top 10 for all 162), 15 golden scenarios on invented documents (15 of 15), and 30 reworded questions, of which 28 could be scored (22 found). None was written by a subject expert and none runs on a real file. The pilot's exit tests (at least 60% of answers rated useful, median time-to-answer down, zero policy breaches, approvals under 24 hours) have no instrument: no rating field, no baseline, no real markers, no time-to-decision. This step builds the instruments before the first real node leaves stage 1.

| Instrument | Design | Why this size |
|---|---|---|
| Expert question set | For each node, 30 real questions collected from staff in weeks 2 to 6, with the reference answer and the source passage marked by a subject expert (an employee who knows the topic), graded 0 to 3. Growing to 200 per node by the end of stage 2 (week 18) and 385 for the cross-node set by week 23 | With 30 questions a result of 27 right has a 95% Wilson interval of 74.4% to 96.5%, too wide to confirm a 90% target. 200 questions at 189 right give 90.4% to 96.9%. 385 questions give plus or minus 5 points at worst |
| Generated questions | Kept only to extend the set, labelled as generated and reported separately | Chroma's generative benchmarking found, on one production set, a recall at 10 of 0.530 for generated questions against 0.439 for real questions with the same embedding model (text-embedding-3-small), so generated questions overstate recall there. On a multilingual Wikipedia set, generated questions scored lower than real ones for some of the models tested |
| Rating | On every answer, "useful" or "not useful" with one reason (not relevant, wrong company, out of date, too long, missing citation, other). One event per question without the question text, with company, node set, latency, tokens and price | The pilot exit test is that at least 60% of answers are rated useful. This plan requires the lower end of the 95% Wilson interval to reach 60%, which with 200 rated answers needs 134 rated useful (67%, interval 60.2% to 73.1%). With 100 rated answers, 60 rated useful gives 50.2% to 69.1%, so it is not passed |
| Baseline | Before the pilot, 20 staff per company time how long they take today to find the answer to five of the expert questions by their usual means | The exit test "median time-to-answer down" has nothing to compare against |
| Leak markers | At least three marker strings per sensitivity tier planted by each node owner in real documents. The check step reads them in every environment. A weekly run of 50 marker questions written to pull each marker out | The present canaries exist only in synthetic packs. With no marker returned in 100 marker questions the true leak rate is at most 3.7% (upper end of the 95% Wilson interval), with none in 300 marker questions at most 1.3% |
| Failure tags | Every failed question is tagged with one of the seven failure points listed in source 32 (missing content, missed top-ranked document, not in context, not extracted, wrong format, wrong specificity, incomplete) | Gives the owner of each step a count to act on |
| Language test | 30 Malayalam and 30 English questions on Harrisons files before any Malayalam text is indexed | No public score exists for these tools on Indian company documents |
| Speed and availability | A scheduled request (a probe) every minute to the centre and to each node. The report gives the median response time, the p95 (the time that 95 of 100 requests beat) and availability (the share of probes answered). A 50-user load test before stage 3 | The design plan's targets (median answer under 10 seconds, p95 node response under 300 milliseconds, availability 99.5%) have no data today |
| Privacy scan recall | 200 hand-labelled documents per node for the personal data scan (Step 4) | No published recall figure fits Indian company documents (Step 4), so each node measures its own |

What a good score does not show: a pass rate on the expert set is not the live pass rate (staff ask questions the experts did not write), a 100% result on 30 questions still allows a true rate as low as 88.6%, and a clean marker run shows only that those markers did not leak.

### Diagram 8: the weekly evaluation run

```
Monday    expert set (per node, by origin: expert / generated)  -->  recall, grade, failure tags
          marker set (50 questions)                             -->  leaks found, upper bound
          ratings of the week                                   -->  useful share with Wilson interval
          probe log                                             -->  median, p95, availability
          model events                                          -->  cost per company
             |
             v
          one page per node, red where below target, read by the node owner and the Mesh Council
```

Key insight: every target in the design plan is a proportion, so every result is reported with its interval and no result from fewer than 30 questions is called a pass.

## 9. Step 8: Use case improvements

UC1 to UC4, UC7, SkillForge journey A and Snap and Score run today on invented records. UC5 and UC6 have no scenario, no test and no data. UC2, UC3, UC4, UC5 and UC6 each depend on documents or systems that no data owner has yet named. This step names, for each one, what it needs from real data and what has to change in the application.

| Use case | Works today on | Needed for real data | Change in the application |
|---|---|---|---|
| UC1 Expert finder | 30 invented expert profiles in `experts.yaml`, 23 of them with a recorded consent | An HR-sourced directory per company with dated consent per purpose, DPDP notice text, withdrawal | The sign-up opt-in that no node reads is removed. Each node reads one directory feed. The expert answers the introduction. An expert id derived per caller and purpose |
| UC2 Integration lessons (Camso, SAE Towers) | Summaries of KEC L-02 and CEAT items, gated annex L-02a reachable only by seed script | The real integration documents picked by the CEAT and KEC owners, with the annex approval-gated | The Request access button and the approval service (Step 6) |
| UC3 Incident and RCA patterns | 3 mock SQLite files, 712 rows, 5 views that return counts per group, and a group of fewer than 3 source records is dropped | A read-only owner-approved view in each company's quality or ERP system. CEAT is reported to have implemented SAP S/4HANA on AWS (AWS press release, 17 August 2022) and KEC to have agreed to adopt it (trade report, 28 August 2017, rollout status not stated). Neither company has stated it, so each IT lead names the system (section 11) | A connector per view, `min_group` (the smallest number of source records a returned figure may rest on) per datapoint, set to 10 for any figure about people, refusal of a view without a count column, suppression of a complementary small group |
| UC4 AI delivery playbooks | 8 short Zensar documents | Zensar's real playbooks, hundreds of pages each, with client names masked by the owner | Structure-aware chunking (Step 3). Client-confidential rule in the never-leave list |
| UC5 Contract and claims precedents | Nothing (no scenario, no test) | KEC, Raychem and Zensar contract files with legal privilege marked by the owner | A `privileged` flag at the policy point that caps the item at metadata for every other company. Counsel review before the node opens |
| UC6 Materials-science exchange | Nothing | CEAT, KEC and Raychem test reports, MD and SUM only | TE Connectivity terms for Raychem material settled first (Step 9 decision). Raychem stays at metadata until then |
| UC7 Latex spoilage (flagship) | S1 passes on invented E-03 and O-05 | A real CEAT latex-receipt quality document and a real Harrisons spoilage record chosen by their owners, E-01 formulations at metadata only, the Harrisons grouped figures from the estate system | The first real cross-company question. Run only after both nodes pass stage 2 (Step 9) and the owner decision on Harrisons policy is taken |
| SkillForge journey A | 17 roles and 44 skills copied from SkillForge development data | Group HR's role list with skill names joined across companies | None in NeuralMesh, the feed changes |
| SkillForge journeys B and C | Vocabulary served, learning sources by reference | The SkillForge test of 50 hand-labelled CVs, passed when at least 90% of the skills found are correct, learning release records with end date and daily deletion | Renewing service tokens, a learning release record |
| Snap and Score | Live cover from one JSON file per node (none for Raychem), inspections written into the central graph | Cover status from each company's insurance or stock-policy system | Inspection results kept in the owning node, the centre keeps the reference only. A connector per company |
| Dashboard and Admin | Typed 0 for records copied, decision counts from the latest 100 ledger rows, a typed value formula labelled illustrative, guardrails typed enabled | Measured values | Counts from the events of Step 7, cost per company from Step 5, each guardrail reported by the code that enforces it, the value panel fed by ratings and the baseline |

### Diagram 9: use cases against their real sources

```
UC1 ----> HR directory feed (per company) ----> consent, withdrawal
UC2 ----> CEAT and KEC integration files ----> approval gate
UC3 ----> SAP / quality views (read-only) ----> grouped figures, min_group
UC4 ----> Zensar playbooks ----> client names masked, chunk by heading
UC5 ----> contract files ----> privileged flag, counsel review
UC6 ----> materials test reports ----> MD and SUM, TE terms first
UC7 ----> CEAT E-03 + Harrisons O-05 (real) ----> stage 2 of both nodes
SkillForge ----> Group HR roles, SkillForge CV test
Snap and Score ----> insurance / stock-policy systems ----> inspections stay in the node
```

Key insight: five of the seven use cases (UC2, UC4, UC5, UC6, UC7) wait for a data owner to choose a real document, so the first deliverable of the pilot is that list, not code.

## 10. Step 9: Staged rollout by node and data class

Real data enters in four stages. Stage 1 loads one node with published documents that hold no personal data. Each later stage adds one kind of record (confidential documents, then data about people, then the remaining nodes) and opens only when the measures of the stage before are met. The synthetic packs stay in development only and are never loaded into a node that holds a real record.

| Stage | Data allowed | Nodes | Entry condition | Exit condition |
|---|---|---|---|---|
| 1 | Public documents and Internal documents without personal data: each company's own published annual report and investor presentations (CEAT Integrated Annual Report FY26, KEC Annual Report 2025-26, RPG Life Sciences Annual Report 2025-26, Harrisons Malayalam Annual Report 2025-26), tagged publisher, date, source URL | One pilot node (Zensar, the one node the design plan places at maturity level L3, or CEAT) in a new protected environment with its own secrets | Steps 1 and 2 done (week 6), git and encryption in place | Read reports complete for every file, expert set of 30 collected, personal data scan recall measured on 200 labelled documents, markers planted, zero leaks in 100 marker questions |
| 2 | Confidential documents without personal data, the real UC7 pair (CEAT E-03, Harrisons O-05), UC2 integration files, UC4 playbooks with client names masked | CEAT, KEC, Zensar, Harrisons | Stage 1 exit, Steps 3 to 6 done (week 12), India model profile live, owner review running | 200 expert questions per node, grade and recall reported, time-to-decision under 24 hours for 90% of requests (this plan's proposal, the design plan says only "approvals under 24 hours"), zero leaks in 300 marker questions (six weekly runs of 50) |
| 3 | Expert profiles and CV-derived skills, grouped figures from company systems | Same four plus RPG Life Sciences | Data protection impact assessment per company (this plan's own precaution: the DPDP Rules require one only for a company notified as a Significant Data Fiduciary, and whether GDPR Article 35 applies to an RPG entity is a question for group counsel), consent flow live, HR feed agreed, 50-user load test passed | 60% useful with the Wilson lower bound above 60% (at least 134 of 200 ratings), availability record of four weeks |
| 4 | Remaining nodes and classes | Raychem (after TE Connectivity terms), Asvata (company-supplied content only, almost no public documents exist), Others node | Written terms for Raychem, content list for Asvata | Same measures as stage 2 per node |

Harrisons Malayalam needs a decision before stage 2: the company is presented on the websites of both the RPG group (rpggroup.com) and the RP-Sanjiv Goenka group (rpsg.in), and its promoter group holds 54.12% (shareholding pattern of 30 September 2026, read through an aggregator of the exchange filing). Which promoter entity belongs to which group was not established, so RPG must say which group's policy and which data owner decide for Harrisons data. Raychem RPG is a 50:50 joint venture with TE Connectivity. A trade report (tele.net.in, undated) says TE Connectivity acquired Raychem's stake in the telecom business of the venture, and no filing confirming or ruling this out was found, so the Raychem RPG board states what the company still owns before its node is listed.

### Diagram 10: the four stages

```
Stage 1 ------> Stage 2 ------> Stage 3 ------> Stage 4
public,         confidential,   people data,    Raychem, Asvata,
non-personal    UC7 real pair   grouped figures Others
1 node          4 nodes         5 nodes         8 nodes
|               |               |               |
scan recall     200 questions   134 of 200      TE terms,
markers 0/100   markers 0/300   rated useful    Asvata content
```

Key insight: each stage adds one kind of risk (size, confidentiality, people, partners), and the measure that opens the next stage is the one that covers the risk just added.

## 11. Decisions needed from RPG and each company

| Decision | Who | Needed before | Why it cannot be taken here |
|---|---|---|---|
| Identity provider per company and whether one tenant is shared | Group IT | Step 2 | Decides on-behalf-of, token exchange or the MCP enterprise extension |
| Systems of record for documents, quality and ERP at each company, and their owners | Each company IT lead | Step 3 | No public statement exists for any of the seven companies on Microsoft 365 or a document system. SAP at CEAT and KEC is known only from vendor and trade press |
| Legal basis for employee data in the expert directory: section 7(i) employment purpose or consent per company | Counsel per company | Stage 3 | Section 7(i) covers employment purposes and says nothing about showing skills to other group companies |
| Role of the central service: processor under a section 8 contract or fiduciary | Group counsel | Stage 1 | The DPDP Act gives no group-company exemption |
| Whether the UPSI sharing entries may be held by group IT or must sit in each listed company | Compliance officer of each listed company | Stage 2 | Regulation 3(5) keeps the structured digital database internal and not outsourced |
| Which group's policy and which data owner decide for Harrisons Malayalam data | RPG executive sponsor | Stage 2 | The company is presented by both the RPG group and the RP-Sanjiv Goenka group |
| TE Connectivity rights over Raychem catalogues, manuals and test data | Raychem RPG board | Stage 4 | A 50:50 joint venture. No public source for the agreement or for TE's rights over Raychem documents was found |
| Build the centre or host it on Zensar's ZenseAI.AgentMesh product, and who owns the commercial rights | RPG executive sponsor | Roadmap week 4 | AgentMesh launched 17 June 2026 with native MCP support and 80 pre-built agents. NeuralMesh nodes could be MCP servers that AgentMesh agents call |
| Acceptance of Bedrock inference in Mumbai and Hyderabad only, and the retention position | Counsel and the AWS account team | Stage 2 | No stricter India pinning exists for current Claude models on any platform |
| One 80 GB GPU server inside the network, and who operates it | Group IT | Stage 2 | Restricted records need a model that never leaves the network |
| Licences: BIS authorisation or ISO multi-user licence, Rubber Board permission, Datalab or Artifex if a need appears | Procurement and counsel | Stage 2 | Third-party text is metadata only until then |
| Languages written at the Harrisons estates and share that is scanned | Harrisons node owner | Stage 2 | No public source states it |
| Executive sponsor and Mesh Council membership | RPG | Week 1 | Listed as an open question in the design plan (section B8) |

## 12. Roadmap

The order follows the dependencies: nothing real is loaded before Steps 1 and 2 are done (week 6), nothing confidential before Steps 3 to 6 are done (week 12), nobody's personal data before the impact assessment. Sizes are estimates of elapsed calendar time for one engineering team per row. Added up for one team they exceed 26 weeks, so the timeline assumes three teams in parallel from week 3: one on sign-in and tokens (Step 2), one on ingestion (Steps 3 and 4) and one on models and governance (Steps 5 and 6). The SAP connector and the Teams notification start after week 12. These sizes are not commitments.

### Diagram 11: 26 weeks

```
Week  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26
S1   ## ##                                                                     Step 1 synthetic flag, generator guard, git, encryption, markers (weeks 1 to 2)
S2   ## ## ## ## ## ##                                                         Step 2 corporate sign-in, roles, token exchange, MCP 2026-07-28 (weeks 1 to 6)
S3         ## ## ## ## ## ## ## ## ## ##                                       Step 3 SharePoint and file-share connectors, Docling, OCR queue, chunking, BGE-M3, quarantine, node tools (weeks 3 to 12)
S4               ## ## ## ## ## ##                                             Step 4 labels, personal data scan, UPSI guard, licence field (weeks 5 to 10)
S5                        ## ## ## ##                                          Step 5 model tiers, India profile, in-network model, cost events (weeks 8 to 11)
S6         ## ## ## ## ## ## ## ## ## ##                                       Step 6 request access, approvals, audit chain, retention, erasure (weeks 3 to 12)
S7      ## ## ## ## ##                   ## ## ## ## ## ## ## ## ## ## ##      Step 7 rating and baseline (weeks 2 to 6), expert sets to 200 per node by week 18 and 385 cross-node by week 23
St1                     ## ## ## ## ## ##                                      Stage 1 pilot node, public documents (weeks 7 to 12)
St2                                       ## ## ## ## ## ##                    Stage 2 four nodes, confidential, UC7 real pair (weeks 13 to 18)
St3                                                         ## ## ## ## ##     Stage 3 people data, after the impact assessment (weeks 19 to 23)
St4                                                                     ## ## ## ##  Stage 4 Raychem, Asvata, Others (weeks 23 to 26)
SAP                                       ## ## ## ## ## ##                    SAP connector and Teams notification (weeks 13 to 18)
Dec  ## ## ## ##                                                               Decisions of section 11 (sponsor week 1, build or host week 4)
```

Week 1 also starts the two collections that need the longest lead time and no code: the list of real documents chosen by each data owner (Step 8) and the baseline timing of 20 staff per company (Step 7).

## 13. Sources

| Number | Source | Date | Used for |
|---|---|---|---|
| 1 | Digital Personal Data Protection Act, 2023, Gazette text, meity.gov.in | 11 August 2023 | Sections 5, 6(10), 7(i), 8, 12, 16 |
| 2 | Digital Personal Data Protection Rules, 2025, G.S.R. 846(E), Gazette PDF, meity.gov.in | 13 November 2025 | Rules 3, 4, 6, 7, 8 and the phased start |
| 3 | AZB and Partners, ConsentPlix tracker (17 October 2026) and SCC Online (15 October 2026) on the DPDP phased rollout, secondary | October 2026 | The 12, 13 or 14 May 2027 date difference |
| 4 | SEBI (Prohibition of Insider Trading) Regulations, 2015, consolidated text, sebi.gov.in | August 2026 copy | Regulations 2(1)(n), 3(1), 3(2A), 3(2B), 3(5), 3(6), Schedule B clause 4 |
| 5 | CERT-In Directions under section 70B, cert-in.org.in | 28 April 2022 | Six-hour incident report, 180-day logs |
| 6 | WHO Technical Report Series 1033, Annex 4 | 2021 | ALCOA+ and true copy, RPG Life Sciences node as a reference only |
| 7 | India AI Governance Guidelines, PIB document | 5 November 2025 | Principles used as a checklist |
| 8 | ISO/IEC 27002:2022 controls 5.12 and 8.33, read through a secondary guide (isms.online), the ISO text is paid | 2022 | Owner classification, no sensitive data in test environments |
| 9 | Microsoft Graph: driveItem extractSensitivityLabels, sensitivityLabel, driveItem delta, learn.microsoft.com | pages updated 2026-07-24, 2026-11-04, 2026-06-06 | Label reading, 423 errors, delta sync, 410 Gone |
| 10 | Azure AI Search: SharePoint indexer permission metadata, learn.microsoft.com | 2026-09-17 | Stale access lists |
| 11 | Azure Data Factory: SAP change data capture, learn.microsoft.com | 2026-09-11 | ODP route blocked by SAP Note 3255746, deletions |
| 12 | Glean Indexing SDK: Permissions, developers.glean.com | undated | Groups rather than flattened users |
| 13 | Microsoft 365 Copilot connectors overview, learn.microsoft.com | 2026-09-30 | Federated connectors leave data in the source |
| 14 | Microsoft Presidio supported entities, presidio.dataprivacystack.org | undated | Indian recognisers, English default |
| 15 | PIIBench, arXiv 2604.15776 | 17 April 2026 | Presidio span-level F1 0.1385 |
| 16 | Naamapadam, arXiv 2212.10168, abstract figures only | 2022 | Indian-language named entity scores |
| 17 | EDPB Guidelines 02/2025 on pseudonymisation, version 2.0 | adopted 7 July 2026 | Keyed hash in audit lines |
| 18 | Data Mesh Principles and Logical Architecture, martinfowler.com | 3 December 2020 | Federated computational governance |
| 19 | all-MiniLM-L6-v2 model card (GitHub copy of the card) | undated | 256 word-piece truncation, 384 dimensions |
| 20 | BGE-M3 paper, arXiv 2402.03216 | February 2024 | 8,192 tokens, 100+ languages, MLDR and MIRACL scores |
| 21 | IndicRAGSuite, arXiv 2506.01615 | June 2025 | IndicMSMarco scores for Hindi, Marathi, Malayalam |
| 22 | Qwen3-Embedding blog, qwenlm.github.io | 5 June 2025 | Second embedder candidate |
| 23 | Docling technical report, arXiv 2408.09869, and README | August 2024 | MIT licence, formats, 1.27 pages per second, OCR speed |
| 24 | Surya and Marker README, github.com/datalab-to | undated | Weight licence terms |
| 25 | PaddleOCR README, github.com/PaddlePaddle | undated | Hindi named, Malayalam absent |
| 26 | Open-Source OCR Libraries: A Comprehensive Study for Low Resource Language, ICON 2024, aclanthology.org | December 2024 | Tesseract Malayalam support |
| 27 | Chroma Research: Evaluating Chunking Strategies, and Generative Benchmarking | undated | Chunking recall difference, generated questions |
| 28 | Anthropic: Introducing Contextual Retrieval | 19 September 2024 | 35% to 67% failure reduction |
| 29 | Jina AI: Late Chunking | undated | Context-preserving chunks |
| 30 | datasketch MinHash LSH documentation | undated | Near-duplicate detection |
| 31 | Result Merging in Distributed Indexing, W3C Distributed Indexing Workshop paper | May 1996 | Node scores are not comparable |
| 32 | Seven Failure Points When Engineering a Retrieval Augmented Generation System, arXiv 2401.05856 | January 2024 | Failure tags |
| 33 | Ragas documentation: Context Recall, Faithfulness | undated | Reference answers needed |
| 34 | Wikipedia: Binomial proportion confidence interval (formulas, applied to the counts in Steps 7 and 9) | read 2026-11-11 | Wilson score intervals and sample sizes |
| 35 | MCP specification 2026-07-28: changelog, authorization, enterprise-managed authorization extension, modelcontextprotocol.io | 28 July 2026 | Stateless protocol, audience checks, no token passthrough |
| 36 | RFC 8693 OAuth 2.0 Token Exchange, RFC 8707 Resource Indicators | January 2020, February 2020 | Per-node tokens |
| 37 | Microsoft identity platform: On-Behalf-Of flow, learn.microsoft.com | 2026-06-15 | Same-tenant delegation |
| 38 | Anthropic Commercial Terms of Service | 17 June 2025 | No training on customer content |
| 39 | Claude Platform docs: API and data retention, Data residency, Pricing, Claude in Amazon Bedrock, Claude on Google Cloud | read 2026-11-11 | Retention, "us" and "global" only, list prices, regional 10% premium |
| 40 | AWS Price List for Amazon Bedrock foundation models, ap-south-1 (JSON) and AWS model cards for Claude Opus 5, Sonnet 5, Haiku 4.5, Sonnet 5.5, Opus 5.5, Haiku 5.5 | published 2026-11-09 | India inference profile and Mumbai prices |
| 41 | Microsoft Foundry: Deploy and use Claude models, learn.microsoft.com | 2026-09-21 | Data zones, no India pinning |
| 42 | openai/gpt-oss README, github.com | undated | gpt-oss-120b size, licence, GPU |
| 43 | OWASP Top 10 for LLM Applications 2025, LLM08 | 2025 | Vector and embedding weaknesses |
| 44 | PoisonedRAG, arXiv 2402.07867 | 12 February 2024 | 90% attack success with five texts |
| 45 | The Attacker Moves Second, arXiv 2510.09023 | 10 October 2025 | Twelve defences bypassed |
| 46 | CaMeL: Defeating Prompt Injections by Design, arXiv 2503.18813 | 24 March 2025 | Separation of instructions and data |
| 47 | Llama Prompt Guard 2 model card, github.com/meta-llama | undated | Classifier as a flag |
| 48 | Vec2Text: Text Embeddings Reveal (Almost) As Much As Text, arXiv 2310.06816 | 10 October 2023 | Embedding inversion |
| 49 | NIST AI 600-1 Generative AI Profile | July 2024 | Control checklist |
| 50 | OpenTelemetry GenAI semantic conventions, github.com/open-telemetry | undated, Development status | Tracing without content |
| 51 | raychemrpg.com | read 2026-11-11 | 50:50 joint venture with TE Connectivity |
| 52 | tele.net.in item on TE acquiring the telecom business stake of the Raychem joint venture, undated trade report | undated | To confirm what Raychem RPG owns |
| 53 | asvata.com | read 2026-11-11 | Climate action business, few public documents |
| 54 | Zensar press release on ZenseAI.AgentMesh and the AgentMesh product page, zensar.com | 17 June 2026 | Overlap and positioning |
| 55 | Harrisons Malayalam Annual Report 2025-26, NSE archives and harrisonsmalayalam.com | for the year ended 31 March 2026 | 193 pages, 99,787 words, 6,731 employees, 24 estates |
| 56 | Harrisons Malayalam shareholding pattern as of 30 September 2026, read through Emkay Global (aggregator of the exchange filing), rpggroup.com and rpsg.in company pages | 2026 | Promoter group 54.12%, both groups present |
| 57 | KEC International investors page and Annual Report 2025-26, kecrpg.com | 2026 | First real documents |
| 58 | CEAT shareholder information page, ceat.com | investor presentations to 14 October 2026 | First real documents |
| 59 | RPG Life Sciences annual reports page, rpglifesciences.com | 2026 | First real documents |
| 60 | AWS press release on CEAT and SAP S/4HANA (vendor) and DataQuest on KEC and SAP (trade press) | 17 August 2022, 28 August 2017 | Enterprise systems, publicly reported only |
| 61 | Bureau of Indian Standards Act, 2016, section 11, and the ISO help centre on intranet posting | 2016, undated | Standards as metadata only |
| 62 | Rubber Research Institute of Sri Lanka, Collection and Preservation of Latex (foreign source) and Polymers (MDPI) 7 December 2023 on ammonia preservation | undated, 2023 | Background for the flagship question, metadata only |
| 63 | NeuralMesh source files (`kbgen.py`, `services/uploads.py`, `services/neuralmesh.py`, `services/context/policy.py`, `services/context/builder.py`, `mcp_nodes/policy.py`, `api/routers/mesh.py`, `api/account_store.py`, `knowledge/packgen.py`, `config/model_policy.json`), the central model-call events of 2026-11-06 to 2026-11-10, the NeuralMesh design plan (sections B4 to B8), the implementation status of 2026-11-10 and the architecture design review of 2026-11-10 | read 2026-11-11 | Line references, token medians and counts about today's code |

## 14. Glossary

| Term | Meaning in this document |
|---|---|
| Node | The MCP server one company runs over its own knowledge. By design, text and vectors stay in it. Today the centre also writes uploads into node folders |
| Centre | The FastAPI and LangGraph service that routes a question to nodes and writes the answer. By design it holds metadata only. Today it also holds Snap and Score inspection results |
| Pack | The folder of documents, catalogue and policy files that one node serves for one domain. There are 37 packs today |
| Catalogue item, datapoint | One entry of a node's catalogue, with a code such as E-03, a sensitivity tier, a ceiling and an owner. Documents belong to items |
| Ceiling | The highest exposure mode the data owner has allowed for an item |
| Data owner | The person in a company who owns one catalogue item and approves its summary and exposure mode |
| Node owner | The person who runs one company's node |
| Mesh admin | The role that administers the centre and today is the only role that can upload |
| Mesh Council | The group body of node owners named in the design plan to decide shared rules |
| Subject expert | An employee who knows a topic and writes the reference answer for a test question. Not the same as an expert listed in UC1 |
| Check, test, measure, gate | A check is an automatic rule on every answer. A test is a set of questions with known right answers. A measure is a number computed from tests or events. A gate is a rule that decides whether a record or a model may be used |
| Model tiers | Gateway: a model reached through a company-run proxy. Local: a model run on a server inside the company network. Cloud: a model reached over the public internet |
| Node maturity L0 to L3 | The design plan's levels: L0 metadata only, L1 owner-approved summaries, L2 cited retrieval, L3 agentic (the node runs multi-step tasks) |
| Exposure mode | What a node may return for an item: MD (title and owner only), SUM (an owner-approved summary, today the first 400 characters of an upload with no review), RAG (cited text chunks), LIVE (a scoped query result) |
| Sensitivity tier | Public, Internal, Confidential or Restricted, set by the data owner |
| Never-leave list | Records capped at metadata (title and owner) for every other company in every mode: UPSI, personal data beyond consented expert fields, joint venture or partner intellectual property, client-confidential and privileged material, and any Restricted record whose data owner has not allowed a summary |
| Synthetic | A record written by the generator or any invented source, marked `synthetic: true`. Everything else is real |
| Connector | The code that reads items from a company system by id, with changes, deletions and access lists |
| Access list (ACL) | The users and groups allowed to read an item in its source system |
| Chunk | One indexed piece of a document, here one section of at most 400 tokens with its heading path |
| Embedder | The model that turns a chunk into a vector for similarity search. BGE-M3 is proposed, all-MiniLM-L6-v2 is used today |
| FTS5 | The SQLite full-text keyword index used in every node |
| Quarantine, draft | The state of a new document that nobody can see until its data owner approves it |
| Marker (canary) | A unique string planted in a document so that its appearance in an answer proves a leak |
| UPSI | Unpublished price sensitive information as defined in regulation 2(1)(n) of the SEBI (Prohibition of Insider Trading) Regulations, 2015 |
| Trading window | The period from the end of a quarter until 48 hours after results in which UPSI holders may not trade and sharing is restricted |
| DPDP Act | The Digital Personal Data Protection Act, 2023, with its Rules of 2025 |
| Data fiduciary, data processor | Under the DPDP Act, the party that decides the purpose of processing, and the party that processes on its behalf under contract |
| Data protection impact assessment | A written assessment of the risks to people before a new processing of their data starts |
| Wilson score interval | The range in which the true proportion is likely to lie (95% confidence here), given the count observed. Narrower with more questions |
| Recall | The share of questions for which the required document is found |
| India inference profile | An Amazon Bedrock routing choice that keeps model requests inside Mumbai and Hyderabad |
| Token exchange | Trading one signed token for another with a different audience, as defined in RFC 8693 |
| JWKS | A published set of public keys used to verify signed tokens |
| MCP | Model Context Protocol, the protocol between the centre and the nodes, version 2026-07-28 |
| OCR | Optical character recognition, reading text from a scanned page image |
| Hash chain, HMAC | An audit log in which each line carries a hash of the previous one, keyed with a secret so that a line cannot be rewritten without the key |
| HS256, JWT, jti | HS256 is a token signature made with one shared secret. A JWT is a signed token of claims. jti is the token's unique id, used to revoke it |
| etag, delta token | An etag is a version marker of one item in a source system. A delta token is a bookmark from which a source lists what changed since |
| SCP | An AWS service control policy, an account-wide rule that denies named actions |
| Amazon Bedrock, vLLM, GPU | Bedrock is the AWS service that serves Claude models. vLLM is a server for open-weight models. A GPU is the graphics processor such models run on |
| SAP S/4HANA, ODP | S/4HANA is SAP's enterprise resource planning system. ODP is SAP's framework for extracting changed records |
| Presidio, Docling, Tesseract, BGE-M3, MinHash | Presidio detects personal data in text. Docling reads PDF, Word, Excel and PowerPoint files into structured text. Tesseract reads text from page images. BGE-M3 is the proposed embedding model. MinHash is a fingerprint for finding near-duplicate documents |
| PAN, GSTIN, Aadhaar | PAN is the Indian Permanent Account Number for tax. GSTIN is the 15-character goods and services tax registration number. Aadhaar is the 12-digit resident identity number |
| CERT-In | The Indian Computer Emergency Response Team, which issued the 2022 directions on incident reporting and logs |
| F1 score | A score that balances precision (share of hits that are right) and recall (share of true items found), from 0 to 1 or 0 to 100 |
| p95, probe, availability | p95 is the response time that 95 of 100 requests beat. A probe is a scheduled test request. Availability is the share of probes answered |
| min_group | The smallest number of source records a returned grouped figure may rest on |
| SkillForge, Snap and Score | The two applications that call NeuralMesh through its context contract: SkillForge for skills and careers, Snap and Score for asset inspections |
| Significant Data Fiduciary | A data fiduciary notified as such by the Central Government under the DPDP Act, with extra duties such as a yearly impact assessment |
