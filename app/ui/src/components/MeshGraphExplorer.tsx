import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DataSet } from 'vis-data'
import { Network } from 'vis-network'
import type { MeshGraphView } from '../services/api'

// Same engine and rules as the Agent Registry dependency graph (vis-network, as cobol_contextintel uses through pyvis):
// progressive expansion instead of drawing every entity at once, nodes hidden and never removed, an edge hidden when
// either end is hidden, a tree view from a right-click, Escape back to the full view.

export const TYPE_ORDER = ['Subsidiary', 'Domain', 'Datapoint', 'Document', 'Concept', 'Skill', 'Role', 'Expert', 'Asset', 'AssetFamily', 'Condition', 'ConditionFamily', 'GradeScale', 'CoverType', 'View', 'ReviewStatus', 'Inspection']
export const TYPE_COLOURS: Record<string, string> = {
  Subsidiary: '#212529', Domain: '#868e96', Datapoint: '#1c7ed6', Document: '#74c0fc', Concept: '#f08c00',
  Skill: '#2f9e44', Role: '#ae3ec9', Expert: '#e64980',
  Asset: '#c2255c', AssetFamily: '#a61e4d', Condition: '#e8590c', ConditionFamily: '#d9480f', GradeScale: '#2b8a3e', CoverType: '#0b7285',
  View: '#868e96', ReviewStatus: '#adb5bd', Inspection: '#5f3dc4',
}
// A value of one of the tables below by its own key only, so a type a person wrote, such as "constructor", finds nothing
const own = <T,>(table: Record<string, T>, key: string): T | undefined => (Object.prototype.hasOwnProperty.call(table, key) ? table[key] : undefined)
// The types the mesh does not know, such as the ones a person wrote in an ingested graph, take these colours in turn,
// then colours spread round the colour wheel, so no two of them in one graph share a colour
const OTHER_COLOURS = ['#0ca678', '#4263eb', '#fab005', '#845ef7', '#ff6b6b', '#20c997', '#66a80f', '#f783ac', '#3bc9db', '#e599f7']
const otherColour = (i: number) => (i < OTHER_COLOURS.length ? OTHER_COLOURS[i] : `hsl(${Math.round((i * 137.5) % 360)}, 60%, 45%)`)
const COMPANY_TONES: Record<string, string> = { ceat: '#e8590c', kec: '#1c7ed6', zensar: '#7048e8', harrisons: '#5c940d', raychem: '#862e9c', rpgls: '#0c8599', asvata: '#e67700', others: '#868e96' }
const EDGE_COLOURS: Record<string, string> = {
  CONFLICTS_WITH: '#e03131', CORROBORATES: '#2f9e44', ADDRESSES_GAP: '#f08c00', SUPERSEDES: '#9c36b5',
  RELATED_TO: '#4c6ef5', BROADER: '#4c6ef5', SAME_AS: '#4c6ef5', SIMILAR_TO: '#868e96', GOVERNED_BY: '#2b8a3e',
}
const LINK_TYPES = new Set(['CONFLICTS_WITH', 'CORROBORATES', 'ADDRESSES_GAP', 'SUPERSEDES'])
const START_TYPES = new Set(['Subsidiary', 'Datapoint'])
const SHAPES: Record<string, string> = { Subsidiary: 'box', Domain: 'diamond', Datapoint: 'dot', Document: 'dot', Concept: 'triangle', Skill: 'star', Role: 'square', Expert: 'dot', Asset: 'hexagon', AssetFamily: 'hexagon', Condition: 'triangleDown', ConditionFamily: 'triangleDown', GradeScale: 'diamond', CoverType: 'diamond', View: 'dot', ReviewStatus: 'dot', Inspection: 'square' }
const SIZES: Record<string, number> = { Domain: 12, Datapoint: 12, Document: 8, Concept: 11, Skill: 14, Role: 11, Expert: 8, Asset: 12, AssetFamily: 13, Condition: 9, ConditionFamily: 11, GradeScale: 10, CoverType: 9, View: 7, ReviewStatus: 7, Inspection: 9 }

type GNode = MeshGraphView['nodes'][number]
type GEdge = MeshGraphView['edges'][number]
interface Neighbour { edge: GEdge; other: GNode; outgoing: boolean }

// A fit by vis-network goes by the node shapes, and a label is wider than its node. This fit takes the box of each node
// with its label, so no label is cut at the edge of the canvas.
function fitWithMargin(net: Network, ids?: string[], animate = false) {
  const body = (net as any).body
  const list = (ids ?? Object.keys(body.nodes)).filter((id) => body.nodes[id] && !body.nodes[id].options.hidden)
  const canvas = (net as any).canvas.frame.canvas as HTMLCanvasElement
  if (!list.length || !canvas.clientWidth) { net.fit({ animation: false } as any); return }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const ctx = canvas.getContext('2d')
  const positions = net.getPositions(list)
  for (const id of list) {
    const b = net.getBoundingBox(id), o = body.nodes[id].options, at = positions[id]
    if (ctx) ctx.font = `${o.font?.bold ? 'bold ' : ''}${o.font?.size ?? 14}px arial`
    const half = Math.max((b.right - b.left) / 2, (ctx ? ctx.measureText(String(o.label ?? '')).width : 0) / 2 + 4)
    minX = Math.min(minX, at.x - half); maxX = Math.max(maxX, at.x + half); minY = Math.min(minY, b.top); maxY = Math.max(maxY, b.bottom)
  }
  const pad = 16
  const scale = Math.min(1.2, (canvas.clientWidth - 2 * pad) / Math.max(maxX - minX, 1), (canvas.clientHeight - 2 * pad) / Math.max(maxY - minY, 1))
  net.moveTo({ position: { x: (minX + maxX) / 2, y: (minY + maxY) / 2 }, scale, ...(animate ? { animation: { duration: 400, easingFunction: 'easeInOutQuad' } } : {}) } as any)
}

function short(text: string, max = 28) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

// startIds: the entities shown first when the graph is too large to show at once (default: the companies and items).
// edgeLabels: every link carries its type as a label, for a graph whose link types a person wrote.
export default function MeshGraphExplorer({ graph, revealAll = false, startIds, edgeLabels = false }: { graph: Pick<MeshGraphView, 'nodes' | 'edges' | 'counts'>; revealAll?: boolean; startIds?: string[]; edgeLabels?: boolean }) {
  const container = useRef<HTMLDivElement | null>(null)
  const network = useRef<Network | null>(null)
  const nodesDs = useRef<DataSet<any> | null>(null)
  const edgesDs = useRef<DataSet<any> | null>(null)
  const [revealed, setRevealed] = useState<Set<string>>(new Set())
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())
  const [selected, setSelected] = useState<string | null>(null)
  const [treeRoot, setTreeRoot] = useState<string | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; id: string } | null>(null)
  const [search, setSearch] = useState('')
  const fitNext = useRef(true)
  const treeRef = useRef(treeRoot)
  treeRef.current = treeRoot

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph])
  const typeColour = useMemo(() => {
    const others = new Map([...new Set(graph.nodes.map((n) => n.type))].filter((t) => !own(TYPE_COLOURS, t)).sort().map((t, i) => [t, otherColour(i)]))
    return (type: string) => own(TYPE_COLOURS, type) ?? others.get(type) ?? '#adb5bd'
  }, [graph])
  const edges = useMemo(() => graph.edges.filter((e) => byId.has(e.source) && byId.has(e.target)), [graph, byId])
  const adjacency = useMemo(() => {
    const out = new Map<string, Neighbour[]>()
    for (const e of edges) {
      const a = byId.get(e.source)!, b = byId.get(e.target)!
      out.set(a.id, [...(out.get(a.id) ?? []), { edge: e, other: b, outgoing: true }])
      out.set(b.id, [...(out.get(b.id) ?? []), { edge: e, other: a, outgoing: false }])
    }
    return out
  }, [edges, byId])

  const startKey = (startIds ?? []).join('|')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const startSet = useCallback(() => new Set(revealAll || !startIds ? graph.nodes.filter((n) => revealAll || START_TYPES.has(n.type)).map((n) => n.id) : startIds), [graph, revealAll, startKey])
  useEffect(() => { setRevealed(startSet()); setSelected(null); setTreeRoot(null) }, [startSet])

  // Boot the engine once per graph. Every node is in the data set from the start, hidden until revealed.
  useEffect(() => {
    if (!container.current) return
    const nodes = new DataSet<any>(graph.nodes.map((n) => {
      const tone = (n.subsidiary && own(COMPANY_TONES, n.subsidiary)) || (n.type === 'Subsidiary' && own(COMPANY_TONES, n.id.split(':')[1])) || typeColour(n.type)
      const fill = n.type === 'Subsidiary' ? tone : typeColour(n.type)
      return {
        id: n.id, label: n.type === 'Subsidiary' ? n.label : short(n.label), title: `${n.type}: ${n.label}\n${n.id}`,
        shape: own(SHAPES, n.type) ?? 'dot', size: own(SIZES, n.type) ?? 9, hidden: true, ntype: n.type,
        color: { background: fill, border: tone, highlight: { background: fill, border: '#212529' } }, borderWidth: n.type === 'Subsidiary' ? 1 : 2,
        font: n.type === 'Subsidiary' ? { color: '#ffffff', size: 18, bold: true } : { color: '#343a40', size: 13 },
        margin: n.type === 'Subsidiary' ? 10 : undefined, mass: n.type === 'Subsidiary' ? 3 : 1,
      }
    }))
    const edgeDs = new DataSet<any>(edges.map((e) => ({
      id: e.id, from: e.source, to: e.target, hidden: true, etype: e.type,
      label: edgeLabels ? e.type : LINK_TYPES.has(e.type) ? e.type.toLowerCase().replace(/_/g, ' ') : undefined, // a type a person wrote is shown as written
      title: `${e.type}${e.status !== 'approved' ? ` (${e.status})` : ''}`,
      color: { color: own(EDGE_COLOURS, e.type) ?? '#ced4da', highlight: own(EDGE_COLOURS, e.type) ?? '#495057' },
      width: LINK_TYPES.has(e.type) ? 2.5 : 1, dashes: e.status !== 'approved',
    })))
    nodesDs.current = nodes
    edgesDs.current = edgeDs
    const net = new Network(container.current, { nodes, edges: edgeDs } as any, {
      physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { springLength: 80, gravitationalConstant: -45, centralGravity: 0.02 }, stabilization: { iterations: 250 } },
      edges: { arrows: { to: { enabled: true, scaleFactor: 0.5 } }, smooth: { enabled: true, type: 'dynamic' }, font: { size: 10, color: '#495057', strokeWidth: 3, strokeColor: '#ffffff' } },
      nodes: { scaling: { label: { drawThreshold: 2 } } },
      interaction: { hover: true, tooltipDelay: 150 },
    } as any)
    network.current = net
    net.on('stabilizationIterationsDone', () => { if (!treeRef.current) fitWithMargin(net) })
    // the layout keeps moving for a moment after the first fit, so it is fitted once more when it has settled
    let settled = false
    net.on('stabilized', () => { if (!settled && !treeRef.current) { settled = true; fitWithMargin(net, undefined, true) } })
    net.on('dragStart', () => { settled = true })
    net.on('zoom', () => { settled = true })
    net.on('click', (p: any) => { setMenu(null); setSelected(p.nodes?.length ? String(p.nodes[0]) : null) })
    net.on('doubleClick', (p: any) => { if (p.nodes?.length) expand(String(p.nodes[0])) })
    net.on('oncontext', (p: any) => {
      const id = net.getNodeAt(p.pointer.DOM)
      p.event.preventDefault()
      setMenu(id != null || treeRef.current ? { x: p.event.clientX, y: p.event.clientY, id: id != null ? String(id) : '' } : null)
    })
    net.on('dragStart', () => setMenu(null))
    return () => { net.destroy(); network.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, edges])

  const expand = useCallback((id: string) => {
    const pos = network.current?.getPositions([id])[id]
    setRevealed((prev) => {
      const next = new Set(prev)
      for (const nb of adjacency.get(id) ?? []) {
        if (!next.has(nb.other.id) && pos) {
          try { nodesDs.current?.update({ id: nb.other.id, x: pos.x + (Math.random() - 0.5) * 60, y: pos.y + (Math.random() - 0.5) * 60 }) } catch { /* not drawn yet */ }
        }
        next.add(nb.other.id)
      }
      next.add(id)
      return next
    })
    setSelected(id)
  }, [adjacency])

  // Visibility: the tree decides while it is open, otherwise revealed minus the hidden types.
  useEffect(() => {
    const nodes = nodesDs.current, edgeDs = edgesDs.current, net = network.current
    if (!nodes || !edgeDs || !net) return
    let visible: Set<string>
    let treeEdges: Set<string> | null = null
    if (treeRoot) {
      treeEdges = new Set()
      const depth = new Map([[treeRoot, 0]])
      const order = [treeRoot]
      const children = new Map<string, string[]>([[treeRoot, []]])
      for (let i = 0; i < order.length; i++) {
        const from = order[i]
        if ((depth.get(from) ?? 0) >= 2) continue
        for (const nb of adjacency.get(from) ?? []) {
          if (depth.has(nb.other.id) || hiddenTypes.has(nb.other.type)) continue
          depth.set(nb.other.id, (depth.get(from) ?? 0) + 1)
          children.get(from)!.push(nb.other.id)
          treeEdges.add(nb.edge.id)
          children.set(nb.other.id, [])
          order.push(nb.other.id)
        }
      }
      visible = new Set(order)
      const pos = new Map<string, { x: number; y: number }>()
      let leaf = 0
      const place = (id: string): number => {
        const kids = children.get(id) ?? []
        const x = kids.length ? kids.map(place).reduce((a, b) => a + b, 0) / kids.length : (leaf++) * 125
        pos.set(id, { x, y: (depth.get(id) ?? 0) * 130 })
        return x
      }
      place(treeRoot)
      net.setOptions({ physics: { enabled: false }, edges: { smooth: { enabled: true, type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.4 } } } as any)
      pos.forEach((p, id) => { try { net.moveNode(id, p.x, p.y) } catch { /* hidden */ } })
    } else {
      visible = new Set([...revealed].filter((id) => !hiddenTypes.has(byId.get(id)?.type ?? '')))
      net.setOptions({ physics: { enabled: true }, edges: { smooth: { enabled: true, type: 'dynamic' } } } as any)
    }
    nodes.update(nodes.get().filter((n: any) => n.hidden === visible.has(n.id)).map((n: any) => ({ id: n.id, hidden: !visible.has(n.id) })))
    edgeDs.update(edgeDs.get().map((e: any) => ({ id: e.id, hidden: treeEdges ? !treeEdges.has(e.id) : !(visible.has(e.from) && visible.has(e.to)) }))
      .filter((u: any) => (edgeDs.get(u.id) as any)?.hidden !== u.hidden))
    if (treeRoot || fitNext.current) {
      fitNext.current = false
      setTimeout(() => { try { fitWithMargin(net, [...visible], true) } catch { /* noop */ } }, treeRoot ? 0 : 900)
    }
  }, [revealed, hiddenTypes, treeRoot, adjacency, byId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMenu(null); if (treeRef.current) fitNext.current = true; setTreeRoot(null) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const focus = (id: string) => {
    setRevealed((prev) => new Set(prev).add(id))
    setSelected(id)
    setTimeout(() => {
      try { network.current?.selectNodes([id]); network.current?.focus(id, { scale: 0.85, animation: { duration: 400, easingFunction: 'easeInOutQuad' } } as any) } catch { /* noop */ }
    }, 50)
  }
  const runSearch = () => {
    const q = search.trim().toLowerCase()
    if (!q) return
    const hit = graph.nodes.find((n) => n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q))
    if (hit) { setTreeRoot(null); expand(hit.id); focus(hit.id) }
  }
  const toggleType = (type: string) => setHiddenTypes((prev) => {
    const next = new Set(prev)
    if (next.has(type)) next.delete(type)
    else next.add(type)
    return next
  })

  const node = selected ? byId.get(selected) : null
  const groups = useMemo(() => {
    const out = new Map<string, Neighbour[]>()
    for (const nb of (selected && adjacency.get(selected)) || []) {
      const key = `${nb.outgoing ? '' : '← '}${nb.edge.type}`
      out.set(key, [...(out.get(key) ?? []), nb])
    }
    return [...out.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [selected, adjacency])
  const shown = [...revealed].filter((id) => !hiddenTypes.has(byId.get(id)?.type ?? '')).length

  return (
    <div className="mesh-graph-explorer">
      <div className="mesh-graph-toolbar">
        <div className="mesh-graph-counts">
          {[...TYPE_ORDER.filter((t) => graph.counts[t]), ...Object.keys(graph.counts).filter((t) => !TYPE_ORDER.includes(t)).sort((a, b) => graph.counts[b] - graph.counts[a] || a.localeCompare(b))].map((t) => (
            <button type="button" key={t} className={hiddenTypes.has(t) ? 'off' : ''} onClick={() => toggleType(t)} aria-pressed={!hiddenTypes.has(t)}>
              <i style={{ background: typeColour(t) }} />{t} {graph.counts[t]}
            </button>
          ))}
        </div>
        <form className="mesh-graph-search" onSubmit={(e) => { e.preventDefault(); runSearch() }}>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find an entity" aria-label="Find an entity" />
          <button type="submit" className="mesh-outline-action">Find</button>
          <button type="button" className="mesh-outline-action" onClick={() => { fitNext.current = true; setTreeRoot(null); setRevealed(startSet()); setSelected(null) }}>Reset</button>
          <button type="button" className="mesh-outline-action" onClick={() => { fitNext.current = true; setTreeRoot(null); setRevealed(new Set(graph.nodes.map((n) => n.id))) }}>Show all</button>
        </form>
      </div>
      <div className="mesh-graph-body">
        <div className="mesh-graph-canvas-wrap">
          <div ref={container} className="mesh-graph-canvas" role="img" aria-label="Mesh graph" />
          <div className="mesh-graph-hint">{treeRoot ? `Tree from ${byId.get(treeRoot)?.label ?? treeRoot}, two steps out. Esc returns.` : `${shown} of ${graph.nodes.length} shown. Double-click to open connections, right-click for a tree.`}</div>
          {menu && (
            <div className="mesh-graph-menu" style={{ left: menu.x, top: menu.y }} onMouseLeave={() => setMenu(null)}>
              {menu.id && <button type="button" onClick={() => { expand(menu.id); setMenu(null) }}>Open connections</button>}
              {menu.id && menu.id !== treeRoot && <button type="button" onClick={() => { setTreeRoot(menu.id); setSelected(menu.id); setMenu(null) }}>Tree from here</button>}
              {treeRoot && <button type="button" onClick={() => { fitNext.current = true; setTreeRoot(null); setMenu(null) }}>Back to the full graph</button>}
            </div>
          )}
        </div>
        <aside className="mesh-graph-detail">
          {node ? (
            <>
              <span className="mesh-graph-type" style={{ background: typeColour(node.type) }}>{node.type}</span>
              <h3>{node.label}</h3>
              <code>{node.id}</code>
              {node.subsidiary && <p>Company: {node.subsidiary}</p>}
              <div className="mesh-graph-actions">
                <button type="button" className="mesh-outline-action" onClick={() => expand(node.id)}>Open connections</button>
                <button type="button" className="mesh-outline-action" onClick={() => setTreeRoot(node.id)}>Tree from here</button>
              </div>
              {groups.map(([type, list]) => (
                <div key={type} className="mesh-graph-group">
                  <h4 style={{ color: own(EDGE_COLOURS, type.replace('← ', '')) }}>{type} ({list.length})</h4>
                  <ul>{list.map((nb) => (
                    <li key={nb.edge.id}><button type="button" onClick={() => focus(nb.other.id)}>{nb.other.label}</button>{nb.edge.status !== 'approved' && <em> {nb.edge.status}</em>}</li>
                  ))}</ul>
                </div>
              ))}
            </>
          ) : (
            <p className="mesh-graph-empty">Select an entity to see its connections.</p>
          )}
        </aside>
      </div>
    </div>
  )
}
