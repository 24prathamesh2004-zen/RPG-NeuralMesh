#!/usr/bin/env python3
"""Build the mock knowledge-base pack for the RPG NeuralMesh MCP nodes.

kb/<node>.yaml  ->  data_pack/<node>/{source,gated,index.db,policy.yaml,experts.yaml,node.yaml,*.db}
All content is SYNTHETIC. Run:  python kbgen.py   (needs PyYAML; everything else is stdlib)
"""
import hashlib, json, random, re, shutil, sqlite3, sys
from pathlib import Path
from string import Template
import yaml

ROOT = Path(__file__).parent
KB, OUT = ROOT / "kb", ROOT / "data_pack"
sys.path.insert(0, str(ROOT.parent))
from shared.registry import node_ids  # noqa: E402

NODES = list(node_ids())
SCHEMA = "1.0.0"


def months(n=36, y=2023, m=11):
    out = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


# ---------- mock structured data ----------
def gen_harrisons(db):
    rnd = random.Random(42)
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE estate_month(estate_id TEXT, month TEXT, collected_kg REAL, rainfall_mm REAL, transport_hours REAL,
      spoil_precoag_kg REAL, spoil_contam_kg REAL, spoil_delay_kg REAL, spoil_temp_kg REAL, workers INTEGER);""")
    rain = {1: 20, 2: 25, 3: 60, 4: 130, 5: 260, 6: 620, 7: 700, 8: 520, 9: 340, 10: 290, 11: 150, 12: 50}
    season = {1: .9, 2: .7, 3: .6, 4: .75, 5: .95, 6: 1.1, 7: 1.15, 8: 1.1, 9: 1.05, 10: 1.0, 11: 1.0, 12: .95}
    est = [f"EST-{i:02d}" for i in range(1, 13)]
    base = {e: rnd.uniform(18000, 42000) for e in est}
    hrs = {e: rnd.uniform(1.2, 4.6) for e in est}
    for mo in months():
        m = int(mo[5:])
        for e in est:
            r = max(0, rain[m] * rnd.uniform(.7, 1.3))
            col = base[e] * season[m] * rnd.uniform(.9, 1.1)
            tr = hrs[e] * (1.2 if r > 400 else 1.0) * rnd.uniform(.95, 1.05)
            pre = col * (0.010 + 0.000045 * r + 0.0035 * max(0, tr - 2.5)) * rnd.uniform(.9, 1.1)
            dly = col * 0.0035 * max(0, tr - 1.5) * rnd.uniform(.9, 1.1)
            tmp = col * (0.011 if m in (3, 4, 5) else 0.003) * rnd.uniform(.9, 1.1)
            con_ = col * 0.008 * rnd.uniform(.85, 1.15)
            con.execute("INSERT INTO estate_month VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (e, mo, round(col), round(r), round(tr, 2), round(pre), round(con_), round(dly), round(tmp), rnd.randint(40, 120)))
    causes = [("pre-coagulation", "spoil_precoag_kg"), ("contamination", "spoil_contam_kg"),
              ("delay", "spoil_delay_kg"), ("temperature", "spoil_temp_kg")]
    union = " UNION ALL ".join(
        f"SELECT month,'{c}' AS cause, ROUND(100.0*SUM({col})/SUM(collected_kg),2) AS spoil_pct, COUNT(DISTINCT estate_id) AS n_estates "
        f"FROM estate_month GROUP BY month HAVING COUNT(DISTINCT estate_id)>=3" for c, col in causes)
    band = ("CASE WHEN transport_hours<2.5 THEN 'under_2.5h' WHEN transport_hours<3.5 THEN '2.5_to_3.5h' ELSE 'over_3.5h' END")
    con.executescript(f"""
    CREATE VIEW v_spoilage_by_month AS {union};
    CREATE VIEW v_spoilage_by_band AS SELECT month, {band} AS band,
      ROUND(100.0*SUM(spoil_precoag_kg+spoil_contam_kg+spoil_delay_kg+spoil_temp_kg)/SUM(collected_kg),2) AS spoil_pct,
      COUNT(DISTINCT estate_id) AS n_estates FROM estate_month GROUP BY month, {band} HAVING COUNT(DISTINCT estate_id)>=3;""")
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    def share(mset):
        ph = ",".join("?" * len(mset))
        pre, tot = q(f"SELECT SUM(spoil_precoag_kg), SUM(spoil_precoag_kg+spoil_contam_kg+spoil_delay_kg+spoil_temp_kg) "
                     f"FROM estate_month WHERE CAST(substr(month,6,2) AS INT) IN ({ph})", *mset)[0]
        return round(100 * pre / tot)
    def bandpct(cond):
        a, c = q(f"SELECT SUM(spoil_precoag_kg+spoil_contam_kg+spoil_delay_kg+spoil_temp_kg), SUM(collected_kg) FROM estate_month WHERE {cond}")[0]
        return round(100 * a / c, 1)
    contam = [r[0] for r in q("SELECT 100.0*SUM(spoil_contam_kg)/SUM(collected_kg) FROM estate_month GROUP BY month")]
    tp = q("SELECT 100.0*SUM(spoil_temp_kg)/SUM(collected_kg) FROM estate_month WHERE CAST(substr(month,6,2) AS INT) IN (3,4,5)")[0][0]
    seasons = {"monsoon": (6, 7, 8), "winter": (12, 1, 2), "summer": (3, 4, 5)}
    largest = {}
    for s, ms in seasons.items():
        ph = ",".join("?" * len(ms))
        row = q(f"SELECT SUM(spoil_precoag_kg),SUM(spoil_contam_kg),SUM(spoil_delay_kg),SUM(spoil_temp_kg) FROM estate_month "
                f"WHERE CAST(substr(month,6,2) AS INT) IN ({ph})", *ms)[0]
        largest[s] = ["pre-coagulation", "contamination", "delay", "temperature"][row.index(max(row))]
    suppressed = 0
    for mo in months():
        for lo, hi in ((0, 2.5), (2.5, 3.5), (3.5, 99)):
            n = q("SELECT COUNT(DISTINCT estate_id) FROM estate_month WHERE month=? AND transport_hours>=? AND transport_hours<?", mo, lo, hi)[0][0]
            suppressed += 1 if 0 < n < 3 else 0
    stats = dict(MON_PRECOAG=share((6, 7, 8)), WIN_PRECOAG=share((12, 1, 2)),
                 BAND_LOW=bandpct("transport_hours<2.5"), BAND_HIGH=bandpct("transport_hours>=3.5"),
                 CONTAM_MIN=round(min(contam), 2), CONTAM_MAX=round(max(contam), 2), TEMP_PEAK=round(tp, 1),
                 _largest=largest, _suppressed_cells=suppressed)
    con.commit(); con.close()
    return stats


def gen_ceat(db):
    rnd = random.Random(7)
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE failure_reports(id TEXT, plant TEXT, report_date TEXT, defect_code TEXT, severity TEXT, root_cause_category TEXT, summary TEXT);
    CREATE TABLE maintenance_log(id TEXT, plant TEXT, equipment TEXT, failure_mode TEXT, downtime_hours REAL, cause TEXT);""")
    cats = ["material-handling"] * 28 + ["process-drift"] * 30 + ["equipment"] * 20 + ["supplier-material"] * 12 + ["operator"] * 10
    defects = ["BLISTER", "VOID", "TREAD-SEP", "BEAD-UNSEAT", "SCORCH", "MIX-VARIATION"]
    n_mh = 0
    for i in range(60):
        c = cats[rnd.randrange(100)]
        n_mh += c == "material-handling"
        con.execute("INSERT INTO failure_reports VALUES (?,?,?,?,?,?,?)",
                    (f"FR-{i+1:03d}", f"PL-{rnd.randint(1,6)}", f"2026-{rnd.randint(1,10):02d}-{rnd.randint(1,28):02d}",
                     rnd.choice(defects), rnd.choice(["low", "medium", "high"]), c, f"Mock failure report ({c}). Synthetic."))
    for i in range(80):
        con.execute("INSERT INTO maintenance_log VALUES (?,?,?,?,?,?)",
                    (f"ML-{i+1:03d}", f"PL-{rnd.randint(1,6)}", rnd.choice(["mixer", "curing press", "extruder", "calender"]),
                     rnd.choice(["bearing wear", "steam trap", "sensor drift", "seal leak"]), round(rnd.uniform(.5, 16), 1), "mock"))
    con.executescript("""CREATE VIEW v_failure_by_cause AS SELECT root_cause_category, COUNT(*) AS n_reports,
      ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM failure_reports),1) AS share_pct FROM failure_reports
      GROUP BY root_cause_category HAVING COUNT(*)>=3;""")
    con.commit(); con.close()
    return dict(MH_SHARE=round(100 * n_mh / 60))


def gen_kec(db):
    rnd = random.Random(11)
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE projects(id TEXT, type TEXT, region TEXT, status TEXT, start_year INT);
    CREATE TABLE delay_notes(id TEXT, project_id TEXT, category TEXT, note TEXT);
    CREATE TABLE esg_metrics(plant_label TEXT, year INT, water_recycled_pct REAL, water_kl_per_tonne REAL, energy_gj_per_tonne REAL);""")
    for pl in range(1, 6):
        for yr in range(2023, 2027):
            con.execute("INSERT INTO esg_metrics VALUES (?,?,?,?,?)", (f"KP-{pl}", yr, round(rnd.uniform(55, 85) + (yr - 2023) * 2, 1),
                        round(rnd.uniform(1.8, 3.2) - (yr - 2023) * 0.1, 2), round(rnd.uniform(4.0, 6.5), 2)))
    for i in range(30):
        con.execute("INSERT INTO projects VALUES (?,?,?,?,?)", (f"PRJ-{i+1:03d}", rnd.choice(["transmission", "railway", "civil", "water"]),
                    rnd.choice(["India-West", "India-East", "Middle East", "Americas", "Africa"]), rnd.choice(["running", "closed"]), rnd.randint(2021, 2026)))
    cats = (["material-supply"] * 24 + ["right-of-way"] * 20 + ["labour"] * 16 + ["weather"] * 12 + ["design-change"] * 10 + ["payment-cycle"] * 10 + ["customs"] * 8)
    cnt = {}
    for i in range(90):
        c = rnd.choice(cats); cnt[c] = cnt.get(c, 0) + 1
        con.execute("INSERT INTO delay_notes VALUES (?,?,?,?)", (f"DN-{i+1:03d}", f"PRJ-{rnd.randint(1,30):03d}", c, f"Mock delay note ({c}). Synthetic."))
    con.executescript("""CREATE VIEW v_delay_by_category AS SELECT category, COUNT(*) AS n_notes,
      ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM delay_notes),1) AS share_pct FROM delay_notes GROUP BY category HAVING COUNT(*)>=3;
    CREATE VIEW v_esg_summary AS SELECT year, ROUND(AVG(water_recycled_pct),1) AS avg_water_recycled_pct,
      ROUND(AVG(water_kl_per_tonne),2) AS avg_water_kl_per_tonne, ROUND(AVG(energy_gj_per_tonne),2) AS avg_energy_gj_per_tonne,
      COUNT(DISTINCT plant_label) AS n_plants FROM esg_metrics GROUP BY year HAVING COUNT(DISTINCT plant_label)>=3;""")
    con.commit(); con.close()
    ranked = sorted(cnt.items(), key=lambda kv: -kv[1])
    return dict(TOP_CAT=ranked[0][0], TOP_SHARE=round(100 * ranked[0][1] / 90), SECOND_CAT=ranked[1][0])


GEN = {"ceat": ("qms.db", gen_ceat), "kec": ("projects.db", gen_kec), "harrisons": ("estate_mis.db", gen_harrisons), "zensar": (None, None)}


# ---------- pack building ----------
def fill(text, stats):
    return " ".join(Template(text).safe_substitute({k: v for k, v in stats.items() if not k.startswith("_")}).split())


def chunks(body, size=600):
    out = []
    for para in [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]:
        para = " ".join(para.split())
        while len(para) > size:
            cut = para.rfind(". ", 0, size) + 1 or size
            out.append(para[:cut].strip()); para = para[cut:].strip()
        out.append(para)
    return out


def build_node(name):
    cfg = yaml.safe_load((KB / f"{name}.yaml").read_text())
    d = OUT / name
    for sub in ("source", "gated"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    dbname, fn = GEN.get(name, (None, None))
    stats = fn(d / dbname) if fn else {}
    idx = sqlite3.connect(d / "index.db")
    # porter stemming, so that "failures" finds "failure reports" and "delays" finds "delay notes"
    idx.execute("CREATE VIRTUAL TABLE idx USING fts5(text, title, tags, doc_id UNINDEXED, dp UNINDEXED, mode UNINDEXED, sens UNINDEXED, version UNINDEXED, stale UNINDEXED, tokenize='porter unicode61')")
    n_idx = 0
    for doc in cfg["docs"]:
        dp = cfg["datapoints"][doc["dp"]]
        ceil, summary = dp["ceiling"], fill(doc["summary"], stats)
        body = doc.get("body") or doc.get("private_body") or "[mock full source document; not exposed beyond the approved summary]"
        body = fill(body, stats) if "$" in body else body
        fm = {"id": f"{name}:{doc['id']}", "datapoint_id": doc["dp"], "company": name, "title": doc["title"], "sensitivity": dp["sensitivity"],
              "ceiling": ceil, "owner_role": dp["owner_role"], "version": doc.get("version", "2026-01"), "tags": doc["tags"],
              "approved_summary": summary, "synthetic": True}
        text = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n" + body + "\n"
        gated = bool(dp.get("requires_approval")) or dp.get("upgrade_with_approval") is not None
        (d / ("gated" if gated else "source") / f"{doc['id']}.md").write_text(text)
        if gated:
            (d / "source" / f"{doc['id']}.md").write_text("---\n" + yaml.safe_dump({**fm, "note": "body held in gated store"}, sort_keys=False) + "---\n")
        rows = []
        if dp.get("requires_approval") or ceil == "MD":
            rows, mode = [(f"{doc['title']} {summary if gated else ''}".strip(), doc["id"])], "MD"
        elif ceil == "SUM":
            rows, mode = [(summary, doc["id"])], "SUM"
        elif ceil == "RAG":
            rows, mode = [(c, f"{doc['id']}#{i}") for i, c in enumerate(chunks(body))], "RAG"
        else:
            rows, mode = [], "LIVE"
        for t, did in rows:
            idx.execute("INSERT INTO idx VALUES (?,?,?,?,?,?,?,?,?)",
                        (t, doc["title"], " ".join(doc["tags"]), f"{name}:{did}", doc["dp"], mode, dp["sensitivity"], fm["version"], int(int(fm["version"][:4]) < 2021)))
            n_idx += 1
    for dpid, dpc in cfg["datapoints"].items():
        if dpc["ceiling"] == "LIVE" and dpc.get("views"):
            idx.execute("INSERT INTO idx VALUES (?,?,?,?,?,?,?,?,?)", (dpc["title"] + " live aggregate", dpc["title"], " ".join(dpc.get("tags", [])),
                        f"{name}:{dpid}:live", dpid, "LIVE", dpc["sensitivity"], "live", 0))
            n_idx += 1
    idx.commit(); idx.close()
    # experts (public fields vs private reveal)
    experts = [{"id": e["id"], "role": e["role"], "skills": e["skills"], "evidence": [f"{name}:{x}" for x in e["evidence"]],
                "consent": e["consent"], "private": {"name": e["private_name"]}} for e in cfg["experts"]]
    (d / "experts.yaml").write_text(yaml.safe_dump(experts, sort_keys=False))
    pol = {"node": name, "schema_version": SCHEMA, "calendar": "results_calendar.yaml",
           "defaults": {"purposes_allowed": ["problem_solving", "compliance", "bid_support", "learning", "career_mobility", "inspection"], "roles_allowed": ["group_user"]},
           "datapoints": cfg["datapoints"]}
    (d / "policy.yaml").write_text(yaml.safe_dump(pol, sort_keys=False))
    (d / "results_calendar.yaml").write_text(yaml.safe_dump({"windows": [{"start": "2026-10-15", "end": "2026-11-14", "reason": "Q2 results window (mock)"}]}))
    (d / "node.yaml").write_text(yaml.safe_dump({"node_id": name, "display": cfg["display"], "port": cfg["port"], "level": cfg["level"],
                                                  "schema_version": SCHEMA, "structured_db": dbname, "backend": cfg["backend"]}, sort_keys=False))
    facts = [{"node": name, "id": f["id"], "dp": f["dp"], "text": fill(f["text"], stats)} for f in cfg["facts"]]
    return cfg, stats, facts, n_idx


def validate(results):
    errs, rows = [], []
    for name, (cfg, stats, facts, n_idx) in results.items():
        d = OUT / name
        dump = sqlite3.connect(d / "index.db").execute("SELECT group_concat(text||' '||title||' '||tags,' ') FROM idx").fetchone()[0] or ""
        public = dump + (d / "policy.yaml").read_text() + yaml.safe_dump([{k: v for k, v in e.items() if k != "private"} for e in yaml.safe_load((d / "experts.yaml").read_text())])
        stored = "".join(p.read_text() for p in (d / "source").glob("*.md")) + "".join(p.read_text() for p in (d / "gated").glob("*.md"))
        for c in cfg["canaries"]:
            if c in public: errs.append(f"{name}: canary {c} leaked into index/policy/experts")
            if c not in stored: errs.append(f"{name}: canary {c} not planted in source/gated")
        for doc in cfg["docs"]:
            if doc["dp"] not in cfg["datapoints"]: errs.append(f"{name}: doc {doc['id']} has unknown datapoint")
        for f in cfg["facts"]:
            if f["dp"] not in cfg["datapoints"]: errs.append(f"{name}: fact {f['id']} has unknown datapoint")
        if cfg["experts"] and not any(not e["consent"] for e in cfg["experts"]): errs.append(f"{name}: needs at least one opted-out expert")
        if re.search(r"[\w.]+@[\w.]+\.\w+|(?<![\w-])\+?\d[\d -]{8,}\d(?![\w-])", public): errs.append(f"{name}: looks like contact data in public files")
        if "$" in "".join(f["text"] for f in facts): errs.append(f"{name}: unresolved placeholder in facts")
        dbname = GEN.get(name, (None, None))[0]
        for dpid, dpc in cfg["datapoints"].items():
            for v in dpc.get("views", []):
                con_ = sqlite3.connect(d / dbname)
                try:
                    cols = [c[1] for c in con_.execute(f"PRAGMA table_info({v})")]
                    ncol = next((c for c in cols if c.startswith("n_")), None)
                    if not ncol: errs.append(f"{name}: view {v} has no n_* group-size column"); continue
                    mn = con_.execute(f"SELECT MIN({ncol}) FROM {v}").fetchone()[0]
                    if mn is None or mn < dpc.get("min_group", 3): errs.append(f"{name}: view {v} violates min group size ({mn})")
                finally:
                    con_.close()
        if any(dpc.get("upgrade_with_approval") for dpc in cfg["datapoints"].values()) and not list((d / "gated").glob("*.md")):
            errs.append(f"{name}: approval upgrade declared but no gated bodies")
        rows.append((name, len(cfg["docs"]), n_idx, len(cfg["experts"]), len(cfg["canaries"]), len(cfg["datapoints"])))
    h = results["harrisons"][1]
    if h["_suppressed_cells"] < 1: errs.append("harrisons: no small cells to suppress (planted test missing)")
    if set(h["_largest"].values()) != {"pre-coagulation"}: errs.append(f"harrisons: pre-coagulation not largest every season: {h['_largest']}")
    if h["MON_PRECOAG"] <= h["WIN_PRECOAG"] or h["BAND_HIGH"] <= h["BAND_LOW"]: errs.append("harrisons: seasonal/time-band pattern not present")
    z = sqlite3.connect(OUT / "zensar" / "index.db").execute("SELECT count(*) FROM idx WHERE text LIKE '%IGNORE PREVIOUS INSTRUCTIONS%'").fetchone()[0]
    if z < 1: errs.append("zensar: planted injection missing from index")
    return errs, rows


def real_records(out: Path) -> list[Path]:
    """The files under the data folder that main() must not delete (the real data plan, step 1). Every file under a
    node's contributions or added_items, the upload records and the catalogue items a person added, counts as real
    unless it is a .json record that says "synthetic": true. A missing mark, a file that cannot be read and a leftover
    .json.tmp of an interrupted write all count as real. A pack whose header does not say synthetic true counts as real
    too. The packs this application builds always say synthetic true, so for uploads the records are the protection,
    and the pack check stops a pack placed in the folder from elsewhere."""
    found: list[Path] = []
    for path in sorted(p for folder in ("contributions", "added_items") for p in out.glob(f"*/{folder}/**/*") if p.is_file()):
        try:
            if path.suffix != ".json" or json.loads(path.read_text(encoding="utf-8")).get("synthetic") is not True:
                found.append(path)
        except (OSError, ValueError, AttributeError):
            found.append(path)
    for path in sorted(out.glob("*/packs/*/pack.json")):
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("pack", {}).get("synthetic") is not True:
                found.append(path)
        except (OSError, ValueError, AttributeError):
            found.append(path)
    return found


def main():
    if OUT.exists():
        real = real_records(OUT)
        if real:  # main() deletes the whole data folder, so it stops before a real file is lost
            names = ", ".join(str(p.relative_to(OUT)) for p in real[:8]) + (f" and {len(real) - 8} more" if len(real) > 8 else "")
            sys.exit(f"kbgen.py stopped before deleting {OUT}: {len(real)} {'file holds' if len(real) == 1 else 'files hold'} real data or "
                     f"no synthetic mark ({names}). With the stack stopped, move them out of the folder, or mark an invented upload record or added "
                     f"item with \"synthetic\": true.")
        shutil.rmtree(OUT)
    OUT.mkdir()
    results = {n: build_node(n) for n in NODES}
    (OUT / "gold").mkdir()
    (OUT / "gold" / "facts.json").write_text(json.dumps([f for r in results.values() for f in r[2]], indent=2))
    shutil.copy(KB / "golden.yaml", OUT / "gold" / "golden.yaml")
    errs, rows = validate(results)
    man = {"synthetic": True, "nodes": {x[0]: {"docs": x[1], "index_rows": x[2], "experts": x[3], "canaries": x[4], "datapoints": x[5]} for x in rows},
           "files": {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()[:12] for p in sorted(OUT.rglob("*")) if p.is_file()}}
    (OUT / "manifest.json").write_text(json.dumps(man, indent=2))
    print(f"{'node':10} {'datapts':>7} {'docs':>5} {'index rows':>10} {'experts':>8} {'canaries':>9}")
    for r in rows: print(f"{r[0]:10} {r[5]:>7} {r[1]:>5} {r[2]:>10} {r[3]:>8} {r[4]:>9}")
    print("harrisons stats:", {k: v for k, v in results['harrisons'][1].items()})
    print("ceat stats:", results["ceat"][1], "| kec stats:", results["kec"][1])
    if errs:
        print("\nVALIDATION FAILED"); [print(" -", e) for e in errs]; sys.exit(1)
    print("\nVALIDATION OK")
    from knowledge.packgen import build_all  # noqa: E402  packs and vector indexes after the node data
    print("packs:", json.dumps(build_all(build_vectors="--no-vectors" not in sys.argv)))


if __name__ == "__main__":
    main()
