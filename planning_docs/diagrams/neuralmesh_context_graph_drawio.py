"""Build the high-level, end-to-end draw.io diagram of RPG NeuralMesh as the group context graph.

Not tied to the code built so far. Same colours and style as the skill evaluation architecture diagram.
Run:  python planning_docs/diagrams/neuralmesh_context_graph_drawio.py
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).with_name("RPG_NeuralMesh_Context_Graph_Architecture.drawio")

PURPLE = ("#e1d5e7", "#9673a6")   # applications
GREEN = ("#d5e8d4", "#82b366")    # context API and core
BLUE = ("#dae8fc", "#6c8ebf")     # stores and layers
YELLOW = ("#fff2cc", "#d6b656")   # subsidiary nodes
ORANGE = ("#ffe6cc", "#d79b00")   # intake
RED = ("#f8cecc", "#b85450")      # policy and trust
GREY = ("#f5f5f5", "#666666")     # standards and sources

cells: list[str] = []


def box(cid, text, x, y, w, h, fill, stroke, *, parent="1", bold=False, top=False, size=10, italic=False, width=1, shape=None):
    style = (f"shape={shape};boundedLbl=1;backgroundOutline=1;size=10;" if shape else "rounded=1;") + \
        f"whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={width};fontSize={size};" \
        f"fontStyle={(1 if bold else 0) + (2 if italic else 0)};" + ("verticalAlign=top;" if top else "")
    cells.append(f'<mxCell id="{cid}" value="{escape(text)}" style="{style}" vertex="1" parent="{parent}">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')
    return cid


def container(cid, title, x, y, w, h, colour):
    return box(cid, title, x, y, w, h, colour[0], colour[1], bold=True, top=True, size=12, width=2)


def child(cid, text, x, y, w, h, parent, stroke, *, fill="#ffffff", size=9, italic=False, shape=None, top=False):
    return box(cid, text, x, y, w, h, fill, stroke, parent=parent, size=size, italic=italic, shape=shape, top=top, bold=top)


def edge(cid, src, dst, label="", *, exit_="0.5,1", entry="0.5,0", dashed=False):
    ex, ey = exit_.split(","); nx_, ny = entry.split(",")
    style = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#333333;strokeWidth=1.5;fontSize=9;"
             f"labelBackgroundColor=#ffffff;exitX={ex};exitY={ey};exitDx=0;exitDy=0;entryX={nx_};entryY={ny};entryDx=0;entryDy=0;"
             + ("dashed=1;" if dashed else ""))
    cells.append(f'<mxCell id="{cid}" value="{escape(label)}" style="{style}" edge="1" parent="1" source="{src}" target="{dst}">'
                 f'<mxGeometry relative="1" as="geometry" /></mxCell>')


def note(cid, text, x, y, w, h, size=10):
    cells.append(f'<mxCell id="{cid}" value="{escape(text)}" style="text;html=1;fontSize={size};align=left;verticalAlign=middle;" '
                 f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')


# ── row 1: applications ─────────────────────────────────────────────────────
container("apps", "Applications — each brings its own ontology and asks for context", 40, 40, 1120, 130, PURPLE)
apps = [("SkillForge (talent)", "roles, skills, levels, study material, mentors, similar skills"),
        ("Snap and Score (inspection)", "assets, conditions, grade scales, cover types, live cover status, history"),
        ("Next application", "its own domain ontology, the same seven tools")]
for i, (name, what) in enumerate(apps):
    x = 15 + i * 365
    child(f"app{i}", name, x, 32, 350, 30, "apps", PURPLE[1], fill=PURPLE[0], size=10)
    child(f"app{i}d", what, x, 66, 350, 30, "apps", PURPLE[1])
child("apps-note", "An application holds its screens and its own transactional data. It never holds another company's documents or the policy.",
      15, 100, 1090, 20, "apps", PURPLE[1], italic=True)

# ── standards column (left) ─────────────────────────────────────────────────
container("std", "Standards the platform maintains", 1200, 40, 460, 560, GREY)
standards = ["S1 S2  Node and edge shape", "S3 S4  ID rule, direction and symmetry", "S5 S6  Ontology file per domain, core ontology",
             "S7      Adapters change shape only", "S8 S9  Six checks, sorted normalised file", "S10     Upsert by ID, retire never delete",
             "S11     Live facts are pointers, never stored", "S12     Exposure policy per datapoint (MD, SUM, RAG, LIVE)",
             "S13     Every item is an evidence record 1.0", "S14 S15 Provenance, two-owner approval", "S16     Consent for anything about a person",
             "S17 S18 Versioned ontologies and packs, one audit line per decision"]
for i, t in enumerate(standards):
    child(f"s{i}", t, 15, 32 + i * 42, 430, 36, "std", GREY[1], size=9)

# ── row 2: context API ──────────────────────────────────────────────────────
container("capi", "Context API — REST and MCP gateway, service identity + end-user identity on every call", 40, 210, 1120, 110, GREEN)
tools = [("entity", "the node, its layer, its owner"), ("related", "neighbours by edge type, depth 1 or 2"),
         ("similar", "SIMILAR_TO with the reason"), ("ask", "routed answer with evidence"),
         ("sources", "documents and media by reference"), ("experts", "consented, no names"),
         ("live", "lookup through the owning node"), ("import", "ontology, pack, events")]
for i, (t, d) in enumerate(tools):
    x = 15 + i * 137
    child(f"t{i}", t, x, 32, 130, 26, "capi", GREEN[1], fill=GREEN[0], size=10)
    child(f"t{i}d", d, x, 62, 130, 36, "capi", GREEN[1], size=8)

# ── row 3: core ─────────────────────────────────────────────────────────────
container("core", "Context graph core — metadata only, owned by the mesh team", 40, 360, 1120, 300, GREEN)

child("intake", "Intake", 15, 32, 260, 250, "core", ORANGE[1], fill=ORANGE[0], size=10, top=True)
for i, t in enumerate(["adapters: pack, ontology JSON, talent pack, CSV, JSON Lines, events",
                       "validator: shape, type, signature, reference, duplicate, ownership",
                       "sorter: one normalised file per run, diff = change report",
                       "loader: upsert by ID, retire by source, revision +1"]):
    child(f"in{i}", t, 25, 32 + 28 + i * 54, 240, 46, "core", ORANGE[1], size=8)

child("onto", "Ontology registry", 290, 32, 260, 118, "core", GREEN[1], fill=GREEN[0], size=10, top=True)
for i, t in enumerate(["core.yaml: Organisation, Asset, Concept, Person role, Document, Datapoint, Event, Standard",
                       "talent.yaml · inspection.yaml · next: node types, edge signatures, groups, derived edges"]):
    child(f"on{i}", t, 300, 32 + 28 + i * 44, 240, 38, "core", GREEN[1], size=8)

child("engine", "Resolve, route, context builder", 290, 162, 260, 120, "core", GREEN[1], fill=GREEN[0], size=10, top=True)
for i, t in enumerate(["resolve: names, aliases, meaning match on concepts of every domain",
                       "route: concept → hop → documents and records → owners",
                       "builder: budget, checks, model writes the answer text only"]):
    child(f"en{i}", t, 300, 162 + 28 + i * 30, 240, 26, "core", GREEN[1], size=8)

child("gstore", "Graph store — one store, layers per domain", 565, 32, 280, 250, "core", BLUE[1], fill=BLUE[0], size=10, top=True)
for i, t in enumerate(["core layer: organisations, group vocabulary", "talent layer: roles, skills, role profiles",
                       "inspection layer: assets, conditions, scales, cover types", "knowledge layer: documents, concepts, approved links",
                       "similarity layer: SIMILAR_TO, computed, with reasons", "live pointers: node + tool + key, no values"]):
    child(f"gs{i}", t, 575, 32 + 28 + i * 30, 260, 26, "core", BLUE[1], size=8)
child("gs-engine", "SQLite + NetworkX now · graph database behind the same interface on a trigger", 575, 32 + 28 + 6 * 30 + 4, 260, 28,
      "core", BLUE[1], size=8, italic=True)

child("trust", "Policy gate, evidence, audit", 860, 32, 245, 250, "core", RED[1], fill=RED[0], size=10, top=True)
for i, t in enumerate(["identity check on every call", "two-owner approval of cross-company links",
                       "computed links shown as computed", "every item an evidence record with decision and rule",
                       "context bundle: used, found, withheld, checks, trace ID", "audit: one line per decision, lookup and model call"]):
    child(f"tr{i}", t, 870, 32 + 28 + i * 36, 225, 30, "core", RED[1], size=8)

# ── row 4: nodes ────────────────────────────────────────────────────────────
container("nodes", "Subsidiary nodes — the data owners, one MCP server each, policy applied before anything leaves", 40, 700, 1120, 260, YELLOW)
companies = ["CEAT", "KEC International", "Harrisons Malayalam", "Raychem RPG", "Zensar and the next wave"]
for i, name in enumerate(companies):
    x = 15 + i * 219
    child(f"n{i}", name, x, 32, 210, 200, "nodes", YELLOW[1], fill=YELLOW[0], size=10, top=True)
    child(f"n{i}a", "documents, chunks, vectors", x + 8, 60, 194, 28, "nodes", BLUE[1], size=8)
    child(f"n{i}b", "records and events (inspections, assessments)", x + 8, 94, 194, 28, "nodes", BLUE[1], size=8)
    child(f"n{i}c", "live systems: insurance cover, stock, history", x + 8, 128, 194, 28, "nodes", BLUE[1], size=8)
    child(f"n{i}d", "policy per datapoint, consent, grants, audit", x + 8, 162, 194, 28, "nodes", RED[1], fill=RED[0], size=8)
    child(f"n{i}e", "tools: search, summarize, experts, export_graph, live lookups", x + 8, 196, 194, 28, "nodes", YELLOW[1], size=8)
child("nodes-note", "Text, vectors, records and live values stay here. The core receives metadata and evidence records only.",
      15, 236, 1090, 18, "nodes", YELLOW[1], italic=True)

# ── sources ─────────────────────────────────────────────────────────────────
container("src", "Sources behind each node", 1200, 700, 460, 260, GREY)
for i, t in enumerate(["Document stores, SOPs, RCAs, standards", "Quality, maintenance and inspection systems",
                       "HR systems: roles, skills, consented expert directory", "Insurance and asset registers (live lookups)",
                       "Image and media libraries (reference images, by reference)", "Application ontology files (Ontology.json of Snap and Score)"]):
    child(f"sr{i}", t, 15, 32 + i * 37, 430, 32, "src", GREY[1])

# ── edges ───────────────────────────────────────────────────────────────────
edge("e1", "apps", "capi", "tools over REST or MCP, with service and user identity")
edge("e2", "capi", "core", "one request → resolve, route, policy, bundle")
edge("e3", "core", "nodes", "MCP: search, summarize, export_graph, live lookup (user token minted per node)")
edge("e4", "src", "nodes", "", exit_="0,0.5", entry="1,0.5")
edge("e5", "nodes", "core", "export_graph → metadata only · evidence records after policy", exit_="0.85,0", entry="0.85,1", dashed=True)
edge("e6", "apps", "capi", "import: ontology, packs, events", exit_="0.15,1", entry="0.15,0", dashed=True)
edge("e7", "std", "core", "", exit_="0,0.7", entry="1,0.5", dashed=True)

note("title", "RPG NeuralMesh as the group context graph — high level, end to end (2026-11-06)", 40, 8, 1000, 24, size=14)
note("legend", "Purple: applications · Green: context API and core · Orange: intake · Blue: stores and layers · Red: policy and trust · "
     "Yellow: subsidiary nodes · Grey: standards and sources · Dashed: data and rules flowing in", 40, 980, 1120, 24, size=9)

xml = ('<mxfile host="app.diagrams.net" agent="neuralmesh_context_graph_drawio.py" version="24.0.0">\n'
       '<diagram name="RPG NeuralMesh Context Graph" id="neuralmesh-context-graph">\n'
       '<mxGraphModel dx="1700" dy="1260" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
       'page="1" pageScale="1" pageWidth="1700" pageHeight="1040" math="0" shadow="0">\n<root>\n'
       '<mxCell id="0" />\n<mxCell id="1" parent="0" />\n' + "\n".join(c for c in cells if c) +
       '\n</root>\n</mxGraphModel>\n</diagram>\n</mxfile>\n')
OUT.write_text(xml, encoding="utf-8")
print(f"wrote {OUT} with {len(cells)} cells")
