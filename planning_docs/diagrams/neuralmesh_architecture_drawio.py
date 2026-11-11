"""Build the draw.io architecture diagram of RPG NeuralMesh (same style as the skill evaluation architecture).

Run:  python planning_docs/diagrams/neuralmesh_architecture_drawio.py
Writes RPG_NeuralMesh_Architecture.drawio next to this script. Open it in draw.io or the VS Code draw.io extension.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).with_name("RPG_NeuralMesh_Architecture.drawio")

# colours of the reference diagram
PURPLE = ("#e1d5e7", "#9673a6")   # screens
GREEN = ("#d5e8d4", "#82b366")    # API
BLUE = ("#dae8fc", "#6c8ebf")     # stores
YELLOW = ("#fff2cc", "#d6b656")   # nodes
ORANGE = ("#ffe6cc", "#d79b00")   # model
RED = ("#f8cecc", "#b85450")      # policy and checks
GREY = ("#f5f5f5", "#666666")     # external

cells: list[str] = []


def box(cid: str, text: str, x: int, y: int, w: int, h: int, fill: str, stroke: str, *, parent: str = "1",
        bold: bool = False, top: bool = False, size: int = 10, italic: bool = False, width: int = 1,
        shape: str | None = None) -> str:
    style = (f"shape={shape};boundedLbl=1;backgroundOutline=1;size=10;" if shape else "rounded=1;") + \
        f"whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={width};fontSize={size};" \
        f"fontStyle={(1 if bold else 0) + (2 if italic else 0)};" + ("verticalAlign=top;" if top else "")
    cells.append(f'<mxCell id="{cid}" value="{escape(text)}" style="{style}" vertex="1" parent="{parent}">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')
    return cid


def container(cid: str, title: str, x: int, y: int, w: int, h: int, colour: tuple[str, str]) -> str:
    return box(cid, title, x, y, w, h, colour[0], colour[1], bold=True, top=True, size=12, width=2)


def child(cid: str, text: str, x: int, y: int, w: int, h: int, parent: str, stroke: str, *, fill: str = "#ffffff",
          size: int = 9, italic: bool = False, shape: str | None = None, top: bool = False) -> str:
    return box(cid, text, x, y, w, h, fill, stroke, parent=parent, size=size, italic=italic, shape=shape, top=top, bold=top)


def edge(cid: str, src: str, dst: str, label: str = "", *, exit_: str = "0.5,1", entry: str = "0.5,0",
         dashed: bool = False) -> None:
    ex, ey = exit_.split(","); nx_, ny = entry.split(",")
    style = ("edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#333333;strokeWidth=1.5;fontSize=9;"
             f"labelBackgroundColor=#ffffff;exitX={ex};exitY={ey};exitDx=0;exitDy=0;entryX={nx_};entryY={ny};entryDx=0;entryDy=0;"
             + ("dashed=1;" if dashed else ""))
    cells.append(f'<mxCell id="{cid}" value="{escape(label)}" style="{style}" edge="1" parent="1" source="{src}" target="{dst}">'
                 f'<mxGeometry relative="1" as="geometry" /></mxCell>')


def note(cid: str, text: str, x: int, y: int, w: int, h: int, size: int = 10) -> None:
    cells.append(f'<mxCell id="{cid}" value="{escape(text)}" style="text;html=1;fontSize={size};align=left;verticalAlign=middle;" '
                 f'vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>')


# ── row 1: callers ──────────────────────────────────────────────────────────
container("sf", "SkillForge (talent platform, separate repository)", 40, 40, 400, 120, GREY)
child("sf1", "Study material, role Q&A, mentors", 15, 32, 180, 36, "sf", GREY[1])
child("sf2", "Talent export: roles, required skills", 205, 32, 180, 36, "sf", GREY[1])
child("sf3", "Reads evidence records only, through the contract (schema version 1.0)", 15, 74, 370, 30, "sf", GREY[1], italic=True)

container("gw", "MCP gateway :8100 — mcp_gateway/server.py", 40, 190, 400, 120, GREEN)
for i, t in enumerate(["role_context", "skill_context", "ask", "learning_sources", "find_mentors", "vocabulary_export"]):
    child(f"gw{i}", t, 15 + (i % 3) * 125, 32 + (i // 3) * 42, 118, 34, "gw", GREEN[1])

container("ui", "Screens — React · Vite :5173", 1180, 40, 480, 270, PURPLE)
for i, t in enumerate(["Ask", "Mesh Nodes + graph explorer", "Governance (link approvals)", "Dashboard",
                       "Expert Finder", "Sign in (demo accounts)"]):
    child(f"ui{i}", t, 15 + (i % 3) * 150, 32 + (i // 3) * 42, 142, 34, "ui", PURPLE[1], size=10)
child("ui6", "Graph explorer: vis-network, opens with companies and datapoints, double-click expands, tree view", 15, 120, 450, 30, "ui", PURPLE[1], italic=True)
child("ui7", "Mesh Nodes shows the graph counts, the node exports and the group packs", 15, 158, 450, 30, "ui", PURPLE[1], italic=True)
child("ui8", "Answers show the evidence, the withheld items and the check results", 15, 196, 450, 30, "ui", PURPLE[1], italic=True)

# ── row 2: the mesh API ─────────────────────────────────────────────────────
container("api", "Mesh API :8000 — FastAPI (api/main.py)", 480, 40, 680, 560, GREEN)
child("auth", "Auth: POC tokens (HS256), require_user, context_client and talent_exporter roles", 15, 32, 650, 30, "api", GREEN[1])

child("flow", "Query flow — LangGraph (services/neuralmesh.py)", 15, 72, 650, 120, "api", GREEN[1], fill=GREEN[0], top=True)
steps = ["resolve\nnames, aliases, meaning", "route\ngraph walk", "fan_out\nnode search (MCP)", "scope\ntop 12, re-rank",
         "expand\napproved links", "build_answer\nbudget, model, 7 checks", "assemble"]
for i, t in enumerate(steps):
    box(f"st{i}", t, 15 + 10 + i * 90, 72 + 34, 84, 50, "#ffffff", GREEN[1], parent="api", size=9)
    if i:
        edge(f"ste{i}", f"st{i-1}", f"st{i}", exit_="1,0.5", entry="0,0.5")
child("flow-note", "Code decides policy, routing and the checks. A model writes only the answer text from the selected evidence.", 25, 72 + 90, 630, 24, "api", GREEN[1], italic=True)

child("ctx", "Context layer (services/context/)", 15, 204, 320, 150, "api", GREEN[1], fill=GREEN[0], top=True)
for i, t in enumerate(["records: evidence record 1.0", "scoping: top 12 round-robin, demote never drop",
                       "builder: 12,000-character budget, omission note", "check: 7 rules (canary, invented source, length...)",
                       "policy: model tiers, strict mode outside dev", "cache: answer and re-rank"]):
    child(f"ctx{i}", t, 25, 204 + 28 + i * 20, 300, 18, "api", GREEN[1], size=8)

child("graph", "Central mesh graph (services/mesh_graph.py)", 345, 204, 320, 150, "api", GREEN[1], fill=GREEN[0], top=True)
for i, t in enumerate(["load: node exports + group packs, retire never delete", "resolve: labels, aliases, 44 names as vectors",
                       "route: concept → hop → documents → companies", "expand: judgement links, two-owner approval",
                       "161 entities, 327 relationships (2026-11-05)", "graph rules today: constants + pack schema"]):
    child(f"gr{i}", t, 355, 204 + 28 + i * 20, 300, 18, "api", GREEN[1], size=8)

child("routes", "Routes", 15, 366, 650, 110, "api", GREEN[1], fill=GREEN[0], top=True)
for i, t in enumerate(["/mesh/query", "/mesh/routing", "/mesh/graph + /refresh", "/mesh/graph/links/.../review",
                       "/context/* (6 tools)", "/context/talent-packs", "/auth/signin, /me", "/mesh/nodes, requests"]):
    child(f"rt{i}", t, 25 + (i % 4) * 160, 366 + 28 + (i // 4) * 38, 150, 30, "api", GREEN[1])

child("store", "SQLite .neuralmesh/mesh_graph.db\nentities · relationships · link_reviews", 15, 488, 300, 60, "api", BLUE[1],
      fill=BLUE[0], shape="cylinder3")
child("audit", "Central audit .neuralmesh/central_audit.jsonl\none line per model call and per node call, trace ID", 335, 488, 330, 60, "api", BLUE[1], fill=BLUE[0])

# ── answer model ────────────────────────────────────────────────────────────
container("model", "Answer model (config/model_policy.json)", 1180, 340, 480, 120, ORANGE)
child("m0", "Tier gateway or cloud: used only when its key is set", 15, 32, 220, 34, "model", ORANGE[1])
child("m1", "Stand-in :11435 (dev): composes from the evidence by rule, not a language model", 245, 32, 220, 34, "model", ORANGE[1])
child("m2", "Every call is logged with its prompt version, tokens and trace ID", 15, 74, 450, 30, "model", ORANGE[1], italic=True)

# ── row 3: nodes ────────────────────────────────────────────────────────────
container("nodes", "Subsidiary nodes — one MCP server per company (mcp_nodes/)", 40, 640, 1120, 300, YELLOW)
node_names = [("CEAT :8101", "6 packs, L2"), ("KEC :8102", "6 packs, L2"), ("Zensar :8103", "4 packs, L2"), ("Harrisons :8104", "3 packs, L1")]
for i, (name, packs) in enumerate(node_names):
    nx0 = 15 + i * 275
    child(f"n{i}", f"{name} — {packs}", nx0, 32, 260, 240, "nodes", YELLOW[1], fill=YELLOW[0], size=10, top=True)
    child(f"n{i}a", "Tools: health, describe_capabilities, search, summarize, find_experts, export_graph, request_access",
          nx0 + 8, 60, 244, 40, "nodes", YELLOW[1], size=8)
    child(f"n{i}b", "Policy per datapoint: exposure mode MD / SUM / RAG / LIVE, purpose, ceiling, never_leave",
          nx0 + 8, 106, 244, 40, "nodes", RED[1], fill=RED[0], size=8)
    child(f"n{i}c", "Search: FTS5 keywords + Chroma vectors (embedded, no server) merged by rank fusion",
          nx0 + 8, 152, 244, 40, "nodes", BLUE[1], size=8)
    child(f"n{i}d", "Grants + audit: access requests, approvals, one audit line per decision",
          nx0 + 8, 198, 244, 40, "nodes", BLUE[1], size=8)
child("nodes-note", "Text, chunks and vectors never leave the node. The node applies its policy to every item before it answers.",
      15, 276, 1090, 18, "nodes", YELLOW[1], italic=True)

# ── row 4: packs ────────────────────────────────────────────────────────────
container("packs", "Knowledge packs — neuralmesh_kb_pack/ (knowledge/packgen.py builds them)", 40, 980, 720, 150, BLUE)
child("p0", "19 subsidiary packs: datapoints, documents, concepts, skills, experts (pack.json, checked by the schema)", 15, 32, 690, 30, "packs", BLUE[1])
child("p1", "build/chroma per pack: generated, not in git", 15, 70, 220, 34, "packs", BLUE[1])
child("p2", "Canary strings prove no restricted text is indexed", 245, 70, 220, 34, "packs", BLUE[1])
child("p3", "Gated bodies released only with a grant", 475, 70, 230, 34, "packs", BLUE[1])
child("p4", "Group packs, loaded by the API at refresh: group.vocabulary (concepts, aliases), group.links (cross-company links), talent_import (roles, skills)", 15, 112, 690, 26, "packs", BLUE[1], italic=True)

container("dev", "Development stack — scripts/dev_stack.sh", 800, 980, 360, 150, GREY)
child("d0", "start · stop · status · restart-node · restart-api", 15, 32, 330, 30, "dev", GREY[1])
child("d1", "Checks: 90 tests, golden 10 of 10, live 24 of 24, browser 22 of 22", 15, 70, 330, 30, "dev", GREY[1])
child("d2", "Stand-in model and demo accounts only in APP_ENV=development", 15, 108, 330, 30, "dev", GREY[1], italic=True)

# ── edges ───────────────────────────────────────────────────────────────────
edge("e1", "sf", "gw", "MCP tools, service identity")
edge("e2", "gw", "api", "same runtime code", exit_="1,0.5", entry="0,0.3")
edge("e3", "ui", "api", "REST + bearer token", exit_="0,0.5", entry="1,0.2")
edge("e4", "api", "model", "", exit_="1,0.6", entry="0,0.5")
edge("e5", "api", "nodes", "MCP: search, summarize, find_experts, export_graph (user token minted per node)", exit_="0.5,1", entry="0.5,0")
edge("e6", "nodes", "packs", "each node loads its own packs at start", exit_="0.3,1", entry="0.5,0")
edge("e7", "nodes", "api", "export_graph → metadata only", exit_="0.8,0", entry="0.8,1", dashed=True)
edge("e9", "sf", "api", "", exit_="1,0.3", entry="0,0.08", dashed=True)

note("title", "RPG NeuralMesh — how it works (2026-11-06, commit after the Chroma switch)", 40, 8, 900, 24, size=14)
note("legend", "Grey: outside parties and tooling · Green: mesh API and gateway · Purple: screens · Orange: answer model · "
     "Yellow: company nodes · Red: policy · Blue: stores and packs · Dashed arrow: data loaded at start or refresh",
     40, 1150, 1120, 24, size=9)

xml = ('<mxfile host="app.diagrams.net" agent="neuralmesh_architecture_drawio.py" version="24.0.0">\n'
       '<diagram name="RPG NeuralMesh Architecture" id="neuralmesh-arch">\n'
       '<mxGraphModel dx="1700" dy="1260" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
       'page="1" pageScale="1" pageWidth="1700" pageHeight="1200" math="0" shadow="0">\n<root>\n'
       '<mxCell id="0" />\n<mxCell id="1" parent="0" />\n' + "\n".join(cells) +
       '\n</root>\n</mxGraphModel>\n</diagram>\n</mxfile>\n')
OUT.write_text(xml, encoding="utf-8")
print(f"wrote {OUT} with {len(cells)} cells")
