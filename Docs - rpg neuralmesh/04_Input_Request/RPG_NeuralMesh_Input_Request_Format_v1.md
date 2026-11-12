# RPG NeuralMesh: Input Request for an Application

NeuralMesh builds a context graph from the content of your application, for example the Onboarding buddy. Send the content in one of the two ways below. One application sends one folder.

## Way 1: A Folder of Files

Use this when the content is documents. NeuralMesh reads each file and builds the graph.

**Folder layout.** One folder for the application, sent as it is or as one .zip file of up to 100 files and 200 MB. Inside it, one subfolder for each topic. Each subfolder becomes one context graph, and every file in it becomes one input of that graph.

```
onboarding_buddy/
  inputs.csv
  first_week_checklist/
    joining_day_steps.docx
    laptop_and_access_requests.pdf
  leave_and_attendance/
    leave_policy_2026.pdf
    attendance_faq.md
```

**Files.**

- File types: .txt, .md, .csv, .json, .pdf or .docx.
- Size: up to 20 MB for each file.
- A PDF must hold text that can be selected. A scanned page with no text is not read.
- Each file holds at least 40 characters of text.
- One subject in each file. A file that covers the leave policy and the laptop request is better sent as two files.
- Send each document once. A draft and its final version count as two inputs, so send the final version only.

**The list file, inputs.csv.** One row for each file.

| Column | What to write | Example |
|---|---|---|
| file | The path of the file inside the folder | leave_and_attendance/leave_policy_2026.pdf |
| topic | The name of the context graph, 3 to 80 characters. The same for every file of a subfolder | Leave and attendance |
| company | The RPG company that owns the content, or Others when it belongs to no single company | Zensar |
| title | The title of the document. Leave empty to take it from the file | Leave policy 2026 |
| sharing | Who outside the owning company may read it: full text, summary, title only, or never leaves | summary |
| sensitivity | Public, Internal, Confidential or Restricted | Internal |
| real_data | yes for real content, no for content invented for testing | yes |
| owner | The role of the person who approves this content, not a name | HR operations lead |

The example rows use invented file names.

## Way 2: One Graph as JSON

Use this when your application already holds its content as things and relationships. NeuralMesh keeps the JSON as written and builds nothing itself.

- One JSON file for each graph, up to 8,000,000 bytes, with up to 5,000 nodes and 20,000 edges.
- An application with several topics sends one JSON file for each topic.

**Needed fields.**

| Field | What to write |
|---|---|
| graph | The name of the graph, 3 to 80 characters |
| company | The RPG company that owns the data |
| nodes | The things, each with "type" and "name" |
| edges | The relationships, each with "type", "source" and "target" |

**Optional fields.** "sensitivity" (Restricted when missing), "sharing" ("company" when missing, or "group" for every company), "description", and "aliases" and "properties" on a node or an edge. A JSON without "synthetic" is treated as real data.

```json
{
  "graph": "Onboarding: first week",
  "company": "Zensar",
  "sensitivity": "Internal",
  "sharing": "company",
  "nodes": [
    {"id": "day-1", "type": "Step", "name": "Joining day", "properties": {"owner_role": "HR operations"}},
    {"id": "laptop", "type": "Request", "name": "Laptop request"},
    {"id": "it-desk", "type": "Team", "name": "IT service desk"}
  ],
  "edges": [
    {"type": "INCLUDES", "source": "day-1", "target": "laptop"},
    {"type": "HANDLED_BY", "source": "laptop", "target": "it-desk"}
  ]
}
```

The values in the example are invented.

## What Not to Send

- Personal data of employees: names with phone numbers, email addresses, salaries, CVs or health details.
- Passwords, keys and tokens.
- A file you may not share inside the RPG group.

## What You Get Back

- The name and the id of each context graph that was made.
- For a folder of files: for each file, the topics it was linked to, and a note when a file linked to no known topic or repeats another file.
- For a JSON: what was filled in, the defaults used, and each place to fix when the JSON is refused.
