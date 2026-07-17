import { useEffect, useState } from 'react'
import {
  browserLocalPersistence,
  linkWithPopup,
  onIdTokenChanged,
  setPersistence,
  signInAnonymously,
  signInWithPopup,
  signOut,
  updateProfile,
} from 'firebase/auth'

import { auth, googleProvider, isFirebaseConfigured } from '../lib/firebase'

// Firebase mutates the same user instance in place (e.g. when an anonymous
// account is linked to Google), so React state needs a fresh snapshot object
// or re-renders are skipped.
function projectUser(firebaseUser) {
  if (!firebaseUser) return null
  return {
    uid: firebaseUser.uid,
    isAnonymous: firebaseUser.isAnonymous,
    displayName: firebaseUser.displayName,
  }
}

export function useAuth() {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(!isFirebaseConfigured)

  useEffect(() => {
    if (!isFirebaseConfigured || !auth) return

    setPersistence(auth, browserLocalPersistence).catch((error) => {
      console.error('Failed to set auth persistence', error)
    })

    // onIdTokenChanged also fires when an anonymous account gets linked to
    // Google, which onAuthStateChanged does not (the uid stays the same).
    const unsub = onIdTokenChanged(auth, async (nextUser) => {
      if (nextUser) {
        setUser(projectUser(nextUser))
        setReady(true)
        return
      }

      try {
        const creds = await signInAnonymously(auth)
        setUser(projectUser(creds.user))
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

    // Link the guest account instead of replacing it, so stories saved while
    // anonymous stay under the same uid after upgrading.
    const current = auth.currentUser
    if (current?.isAnonymous) {
      try {
        const result = await linkWithPopup(current, googleProvider)
        const google = result.user.providerData.find((p) => p.providerId === 'google.com')
        if (!result.user.displayName && google?.displayName) {
          await updateProfile(result.user, {
            displayName: google.displayName,
            photoURL: google.photoURL || null,
          })
        }
        setUser(projectUser(result.user))
        return
      } catch (error) {
        // This Google account already has its own Luminary user — fall back
        // to signing into that account instead.
        if (error?.code !== 'auth/credential-already-in-use') throw error
      }
    }

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
