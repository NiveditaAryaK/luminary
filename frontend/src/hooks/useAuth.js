import { useEffect, useState } from 'react'
import {
  onAuthStateChanged,
  signInAnonymously,
  signInWithPopup,
  signOut,
} from 'firebase/auth'

import { auth, googleProvider, isFirebaseConfigured } from '../lib/firebase'

export function useAuth() {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(!isFirebaseConfigured)

  useEffect(() => {
    if (!isFirebaseConfigured || !auth) return

    const unsub = onAuthStateChanged(auth, async (nextUser) => {
      if (nextUser) {
        setUser(nextUser)
        setReady(true)
        return
      }

      try {
        const creds = await signInAnonymously(auth)
        setUser(creds.user)
      } catch (error) {
        console.error('Anonymous sign-in failed', error)
      } finally {
        setReady(true)
      }
    })

    return () => unsub()
  }, [])

  async function signInWithGoogle() {
    if (!auth) return
    await signInWithPopup(auth, googleProvider)
  }

  async function logout() {
    if (!auth) return
    await signOut(auth)
  }

  return {
    isFirebaseConfigured,
    ready,
    signInWithGoogle,
    user,
    logout,
  }
}
