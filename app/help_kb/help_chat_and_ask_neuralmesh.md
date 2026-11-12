# NeuralMesh help chat

## What the help chat answers

The chat icon at the bottom right of every page opens the NeuralMesh help chat. It answers questions about the application itself: what each page shows, how to do a task, what a term means (exposure mode, datapoint, context graph, knowledge pack, approval, purpose) and which features are built or only planned. It reads the NeuralMesh guides and planning documents and the list of registered Mesh Nodes. It never reads company documents and never calls a Mesh Node.

## Help chat compared with Ask NeuralMesh

- **Help chat:** questions about using NeuralMesh. Example: "How do I add an input to an existing context graph?"
- **Ask NeuralMesh** (the Ask NeuralMesh page): questions about the knowledge of the companies. Each Mesh Node searches its own documents under its own policy and returns cited evidence, and the answer is written only from that evidence. Example: "What CEAT learnings could reduce Harrisons Malayalam's latex spoilage?"
- **Expert Finder:** questions about who knows a topic. Names appear only after an approved introduction.

## How the help chat answers

The chat finds the guide sections that match the question, and the answer model of the model policy (the "answer" step in config/model_policy.json) writes a short answer from those sections only. Each answer lists the guides it used. When no answer model is available (no API key, or a cloud model outside development), the chat shows the matching guide sections instead. Each answer is recorded in the central audit with the model and token counts, never with the question or the answer text.

## Common tasks

- **Upload an input to the context graph:** open **Context graph**, choose **Upload input**, pick the company and the catalogue item, choose a new context graph (type its name) or an existing one, set the kind, title and tags, choose a file (.txt, .md, .csv, .json, .pdf or .docx, up to 20 MB) and press **Add to the graph**. The text is read and linked to the concepts named in it.
- **Upload an input to an existing graph:** open the graph under **Uploaded graphs** and press **Upload input to this graph**.
- **Ingest your own graph as JSON:** open **Context graph**, choose **Upload input**, choose a .json file with nodes and edges or press **Paste a graph JSON**, press **Ingest**, then **Add to the graph**. **Download sample** shows the JSON structure. The answer gives the graph id to query it with POST /api/v1/context-graphs/<id>/query and a signed-in person's token.
- **Download a context graph:** open the graph and choose a format under "Download this context graph as".
- **Change which companies a question goes to:** use **Scope** in the top bar, or pick companies on the Ask NeuralMesh page.
- **Clear the chat:** press the bin icon in the chat header. The conversation is kept only in this browser tab.

## How a company keeps its data at its own node

- Each company runs its own Mesh Node, an MCP server with its own documents, keyword index, vector index, policy file and audit log. Uploaded source documents are never copied to the centre.
- The node's policy enforcement point decides what leaves, item by item, from the caller's role and purpose and the exposure ceiling of the datapoint: **MD** metadata only, **SUM** the owner-approved summary, **RAG** cited text chunks, **LIVE** the result of an allow-listed grouped view.
- Restricted datapoints (for example formulations, bid prices, pre-results finance) stay metadata only, so a search shows that they exist and why they are withheld, never their content.
- The centre holds only titles, tags, links and counts in the mesh graph. A graph ingested as JSON is the exception: the central service keeps it as written and shows it only as its sharing rule allows. The **Dashboard** shows the count of source records copied to the centre, which stays at 0.

## How approvals and access requests work

- When an item needs approval, Ask NeuralMesh lists it among the withheld items with the reason "Owner approval is required".
- An access request names the datapoint, the purpose and a justification. It goes to the owner role of that datapoint at the owning company.
- The owner approves or denies it on the **Governance** page. An approval is a grant for that one person, purpose and level, for a limited time of up to 7 days, and it can be revoked.
- An expert's name is released the same way: an introduction request that the company approves.
- Every decision is written to the node's audit log with the rule that decided it, never with the content.
