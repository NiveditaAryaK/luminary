import {
  collection,
  doc,
  onSnapshot,
  serverTimestamp,
  setDoc,
} from 'firebase/firestore'

import { db, isFirebaseConfigured } from './firebase'

function storiesCollection(userId) {
  return collection(db, 'users', userId, 'stories')
}

export function subscribeToStories(userId, callback) {
  if (!isFirebaseConfigured || !db || !userId) return () => {}

  return onSnapshot(storiesCollection(userId), (snapshot) => {
    const stories = snapshot.docs
      .map((entry) => ({ id: entry.id, ...entry.data() }))
      .sort((a, b) => {
        const aTime = a.updatedAt?.seconds || 0
        const bTime = b.updatedAt?.seconds || 0
        return bTime - aTime
      })

    callback(stories)
  })
}

export async function saveStorySnapshot(userId, storyId, payload) {
  if (!isFirebaseConfigured || !db || !userId || !storyId) return

  const ref = doc(db, 'users', userId, 'stories', storyId)
  await setDoc(ref, { ...payload, updatedAt: serverTimestamp() }, { merge: true })
}
