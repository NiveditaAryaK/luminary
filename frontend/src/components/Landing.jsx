import { useState } from 'react'
import './Landing.css'

const GENRES = ['fantasy','sci-fi','mystery','horror','romance','adventure','historical']

export default function Landing({ onStart }) {
  const [genre, setGenre] = useState('fantasy')
  const [premise, setPremise] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function handleStart() {
    if (!premise.trim()) { setErr('Please enter a premise.'); return }
    setLoading(true); setErr('')
    try {
      const r = await fetch('/api/story/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ genre, premise })
      })
      const data = await r.json().catch(() => ({}))
      if (data.session_id) onStart({ sessionId: data.session_id, genre, premise, title: data.title })
      else setErr(data.detail || (r.ok ? 'Failed to start story.' : `Request failed (${r.status}).`))
    } catch(e) { setErr('Connection error. Please try again.') }
    setLoading(false)
  }

  return (
    <div className="landing">
      <h1 className="landing-title">Luminary</h1>
      <p className="landing-subtitle">AI Cinematic Interactive Storytelling</p>
      <div className="landing-form">
        <div className="genre-grid">
          {GENRES.map(g => (
            <button key={g} className={`genre-btn ${genre===g?'active':''}`} onClick={() => setGenre(g)}>{g}</button>
          ))}
        </div>
        <textarea
          placeholder="Describe your story premise... (e.g. A detective wakes up with no memory in a city that doesn't exist)"
          value={premise}
          onChange={e => setPremise(e.target.value)}
        />
        {err && <p className="err">{err}</p>}
        <button className="begin-btn" onClick={handleStart} disabled={loading}>
          {loading ? 'Conjuring your story...' : 'Begin the Story ✦'}
        </button>
      </div>
    </div>
  )
}
