"""Write planning_docs/RPG_NeuralMesh_How_It_Works_Business.html, the business explanation of NeuralMesh.

The page borrows the stylesheet and the tab script of RPG_NeuralMesh_How_It_Works.html so both look the same.
Run:  python planning_docs/diagrams/how_it_works_business_html.py
"""
from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
SRC = DOCS / "RPG_NeuralMesh_How_It_Works.html"
OUT = DOCS / "RPG_NeuralMesh_How_It_Works_Business.html"

src = SRC.read_text(encoding="utf-8")
style = re.search(r"<style>.*?</style>", src, re.S).group(0)
script = re.search(r"<script>.*?</script>", src, re.S).group(0).replace("nm-how-tab", "nm-biz-tab")

AH = ('<defs><marker id="ah" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" class="ahead"/></marker>'
      '<marker id="aha" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" class="ahead-a"/></marker></defs>')


def svg_layers() -> str:
    return f'''<svg viewBox="0 0 1000 330" role="img" aria-label="Three layers: applications, the context graph, the company nodes">{AH}
<rect class="zone" x="20" y="20" width="960" height="80" rx="12"/><text class="t-z" x="34" y="40">APPLICATIONS</text>
<rect class="bx-a" x="60" y="48" width="260" height="40" rx="9"/><text class="t-b" x="76" y="73">SkillForge (talent)</text>
<rect class="bx-a" x="370" y="48" width="260" height="40" rx="9"/><text class="t-b" x="386" y="73">Snap and Score (inspection)</text>
<rect class="bx-a" x="680" y="48" width="260" height="40" rx="9"/><text class="t-b" x="696" y="73">Leadership view, next application</text>
<rect class="zone" x="20" y="125" width="960" height="90" rx="12"/><text class="t-z" x="34" y="145">THE CONTEXT GRAPH (the mesh)</text>
<rect class="bx-g" x="60" y="155" width="420" height="44" rx="9"/><text class="t-b" x="76" y="174">Knows what exists and who holds it</text><text class="t-s" x="76" y="191">names, links, owners, rules. No documents, no personal data</text>
<rect class="bx-g" x="520" y="155" width="420" height="44" rx="9"/><text class="t-b" x="536" y="174">Answers with evidence</text><text class="t-s" x="536" y="191">finds the right companies, collects what they release, checks the answer</text>
<rect class="zone" x="20" y="240" width="960" height="75" rx="12"/><text class="t-z" x="34" y="260">COMPANY NODES (the data owners)</text>
<rect class="bx-y" x="60" y="270" width="200" height="34" rx="9"/><text class="t-b" x="76" y="292">CEAT</text>
<rect class="bx-y" x="290" y="270" width="200" height="34" rx="9"/><text class="t-b" x="306" y="292">KEC International</text>
<rect class="bx-y" x="520" y="270" width="200" height="34" rx="9"/><text class="t-b" x="536" y="292">Harrisons Malayalam</text>
<rect class="bx-y" x="750" y="270" width="190" height="34" rx="9"/><text class="t-b" x="766" y="292">Zensar, Raychem, next</text>
<path class="ar-a" d="M190,88 L190,155"/><path class="ar-a" d="M500,88 L500,155"/><path class="ar-a" d="M810,88 L810,155"/>
<path class="ar" d="M160,199 L160,270"/><path class="ar" d="M390,199 L390,270"/><path class="ar" d="M620,199 L620,270"/><path class="ar" d="M845,199 L845,270"/>
</svg>'''


def svg_question() -> str:
    steps = [("1 Ask", "a question,", "with its purpose"), ("2 Find", "the topics", "it is about"), ("3 Route", "to the companies", "that hold them"),
             ("4 Owner decides", "what may leave,", "for this user"), ("5 Collect, check", "the evidence,", "no invention"), ("6 Answer", "with sources and", "what was held back")]
    out = [f'<svg viewBox="0 0 1000 150" role="img" aria-label="The journey of one question in six steps">{AH}']
    for i, (a, b, c) in enumerate(steps):
        x = 20 + i * 163
        out.append(f'<rect class="{"bx-r" if i == 3 else "bx"}" x="{x}" y="40" width="148" height="76" rx="10"/>'
                   f'<text class="t-b" x="{x + 10}" y="64">{a}</text><text class="t-s" x="{x + 10}" y="84">{b}</text>'
                   f'<text class="t-s" x="{x + 10}" y="101">{c}</text>')
        if i:
            out.append(f'<path class="ar-a" d="M{x - 15},78 L{x - 1},78"/>')
    out.append("</svg>")
    return "".join(out)


def svg_similar() -> str:
    return f'''<svg viewBox="0 0 1000 220" role="img" aria-label="One graph serves several applications and shows what is similar">{AH}
<circle cx="500" cy="110" r="34" class="bx-a"/><text class="t-b" x="500" y="106" text-anchor="middle">concept</text><text class="t-s" x="500" y="122" text-anchor="middle">"contamination"</text>
<rect class="bx-g" x="60" y="40" width="230" height="44" rx="9"/><text class="t-b" x="76" y="59">Talent</text><text class="t-s" x="76" y="76">skill: incoming quality control</text>
<rect class="bx-g" x="60" y="140" width="230" height="44" rx="9"/><text class="t-b" x="76" y="159">Knowledge</text><text class="t-s" x="76" y="176">CEAT storage learnings, Harrisons SOP</text>
<rect class="bx-g" x="710" y="40" width="230" height="44" rx="9"/><text class="t-b" x="726" y="59">Inspection</text><text class="t-s" x="726" y="76">condition: dirt and foreign matter</text>
<rect class="bx-g" x="710" y="140" width="230" height="44" rx="9"/><text class="t-b" x="726" y="159">People</text><text class="t-s" x="726" y="176">3 consented experts, names on approval</text>
<path class="ar" d="M290,62 L466,100"/><path class="ar" d="M290,162 L466,120"/><path class="ar" d="M710,62 L534,100"/><path class="ar" d="M710,162 L534,120"/>
<text class="t-s" x="500" y="200" text-anchor="middle">one shared node, so "similar" and "also see" work across applications</text>
</svg>'''


html = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NeuralMesh for the Business</title>
{style}
</head>
<body>
<div class="wrap">
<h1>NeuralMesh: what it does for the group</h1>
<p class="lead">Every RPG company knows things the others could use: how CEAT stores rubber, what KEC learned on an overseas project, how Harrisons spots latex going bad. NeuralMesh lets a person or an application in one company find and use that knowledge, while each company keeps full control of what leaves its walls.</p>

<div class="tabs" role="tablist">
  <button class="tab" role="tab" data-tab="problem" aria-selected="true">The problem it solves</button>
  <button class="tab" role="tab" data-tab="flow" aria-selected="false">How it works</button>
  <button class="tab" role="tab" data-tab="diagrams" aria-selected="false">Diagrams (3)</button>
  <button class="tab" role="tab" data-tab="arch" aria-selected="false">Architecture</button>
  <button class="tab" role="tab" data-tab="helps" aria-selected="false">How it helps</button>
  <button class="tab" role="tab" data-tab="rules" aria-selected="false">The rules it keeps</button>
  <button class="tab" role="tab" data-tab="apps" aria-selected="false">Bringing an application in</button>
</div>

<!-- ───────────── Problem ───────────── -->
<section class="panel on" id="problem">
<div class="facts">
  <div class="fact"><b>1</b><span>place to ask a question that spans the group companies</span></div>
  <div class="fact"><b>0</b><span>documents copied out of a company. The mesh holds names, links and owners only</span></div>
  <div class="fact"><b>Every</b><span>answer carries its sources, and says what was held back and why</span></div>
  <div class="fact"><b>Any</b><span>application can use it: talent, inspection, leadership views, the next one</span></div>
</div>
<h2>Today</h2>
<p class="sub">What happens without a shared context graph.</p>
<div class="tablebox"><table>
<tr><th>Situation</th><th>What happens today</th><th>Cost</th></tr>
<tr><td>A Harrisons estate manager wants to cut latex spoilage</td><td>Does not know that CEAT trends lot quality per supplier at receipt and has written it down</td><td>The same lesson is learned twice, months apart</td></tr>
<tr><td>A learner in SkillForge needs study material for quality management</td><td>Material lives in four companies in four formats, and nobody can say which is current</td><td>Learning plans built on what one person happened to know</td></tr>
<tr><td>An inspector in Snap and Score grades a tyre bulge</td><td>No link to the standard it is graded against, to similar defects elsewhere, or to whether the asset is insured</td><td>Grades differ by inspector, claims are slow</td></tr>
<tr><td>Group leadership asks "who in the group knows acquisition integration"</td><td>An email round, answers in days, names shared without consent</td><td>Decisions wait, privacy rules are bent</td></tr>
<tr><td>Each application builds its own knowledge base</td><td>SkillForge, Snap and Score and the next one each copy data and each invent a vocabulary</td><td>Three copies of the same facts, drifting apart, each with its own access rules</td></tr>
<tr><td>A company shares a document once</td><td>It is copied, forwarded and never retired. The company loses control of it</td><td>Companies stop sharing</td></tr>
</table></div>
<h2 class="gap">What NeuralMesh changes</h2>
<div class="two">
  <div class="card"><h3>One graph, many users</h3><ul><li>One map of what exists in the group: topics, skills, roles, assets, standards, documents and who owns each.</li><li>Every application reads the same map, so a skill in SkillForge and a defect in Snap and Score can point at the same topic.</li><li>A new application adds its own vocabulary to the map instead of building a new store.</li></ul></div>
  <div class="card"><h3>Control stays with the owner</h3><ul><li>Documents, records and personal data stay inside each company's own node.</li><li>Each company states, per catalogue item, what may leave: a title only, a summary, the text, or a live lookup.</li><li>A link between two companies is shown only after both companies approve it.</li><li>Anything shared can be retired later, and the mesh forgets it.</li></ul></div>
</div>
</section>

<!-- ───────────── How it works ───────────── -->
<section class="panel" id="flow">
<div class="layout">
<div>
<h2>In one line</h2>
<p class="sub">A question goes to the companies that hold an answer, each company decides what may leave for this person and this purpose, and the mesh returns an answer built only from what came back, with its sources.</p>
<ol class="steps">
<li class="step"><div class="snum">1</div><div><h3>Each company publishes a catalogue, not its documents</h3><p>A company lists what it holds in named catalogue items (for example "materials handling learnings", "expert directory", "inspection records") and sets a rule for each: title only, summary, full text, or looked up live. The documents stay on the company's own node.</p><div class="ex"><span>Example</span>CEAT lists "approved materials handling and storage learnings" as summary-only for problem solving, and "compound formulations" as title-only, never the content.</div></div></li>
<li class="step"><div class="snum">2</div><div><h3>The mesh keeps a map of names and links</h3><p>From every catalogue the mesh builds one graph: topics with their other names, skills, roles, assets, standards, document titles, and the links between them. It holds no document text and no person's name.</p><div class="ex"><span>Example</span>The topic "latex pre-coagulation" is linked to two Harrisons documents, one CEAT storage learning, and the skill "quality management".</div></div></li>
<li class="step"><div class="snum">3</div><div><h3>A person or an application asks, with a purpose</h3><p>The question comes with who is asking and why: problem solving, learning, career mobility, inspection. The purpose matters, because a company may allow a summary for learning and nothing for a commercial question.</p><div class="ex"><span>Example</span>A SkillForge learner asks for material on quality management at level M. Purpose: learning.</div></div></li>
<li class="step"><div class="snum">4</div><div><h3>The mesh finds the topics and the right companies</h3><p>The question is matched to topics by name, by other names, and by meaning when the wording differs. The map says which companies hold something on those topics. The question goes only there.</p><div class="ex"><span>Example</span>"Latex going bad before it reaches the factory" matches "latex pre-coagulation" by meaning and routes to Harrisons, CEAT and KEC. It is not sent to Zensar.</div></div></li>
<li class="step"><div class="snum">5</div><div><h3>Each company decides what leaves</h3><p>The company's node applies its own rules to each item, for this person and this purpose, and returns what it allows. A held-back item comes back as a title with the reason, so the asker knows it exists and can request access.</p><div class="ex"><span>Example</span>CEAT returns the storage learnings as summaries, and returns "compound formulations" as a title with "held back: formulation data never leaves CEAT".</div></div></li>
<li class="step"><div class="snum">6</div><div><h3>The answer is built from the evidence only, and checked</h3><p>The returned items are fitted into a fixed space, the most relevant first. An assistant writes the answer from those items alone. Seven checks run on the result: no invented sources, no content from a held-back item, no leaked test strings, nothing longer than the evidence supports.</p><div class="ex"><span>Example</span>The Harrisons manager gets three practices with their sources, two titles that were held back, and a note that KEC was reached and had nothing on the topic.</div></div></li>
<li class="step"><div class="snum">7</div><div><h3>Related and similar things are shown</h3><p>Because every application uses the same map, the answer can show what is near: skills that go with this one, similar defects in another company, documents that corroborate or contradict each other, people who know the topic (without names until an introduction is approved).</p><div class="ex"><span>Example</span>Beside the tyre bulge, Snap and Score shows the grade scale it is judged on, two similar conditions in KEC's cable reels, and the reference images CEAT allows.</div></div></li>
<li class="step"><div class="snum">8</div><div><h3>Everything is recorded, and anything can be withdrawn</h3><p>Each decision, lookup and answer is written to an audit with one trace number. A company can change a rule or retire an item, and the next question respects it. Nothing shared is ever copied out of the mesh's control.</p><div class="ex"><span>Example</span>CEAT retires an outdated learning. From the next refresh it is marked superseded, and answers point to the newer version.</div></div></li>
</ol>
</div>
<aside class="side">
<div class="card"><h3>Three kinds of answer</h3><ul><li><b>A fact with sources</b>, for example which practices cut spoilage.</li><li><b>A profile</b>, for example a role with its required skills, or an asset with its conditions, grade scale and standards.</li><li><b>A live value</b>, for example whether an asset is insured right now, looked up at the owning company and never stored.</li></ul></div>
<div class="card"><h3>What the mesh never does</h3><ul><li>Copy a document out of a company.</li><li>Show a person's name without consent and an approved introduction.</li><li>Answer from anything the companies did not release.</li><li>Show a link between two companies that one of them has not approved.</li><li>Delete history. Things are retired and stay in the record.</li></ul></div>
<div class="card"><h3>Words used here</h3><p><b>Node:</b> a company's own server that holds its knowledge and applies its rules.</p><p><b>Catalogue item:</b> a named set of documents or records with one sharing rule.</p><p><b>Topic:</b> a named idea with its other names, shared across the group.</p><p><b>Evidence:</b> one item a company released, with its source and the rule that allowed it.</p></div>
</aside>
</div>
</section>

<!-- ───────────── Diagrams ───────────── -->
<section class="panel" id="diagrams">
<h2>Three layers</h2>
<p class="sub">Applications ask. The mesh knows where to ask and answers with evidence. The companies hold the data and decide.</p>
<div class="dgm">{svg_layers()}</div>
<p class="dgm-cap">The arrows from the mesh to the companies carry the question and the asker's identity. The arrows back carry only what each company released.</p>
<h2 class="gap">The journey of one question</h2>
<div class="dgm">{svg_question()}</div>
<p class="dgm-cap">Step 4 is the one that keeps control with the owner. It runs inside each company, on the company's own rules.</p>
<h2 class="gap">One shared topic serves every application</h2>
<div class="dgm">{svg_similar()}</div>
<p class="dgm-cap">A topic sits once in the map. Talent, knowledge, inspection and people all link to it, which is what makes "similar" and "also see" possible across applications.</p>
</section>

<!-- ───────────── Architecture ───────────── -->
<section class="panel" id="arch">
<h2>The architecture, end to end</h2>
<p class="sub">Applications on top ask through one context API. The core in the middle holds the map, the rules and the audit. The company nodes at the bottom hold the data and decide. The standards column lists what every part follows.</p>
<div class="dgm" style="padding:8px"><img src="diagrams/RPG_NeuralMesh_Context_Graph_Architecture.png" alt="NeuralMesh architecture: applications, context API, context graph core, subsidiary nodes, sources and the standards" style="display:block;width:100%;height:auto;border-radius:8px"></div>
<p class="dgm-cap">Purple: applications. Green: the context API and the core. Orange: intake of vocabularies and data. Blue: the graph store and its layers. Red: policy, evidence and audit. Yellow: the company nodes. Grey: the standards and the sources behind each node. A dashed arrow is data or rules flowing in.</p>
<div class="two">
  <div class="card"><h3>Reading it top to bottom</h3><ul><li>An application calls one of the eight tools with its own identity and the user's identity.</li><li>The core resolves the question, routes it, applies the policy gate and builds the answer bundle.</li><li>The company nodes search their own data, apply their rules and return evidence records. Their text, vectors, records and live values never move.</li></ul></div>
  <div class="card"><h3>Reading it left to right</h3><ul><li>Intake brings vocabularies and data in through adapters, checks and one normalised file.</li><li>The ontology registry holds the core vocabulary and one file per application domain.</li><li>The graph store keeps one layer per domain plus the similarity layer and the live pointers.</li><li>The policy gate, evidence records and audit sit on every path out.</li></ul></div>
</div>
</section>

<!-- ───────────── How it helps ───────────── -->
<section class="panel" id="helps">
<h2>For each group of people</h2>
<p class="sub">What changes in their day.</p>
<div class="tablebox"><table>
<tr><th>Who</th><th>Before</th><th>With NeuralMesh</th></tr>
<tr><td>An employee with a problem</td><td>Asks around, finds what one colleague remembers</td><td>Asks once, gets the practices the group has written down, with sources and with the items that exist but are held back</td></tr>
<tr><td>A learner in SkillForge</td><td>Study material chosen by hand, often outdated</td><td>Material matched to the skill and the level, from the company that owns it, current version only, read by reference so nothing is copied</td></tr>
<tr><td>An inspector in Snap and Score</td><td>Grades from memory, no view of standards or similar cases</td><td>The asset's conditions, grade scale and standards in one profile, similar defects elsewhere, insurance status looked up live</td></tr>
<tr><td>A subsidiary head</td><td>Sharing means losing control, so sharing stops</td><td>Shares by rule, per catalogue item, per purpose, sees every access in the audit, can withdraw at any time</td></tr>
<tr><td>Group leadership</td><td>Cross-company knowledge found by email rounds</td><td>Questions across the group answered in seconds with evidence, experts found by skill without exposing names, gaps between companies visible as links one company can fill for another</td></tr>
<tr><td>An application team</td><td>Builds and maintains its own knowledge store and access rules</td><td>Adds its vocabulary to the map, calls seven standard tools, inherits every sharing rule on day one</td></tr>
<tr><td>IT security and compliance</td><td>Copies of documents in several systems, access rules in each</td><td>Data stays at the owner, one rule per catalogue item, one audit line per decision, consent recorded for anything about a person</td></tr>
</table></div>
<h2 class="gap">What the group gains</h2>
<div class="two">
  <div class="card"><h3>Knowledge used more than once</h3><ul><li>A lesson learned in one company reaches the others the day it is published.</li><li>Gaps become visible: the map shows where one company has a practice another company states it lacks.</li><li>Conflicts become visible: two documents that disagree are linked, so both are read before a decision.</li></ul></div>
  <div class="card"><h3>Trust that holds up</h3><ul><li>Every answer can show "why am I seeing this" for every item.</li><li>No answer is built from something a company did not release.</li><li>Owners see who asked for what and can change the rule tomorrow.</li></ul></div>
  <div class="card"><h3>One platform instead of many</h3><ul><li>Talent, inspection and the next application share one map and one set of tools.</li><li>Similar skills, similar defects and related standards come from the same links.</li><li>Adding a company is adding a node. Adding an application is adding a vocabulary.</li></ul></div>
  <div class="card"><h3>Honest limits</h3><ul><li>The mesh is as good as the catalogues the companies publish. An item not published cannot be found.</li><li>Routing by meaning works for topics the map knows. A question on a topic no company has listed goes to a chosen company, or returns nothing.</li><li>The answer text is written by an assistant from the evidence. The evidence is checked, the wording is not a company's statement.</li></ul></div>
</div>
</section>

<!-- ───────────── Rules ───────────── -->
<section class="panel" id="rules">
<h2>The rules the mesh keeps, in plain words</h2>
<p class="sub">These rules do not change when an application changes. They are what the companies agree to.</p>
<div class="tablebox"><table>
<tr><th>Rule</th><th>Plain meaning</th><th>Who it protects</th></tr>
<tr><td>Data stays with its owner</td><td>Documents, records, vectors and personal data stay inside the company's node. The mesh holds names, links and owners</td><td>The subsidiary</td></tr>
<tr><td>One sharing rule per catalogue item</td><td>Title only, summary, full text, or live lookup. Plus the purposes it is allowed for and a ceiling that no request can pass</td><td>The subsidiary</td></tr>
<tr><td>The purpose is part of every question</td><td>Problem solving, learning, career mobility, inspection. The same item can be open for one and closed for another</td><td>The subsidiary, the asker</td></tr>
<tr><td>Held-back items are visible as titles</td><td>The asker learns that something exists and why it is held back, and can request access from the owner</td><td>The asker</td></tr>
<tr><td>Links between companies need both owners</td><td>A link that says "CEAT's practice fills Harrisons' gap" is shown only after both companies approve it</td><td>Both subsidiaries</td></tr>
<tr><td>Computed is marked computed</td><td>A similarity the system worked out is shown as such, with its reason, and is never shown as a fact a person approved</td><td>The asker</td></tr>
<tr><td>Nothing about a person without consent</td><td>Experts appear by role and skill. A name is released only after the owning company approves an introduction</td><td>The person</td></tr>
<tr><td>Live facts are never stored</td><td>Insurance status, stock, location: the mesh holds a pointer and asks the owner at the moment of the question</td><td>The subsidiary</td></tr>
<tr><td>Every item carries its evidence</td><td>Source, owner, the rule that allowed it, the time. An answer can always show where each line came from</td><td>Everyone</td></tr>
<tr><td>Retire, never delete</td><td>A withdrawn item stops appearing but stays in the record, so an audit can always say what the mesh held and when</td><td>Compliance</td></tr>
<tr><td>One audit line per decision</td><td>Who asked, for what, what each company decided, what the assistant was given, with one trace number through all of it</td><td>Compliance, the subsidiary</td></tr>
<tr><td>Versions are explicit</td><td>Vocabularies and catalogues carry a version and a date. An older document is marked superseded by the newer one</td><td>Everyone</td></tr>
</table></div>
</section>

<!-- ───────────── Applications ───────────── -->
<section class="panel" id="apps">
<h2>How an application joins</h2>
<p class="sub">Three steps, the same for talent, inspection or a leadership view.</p>
<ol class="steps">
<li class="step"><div class="snum b">1</div><div><h3>Describe its vocabulary</h3><p>The application states the kinds of thing it talks about and how they relate. For inspection: assets, conditions, grade scales, cover types, and relations such as "asset is checked for condition". For talent: roles, skills, levels, and "role requires skill". Where a kind already exists in the map (a topic, a document, a company), the application uses it instead of inventing its own.</p></div></li>
<li class="step"><div class="snum b">2</div><div><h3>Send its data through the same door</h3><p>Lists of assets, roles or standards arrive as files, are checked against the vocabulary, and are loaded into the map under the application's own name. Items the companies have not yet confirmed enter as proposed and are approved by each company.</p></div></li>
<li class="step"><div class="snum b">3</div><div><h3>Ask with the standard tools</h3><p>Seven tools cover every application: what is this thing, what is connected to it, what is similar, answer a question, which documents and images, which experts, look this up live. The application brings its own screens. It never brings its own copy of another company's data.</p></div></li>
</ol>
<h2 class="gap">Three applications, one mesh</h2>
<div class="tablebox"><table>
<tr><th>Application</th><th>Its vocabulary</th><th>What it asks the mesh</th><th>What it gets back</th></tr>
<tr><td>SkillForge (talent)</td><td>Roles, skills, levels, study material, mentors</td><td>What does this role need, what material explains this skill at this level, who can mentor it, which skills are similar</td><td>Required skills with the topics behind them, current material by reference, consented experts without names, similar skills with the reason</td></tr>
<tr><td>Snap and Score (inspection)</td><td>Assets, conditions, grade scales, cover types, standards, inspections</td><td>What is this asset and how is it inspected, what standard applies, is it insured now, what similar defects exist elsewhere, what did past inspections find</td><td>The asset's profile, the standard documents the owner releases, the live cover status with its time, similar conditions with the reason, history the owner allows</td></tr>
<tr><td>A leadership view</td><td>Few new kinds. It reads what exists, with the purpose "leadership" and an aggregate rule at each company</td><td>Where does the group hold knowledge on a topic, which companies have a practice another lacks, who in the group can speak to it</td><td>Counts and titles per company, approved gap links, experts by role, nothing below the aggregate rule each company set</td></tr>
</table></div>
<div class="note"><b>Still to be confirmed.</b> The inspection vocabulary received on 2026-11-06 is a first draft. Its assets, conditions and cover types are marked as to be confirmed by each company, and Raychem RPG is named in it but is not yet a node.</div>
</section>

</div>
{script}
</body>
</html>
'''
OUT.write_text(html, encoding="utf-8")
body = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", html, flags=re.S)
text = re.sub(r"<[^>]+>", " ", body)
print(f"wrote {OUT.name}, semicolons in text: {text.count(';')}")
