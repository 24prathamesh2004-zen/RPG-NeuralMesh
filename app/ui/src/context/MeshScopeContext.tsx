import { createContext, useContext } from 'react'
import type { CompanyId } from '../services/api'

export const DEFAULT_MESH_SCOPE: CompanyId[] = ['ceat', 'kec', 'zensar', 'harrisons']

interface MeshScopeValue {
  selectedNodes: CompanyId[]
  setSelectedNodes: (nodes: CompanyId[]) => void
}

const MeshScopeContext = createContext<MeshScopeValue | null>(null)

export const MeshScopeProvider = MeshScopeContext.Provider

export function useMeshScope() {
  const value = useContext(MeshScopeContext)
  if (!value) throw new Error('useMeshScope must be used within MeshScopeProvider')
  return value
}