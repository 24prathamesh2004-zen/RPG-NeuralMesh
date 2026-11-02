import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { getCurrentUser, signIn as signInRequest, signUp as signUpRequest } from '../services/api'
import type { CompanyId, UserAccount } from '../services/api'

interface SignUpPayload {
  email: string
  password: string
  display_name: string
  company: CompanyId
  expert_opt_in: boolean
  expert_title?: string
  expert_skills?: string[]
}

interface AuthContextValue {
  user: UserAccount | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signUp: (payload: SignUpPayload) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)
const TOKEN_KEY = 'rpg-neuralmesh-token'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserAccount | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!localStorage.getItem(TOKEN_KEY)) {
      setLoading(false)
      return
    }
    getCurrentUser()
      .then(({ data }) => setUser(data))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY)
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

  const signIn = async (email: string, password: string) => {
    const { data } = await signInRequest(email, password)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
  }

  const signUp = async (payload: SignUpPayload) => {
    const { data } = await signUpRequest(payload)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
  }

  const signOut = () => {
    localStorage.removeItem(TOKEN_KEY)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signUp, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used within AuthProvider')
  return value
}