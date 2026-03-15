import { useEffect, useState } from 'react'
import Landing from './components/Landing.jsx'
import Story from './components/Story.jsx'
import { useAuth } from './hooks/useAuth'
import { saveStorySnapshot, subscribeToStories } from './lib/storyStore'
import { restoreStorySession } from './utils/storyApi'

export default function App() {
  const [session, setSession] = useState(null)
  const [stories, setStories] = useState([])
  const [resumeError, setResumeError] = useState('')
  const { isFirebaseConfigured, logout, ready, signInWithGoogle, user } = useAuth()

  useEffect(() => {
    if (!isFirebaseConfigured || !user?.uid) return
    return subscribeToStories(user.uid, setStories)
  }, [isFirebaseConfigured, user?.uid])

  async function handleSnapshot(snapshot) {
    if (!isFirebaseConfigured || !user?.uid || !snapshot?.storyId) return
    try {
      await saveStorySnapshot(user.uid, snapshot.storyId, {
        directorMode: snapshot.directorMode,
        genre: snapshot.genre,
        history: snapshot.history,
        memory: snapshot.savedMemory || [],
        premise: snapshot.premise,
        savedChoices: snapshot.savedChoices || [],
        savedStoryboard: snapshot.savedStoryboard || [],
        savedSegments: snapshot.savedSegments,
        storyId: snapshot.storyId,
        title: snapshot.title,
        turns: snapshot.turns,
      })
    } catch (error) {
      console.error('Failed to save story snapshot', error)
    }
  }

  async function handleStartSession(nextSession) {
    setSession(nextSession)

    if (!isFirebaseConfigured || !user?.uid || !nextSession?.storyId) return

    try {
      await saveStorySnapshot(user.uid, nextSession.storyId, {
        directorMode: nextSession.directorMode || 'cinematic',
        genre: nextSession.genre,
        history: [],
        memory: [],
        premise: nextSession.premise,
        savedChoices: [],
        savedStoryboard: [],
        savedSegments: [],
        storyId: nextSession.storyId,
        title: nextSession.title,
        turns: 0,
      })
    } catch (error) {
      console.error('Failed to create initial saved story', error)
    }
  }

  async function handleResume(story) {
    setResumeError('')

    try {
      const restored = await restoreStorySession({
        title: story.title,
        genre: story.genre,
        premise: story.premise,
        history: story.history || [],
        turns: story.turns || 0,
        director_mode: story.directorMode || 'cinematic',
        memory: story.memory || [],
        storyboard: story.savedStoryboard || [],
      })

      const hasSavedProgress = Boolean(
        (story.savedSegments && story.savedSegments.length) ||
        (story.history && story.history.length) ||
        story.turns
      )

      setSession({
        autoStart: !hasSavedProgress,
        genre: restored.genre,
        premise: restored.premise,
        directorMode: restored.director_mode || story.directorMode || 'cinematic',
        savedMemory: restored.memory || story.memory || [],
        savedChoices: story.savedChoices || [],
        savedStoryboard: restored.storyboard || story.savedStoryboard || [],
        savedSegments: story.savedSegments || [],
        sessionId: restored.session_id,
        storyId: story.storyId || story.id,
        title: restored.title,
      })
    } catch (error) {
      console.error('Failed to resume story', error)
      setResumeError(error.message || 'Failed to resume story.')
    }
  }

  if (!ready) return null

  return session
    ? <Story session={session} onExit={() => setSession(null)} onSnapshot={handleSnapshot} />
    : (
      <Landing
        onResume={handleResume}
        resumeError={resumeError}
        onSignIn={signInWithGoogle}
        onSignOut={logout}
        onStart={handleStartSession}
        persistenceReady={isFirebaseConfigured}
        stories={stories}
        user={user}
      />
    )
}
