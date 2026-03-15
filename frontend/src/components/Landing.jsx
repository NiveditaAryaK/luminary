import { useState } from 'react'
import './Landing.css'

const GENRES = ['fantasy', 'sci-fi', 'mystery', 'horror', 'romance', 'adventure', 'historical']
const PROMPTS = [
  'An astronomer discovers a staircase hidden inside moonlight.',
  'A detective wakes up wearing someone else\'s scars.',
  'A ruined kingdom broadcasts warnings through broken radios.',
]

export default function Landing({ onResume, onStart, stories, user, onSignIn, onSignOut, persistenceReady, resumeError }) {
  const [genre, setGenre] = useState('fantasy')
  const [premise, setPremise] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function handleStart() {
    if (!premise.trim()) {
      setErr('Please enter a premise.')
      return
    }

    setLoading(true)
    setErr('')

    try {
      const r = await fetch('/api/story/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ genre, premise }),
      })
      const data = await r.json().catch(() => ({}))

      if (data.session_id) {
        onStart({
          autoStart: true,
          genre,
          premise,
          sessionId: data.session_id,
          storyId: data.session_id,
          title: data.title,
        })
      } else {
        setErr(data.detail || (r.ok ? 'Failed to start story.' : `Request failed (${r.status}).`))
      }
    } catch {
      setErr('Connection error. Please try again.')
    }

    setLoading(false)
  }

  return (
    <div className="landing">
      <div className="landing-backdrop" />
      <div className="landing-shell">
        <section className="landing-copy">
          <div className="auth-bar">
            <div className="auth-copy">
              <span className="auth-label">Story Archive</span>
              <strong>{user?.isAnonymous ? 'Guest session' : user?.displayName || 'Signed in'}</strong>
            </div>
            {persistenceReady && (
              user?.isAnonymous
                ? <button className="auth-btn" onClick={onSignIn}>Upgrade to Google</button>
                : <button className="auth-btn ghost" onClick={onSignOut}>Sign out</button>
            )}
          </div>
          <p className="eyebrow">Creative Storyteller Agent</p>
          <h1 className="landing-title">Luminary</h1>
          <p className="landing-subtitle">
            Direct a living story world that answers with prose, scene art, and branching choices in one cinematic flow.
          </p>

          <div className="landing-highlights">
            <div className="highlight-card">
              <span>Interleaved output</span>
              <strong>Text, imagery, and branching decisions arrive as one staged response.</strong>
            </div>
            <div className="highlight-card">
              <span>Genre steering</span>
              <strong>Push each session toward dread, wonder, intimacy, or impossible mystery.</strong>
            </div>
            <div className="highlight-card">
              <span>Story room</span>
              <strong>Each choice acts like direction given to a live cinematic narrator.</strong>
            </div>
          </div>

          <div className="story-library">
            <div className="library-header">
              <span>Saved stories</span>
              <p>{persistenceReady ? 'Resume unfinished worlds from your archive.' : 'Add Firebase config to enable cross-session saves.'}</p>
            </div>
            <div className="library-list">
              {resumeError && <div className="library-empty error">{resumeError}</div>}
              {stories?.length
                ? stories.slice(0, 4).map((story) => (
                  <button key={story.id} className="library-card" onClick={() => onResume(story)}>
                    <strong>{story.title || 'Untitled story'}</strong>
                    <span>{story.genre}</span>
                    <p>{story.premise}</p>
                  </button>
                ))
                : <div className="library-empty">No saved stories yet. Your latest completed beat will appear here.</div>}
            </div>
          </div>
        </section>

        <section className="landing-form">
          <div className="form-card">
            <div className="form-header">
              <p>Story Brief</p>
              <span>Describe the opening frame, tone, and danger.</span>
            </div>

            <div className="genre-grid">
              {GENRES.map((g) => (
                <button key={g} className={`genre-btn ${genre === g ? 'active' : ''}`} onClick={() => setGenre(g)}>
                  {g}
                </button>
              ))}
            </div>

            <textarea
              placeholder="Describe the opening scene, emotional tone, visual texture, and the impossible thing that changes everything..."
              value={premise}
              onChange={(e) => setPremise(e.target.value)}
            />

            <div className="prompt-bank">
              {PROMPTS.map((prompt) => (
                <button key={prompt} className="prompt-chip" onClick={() => setPremise(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>

            {err && <p className="err">{err}</p>}

            <button className="begin-btn" onClick={handleStart} disabled={loading}>
              {loading ? 'Summoning your opening scene...' : 'Open the Story Room'}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
