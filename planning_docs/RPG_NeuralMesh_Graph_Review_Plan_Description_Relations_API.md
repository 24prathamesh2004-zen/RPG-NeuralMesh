# RPG NeuralMesh: Plan for the Graph Review Points

Date: 2026-11-13. Status of each step is stated in its section.

## 1. Goal

Make each context graph usable by a person and by another application without explanation:

- A person opens a graph and reads what it is about, sees its documents or its drawing without scrolling, and sees a name on every link.
- An application reads and queries one graph by its id.
- A question on Ask NeuralMesh finds the graph it is about.
- A person is asked to decide only when the text leaves a doubt.

## 2. Contents

1. Goal
2. Contents
3. Is This the Right Direction
4. The Points and What Each One Needs
5. How the Parts Work Together
6. Step 1: A Description for Every Graph
7. Step 2: Names on the Links
8. Step 3: A Person Decides Only on a Doubt
9. Step 4: Use This Graph
10. Step 5: Ask NeuralMesh Finds the Graph
11. Step 6: Expert Finder and Its Source
12. What the Check on the Two Real Graphs Showed
13. Roadmap
14. Sources

## 3. Is This the Right Direction

Yes for six of the seven sections, with two limits that the plan has to respect.

| Section of the review | Right direction | Why, or the limit |
|---|---|---|
| Tabs for documents and graph | Yes | Built on 2026-11-13. |
| A description for every graph | Yes, and it comes first | Ask and the review rule both read it. |
| Names on the links | Yes | Every link already has a type, but the drawing did not write it. The relation between two topics can be read from the sentence by code only when the sentence states it with a plain relation word. |
| An API for each graph, shown in the graph view | Yes | The API existed for a graph ingested as JSON only. A graph made by Upload input could not be queried by an application. |
| Ask finds the graph by its description | Yes, as an addition | It must not replace the sharing rules. A document that never leaves its company still gives Ask its title only. |
| A person decides only on a doubt | Yes | The rule settles a link only when the text is clear. On the two real graphs no topic link is clear enough, because the topics are found by single words, so all of them still wait for a person. |
| Expert Finder reads from the graphs | Already the case | No change is needed. See section 11. |

The two limits:

1. **Named relations on real documents need a model that is allowed to read them.** Code read 43 links from the two real graphs and found a relation word in none of them. The model step that names relations exists, but the model policy keeps a cloud model away from real data. Until a model inside the allowed boundary is configured, a person adds named relations to a real graph by loading a corrected JSON, which is built.
2. **The topics come from the group vocabulary.** The real documents are about employee and delivery matters, and the vocabulary has few topics for them. So a meeting on a product roadmap is linked to topics such as "Materials handling" through a single shared word. Better links on this data need vocabulary entries for it. That is a data task, not a code task.

## 4. The Points and What Each One Needs

| # | Point from the review | What it needs | Status |
|---|---|---|---|
| 1 | Two tabs on the chosen graph, buttons kept beside them | Page layout | Built |
| 2 | A named relationship on every link, shown in the graph | Link names in the drawing, relation read from the sentence | Built, with limit 1 |
| 3 | The step that makes the JSON finds the relationships | Same as point 2 | Built for sentences that state a relation |
| 4 | Meetings show no relationship to each other | A calculated link between two inputs that share topics | Built |
| 5 | An API for each graph, shown in the graph view | The graph API serves uploaded graphs, and a "Use this graph" tab | Built |
| 6 | Sample JSON and download reachable in the app | Nothing new | Was built |
| 7 | MCP access | A tool of the MCP gateway that reads one graph by its id | Not planned. The graph is reached through the web API |
| 8 | A description of 5 to 6 lines on every graph | Description made by code, editable by a person | Built |
| 9 | Replace "What every company may read" with "Description" | Same as point 8 | Built |
| 10 | Ask understands the question, reads the descriptions, loads the graph | Graph match in the routing of Ask | Built, with the sharing rule kept |
| 11 | Expert Finder takes its data from the graphs | Check of the source | Checked, no change |
| 12 | A person is asked only on ambiguity or a mismatch with the graph | Settling rule for links, review list for inputs | Built |

## 5. How the Parts Work Together

```
   Upload input (file, folder, zip)              Graph JSON (ingest or correction)
              |                                                |
              v                                                v
   +----------------------------- one context graph ------------------------------+
   |  inputs --> topics of the vocabulary                                         |
   |  links  --> named by the sentence, or "related to"                           |
   |  links between inputs that share 3 topics or more   (calculated)             |
   |  description: made from the inputs, or written by a person                   |
   +---------+--------------------------+----------------------------+------------+
             |                          |                            |
             v                          v                            v
   Context graph page            Graph API by id              Ask NeuralMesh
   Inputs | Graph | Use this     read, query, overview        match the question to
   graph, description on top     same for both kinds          a description, name the
                                                              graph, ask its company
             |
             v
   A person decides only on:  a link named once with no relation word
                              an input that shares no topic with the graph
```

## 6. Step 1: A Description for Every Graph

**Status: built.**

| Item | How it works |
|---|---|
| Made by code | Six sentences from the inputs: how many and whose, kinds of input, the six topics most inputs name, the first four titles, the upload dates, the sharing rule. |
| Written by a person | A mesh admin, or a person of a company that keeps an input in the graph, presses Edit and writes 20 to 1,000 characters. An emptied text brings the made one back. |
| Who sees which | The written text shows to people who see the whole graph. Anyone else gets the description made from the inputs they may see. |
| Where it shows | Above the tabs of the chosen graph, in the graph API, and under the graph name on Ask. |
| Graph ingested as JSON | Keeps the description its JSON gives, as before. |

```
   inputs of the graph ----> code writes 6 sentences ----+
                                                         +--> Description
   a person presses Edit --> writes own text ------------+    (own text wins)
```

**Key insight.** The description is made on reading, from what the reader may see. Nothing new is stored unless a person writes one, so a description can never show more than the inputs behind it.

## 7. Step 2: Names on the Links

**Status: built, with limit 1 of section 3.**

| Item | How it works |
|---|---|
| Link names in the drawing | A switch "Link names" writes the name of every link on its line: mentions, in datapoint, owned by, broader, related to, shares topics with. It starts on for a graph of up to 60 links and off above that, where the names would cover each other. |
| Relation read from the sentence | When a relation word stands between two topic names of one sentence, within eight words, the link takes that relation and runs from the first name to the second. Fifteen relations are known, for example depends on, blocked by, causes, part of, includes, uses, owned by, replaces, follows. |
| Links kept before this step | The relation is read again from the stored evidence sentence each time the graph is read. No stored file is rewritten. |
| What an input states | A sentence that states a decision, a next action or a risk in set wordings ("we agreed to", "the follow-up is", "my concern is") becomes a node of type Decision, Action or Risk. Its input is linked to it by has decision, has action or has risk, and it is linked to the topics it names by about. Up to three of each kind and eight in all for one input. A question is not a statement, and the name of a speaker is left out. |
| Links between inputs | Two inputs of a graph that name three topics or more in common get a link "shares topics with". Each input is linked to the two inputs it shares most with. The link names the shared topics and is calculated on reading. |

```
   "The checklist depends on the cutover plan."
        [topic A]   ^^^^^^^^^^   [topic B]
                    relation word
        A --depends on--> B          stated in the text, no person asked

   "The checklist and the cutover plan came up."
        A --related to--> B          named once, waits for a person
```

**Key insight.** Code names a relation only where the sentence states it. It does not guess one. Where the text does not state a relation, the honest link is "related to", and a named relation has to come from a model that may read the text or from a person's JSON.

## 8. Step 3: A Person Decides Only on a Doubt

**Status: built.**

| Case | Who decides | Shown as |
|---|---|---|
| The sentence states a relation between the two names | The rule | stated in the text |
| Two sentences or more name both topics by their full names | The rule | named together in N sentences |
| The text names the two together once, with no relation word | A person | to review, with Approve and Reject |
| A topic is found by another name or by one word of its name, for example "handling" for "Materials handling" | A person | to review, however often it is named |
| A person approved the link | That person | approved by a person |
| A link the model found | A person | to review |
| An input that shares no topic with the other inputs of its graph | A person | To review on the input, with "Keep in this graph" or "Remove this input" |
| An input that names no known topic, in a graph of two inputs or more | A person | Same |

A person's decision always stands over the rule. A link the rule settled can still be rejected.

```
   link from the text --> relation stated?  --yes--> approved by the rule
                                |
                                no
                                v
                    both full names in 2+ sentences? --yes--> approved by the rule
                                |
                                no --> to review (a person)
```

**Key insight.** The doubt is measured from the text, not from a score. Two countable facts decide: is there a relation word, and how many sentences name both topics in full. A match on one word of a topic name is itself a doubt, so it never settles a link.

## 9. Step 4: Use This Graph

**Status: built. An MCP tool is not planned.**

| Item | How it works |
|---|---|
| Third tab "Use this graph" | Shows the graph id and three ready calls with the id in them: read the graph as JSON, ask it a question, list its node types and link types. Each has a Copy button. |
| One API for both kinds | `GET /api/v1/context-graphs/{id}` and `POST /api/v1/context-graphs/{id}/query` now also take the id of a graph made by Upload input. The graph is put into the same shape on reading, from what the caller may see. |
| List | `GET /api/v1/context-graphs?uploaded=true` adds the uploaded graphs with their descriptions and addresses. |
| Access | The caller's token decides. A caller who may see no input of the graph gets 404. |
| Written answer | Follows the model policy. A cloud model never reads a graph that holds real data. |

```
   application --token--> GET  /context-graphs/g-4f141508          the graph as JSON
               --token--> POST /context-graphs/g-4f141508/query    {"question": "..."}
                                                                   {"overview": true}
```

**Key insight.** The uploaded graph is not copied into a second store for the API. It is read through the same access rules as the page, so the API and the page cannot disagree.

**MCP.** The MCP gateway gives the context tools of the central graph to registered applications. A tool that reads one context graph by its id is not planned. An application reaches a graph through the three web API calls above.

## 10. Step 5: Ask NeuralMesh Finds the Graph

**Status: built.**

| Item | How it works |
|---|---|
| Match | A question is matched to the graphs the asker may see: first by topics both name, then by words shared with the name, the description and the titles, and, when neither finds a graph, by closeness of meaning to the description. |
| Routing | When the wording names no topic and no company, the companies of the matched graph are asked. Before this step such a question went to the classifier or to the asker's own company. |
| What Ask shows | A panel "Context graphs this question is about" with the graph name, why it matched, its description, and up to eight links the graph holds about the question. The decisions, actions and risks of the matched input come first. |
| Sharing rule | Unchanged. A document under an item that never leaves its company gives Ask its title only, also when its graph matched. |

```
   question --> topics and words --> match against graph descriptions
                                              |
                      +-----------------------+----------------------+
                      v                                              v
        graph named on Ask, with its links                its company is asked,
        about the question                                under its sharing rules
```

**Key insight.** Finding the graph and reading its documents are two separate permissions. The first tells the asker where the knowledge is. The second stays with the owning company.

**Defect found and fixed in this step.** A catalogue item named at upload was unknown to the policy of its node, so every document under it was withheld from Ask as "Unknown datapoint". The node now reads these items, and such a document is listed as "Only its title is shared", which is the rule of the item.

## 11. Step 6: Expert Finder and Its Source

**Status: checked, no change.**

| Question | Answer |
|---|---|
| Where do the experts come from | From the expert list each company keeps at its own node. Only people who agreed to be listed are in it. |
| Are they in the graph | Yes. Each expert is an entity of the central graph, linked to the documents that are the evidence. |
| How does the search use the graph | The topics of the question are resolved on the graph and passed to each node, which adds them to an expert's score when the evidence covers them. |
| Do uploaded documents add experts | No. A person named inside an uploaded document does not become an expert, because that person did not agree to be listed. |

**Key insight.** One source is already in place. Keeping uploaded documents out of it is deliberate, because consent comes from the person and not from a document.

## 12. What the Check on the Two Real Graphs Showed

The two graphs are the ones uploaded on 2026-11-12, with 16 inputs and 3 inputs.

| Measure | 16 inputs | 3 inputs |
|---|---|---|
| Links read from the text by code | 21 | 22 |
| Of these, with a named relation | 0 | 0 |
| Settled by the rule (both full names in two sentences or more) | 0 | 0 |
| Waiting for a person | 21 | 22 |
| Waiting for a person before this step | 21 | 22 |
| Calculated links between inputs | 15 | 3 |
| Inputs to review | 0 | 0 |
| Description | 6 sentences, made by code | 6 sentences, made by code |

**Run of the two downloaded zip files on a copy of the data, 2026-11-13.** The 16 meeting transcripts gave 83 statements (18 decisions, 32 actions, 33 risks), each with a named link from its input. The 3 knowledge documents gave 3 statements, because they state rules and not decisions. The question "What was decided in the quarterly product roadmap review?" found the meeting and its decision through the graph API, and the run passed 21 of 21. On the running stack the same inputs get their statements only after the extraction is made again, which was not done there.

Checks run: 300 backend tests pass, 9 of them new. The browser check of the description, the three tabs, the three calls, the link names, the review count and Ask passed 13 of 13 on the running stack. Nothing was saved, approved, rejected or removed on the running stack during the check.

Not checked: a save of a written description on the running stack, the "Keep in this graph" button on real data (no real input is listed for review), and a cloud model on any of these paths.

## 13. Roadmap

| Order | Step | State | Depends on |
|---|---|---|---|
| 1 | Description for every graph | Built | |
| 2 | Link names, relation from the sentence, links between inputs | Built | |
| 3 | A person decides only on a doubt | Built | 2 |
| 4 | Use this graph, graph API for uploaded graphs | Built | 1 |
| 5 | Ask finds the graph | Built | 1 |
| 6 | Expert Finder source | Checked | |
| 7 | Vocabulary entries for employee and delivery topics | Open | A person who knows the documents |
| 8 | Named relations between topics on real documents by a model | Open | A model inside the allowed boundary |
| 8a | Rule statements of policy documents ("must", "is required to") as nodes | Open | A decision on how many to keep for one document |
| 9 | MCP tool that reads one graph by its id | Not planned | The graph is reached through the web API |
| 10 | API reference updated for the uploaded graphs | Open | 4 |

## 14. Sources

- The review call of 2026-11-13 on the Context graph page, as transcribed.
- `app/services/graph_describe.py`, `app/services/graph_extract.py`, `app/services/uploads.py`, `app/api/routers/context_graphs.py`, `app/services/neuralmesh.py`, `app/mcp_nodes/server_config.py`.
- `app/tests/test_graph_describe.py`.
- `app/config/model_policy.json` for the rule that keeps a cloud model away from real data.
