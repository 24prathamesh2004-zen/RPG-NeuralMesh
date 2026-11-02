import { ArrowRight, Boxes, CircleDashed, Settings2, ShieldCheck, UsersRound } from 'lucide-react'
import { Link } from 'react-router-dom'

const SECTION_INFO = {
  'Expert Finder': { icon: UsersRound, eyebrow: 'People and expertise', status: 'Expert search and consent-based introductions are next.' },
  'Mesh Nodes': { icon: Boxes, eyebrow: 'Subsidiary connectivity', status: 'Node health and onboarding views are next.' },
  Governance: { icon: ShieldCheck, eyebrow: 'Access and evidence', status: 'Approval and audit views are next.' },
  Admin: { icon: Settings2, eyebrow: 'Shared mesh configuration', status: 'Registry, vocabulary and guardrail controls are next.' },
} as const

export default function WireframeSectionPage({ section }: { section: keyof typeof SECTION_INFO }) {
  const info = SECTION_INFO[section]
  const Icon = info.icon

  return (
    <section className="wireframe-placeholder">
      <span className="wireframe-placeholder-icon"><Icon size={22} /></span>
      <div className="mesh-eyebrow">{info.eyebrow}</div>
      <h1>{section}</h1>
      <p>{info.status}</p>
      <div className="wireframe-placeholder-status"><CircleDashed size={15} /> Planned pilot view</div>
      <Link to="/ask" className="mesh-text-link">Back to Ask NeuralMesh <ArrowRight size={14} /></Link>
    </section>
  )
}