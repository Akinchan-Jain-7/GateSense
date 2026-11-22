import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import { homeFor } from '@/lib/api/auth'
import { useAuth } from '@/lib/auth'
import { useDemoInfo } from '@/lib/queries'

/** One-click sign-in as a demo account (only offered when the API is in demo mode). */
export function useDemoLogin() {
  const demo = useDemoInfo()
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const [pending, setPending] = useState<string | null>(null)

  const accounts = demo.data?.enabled ? demo.data.accounts : []
  const password = demo.data?.password ?? null

  async function loginAs(role: string) {
    const account = accounts.find((a) => a.role === role)
    if (!account || !password) return
    setPending(role)
    try {
      const user = await signIn(account.email, password)
      void navigate(homeFor(user.role))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Couldn’t sign in to the demo.')
    } finally {
      setPending(null)
    }
  }

  return {
    enabled: accounts.length > 0,
    accounts,
    password,
    pending,
    loginAs,
    isLoading: demo.isLoading,
  }
}
