import { useEffect, useRef } from 'react'

import { useStorySession } from '../hooks/useStorySession'

import './Story.css'

export default function Story({ session, onExit }) {
  const { choices, error, makeChoice, segments, streaming, title } = useStorySession(session)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [segments, streaming])

  return (
    <div className="story-page">
      <div className="story-header">
        <h2 className="story-title">{title}</h2>
        <button className="exit-btn" onClick={onExit}>✕ New Story</button>
      </div>
      <div className="segments">
        {error && (
          <p className="seg-text" style={{ color: 'var(--gold)' }}>{error}</p>
        )}
        {segments.map((seg, i) => (
          <div key={i}>
            {(seg.type === 'text' || seg.type === 'text_stream') && (
              <p className="seg-text">{seg.content}</p>
            )}
            {seg.type === 'image' && (
              <div className="seg-image">
                <img src={`data:${seg.mime};base64,${seg.content}`} alt="Story illustration" />
              </div>
            )}
            {seg.type === 'choice' && (
              <p style={{color:'var(--gold)', fontStyle:'italic', fontSize:'0.9rem'}}>▶ {seg.content}</p>
            )}
          </div>
        ))}
        {streaming && (
          <div className="streaming">
            <span className="dot">◆</span> Weaving the story...
          </div>
        )}
      </div>
      {choices.length > 0 && (
        <div className="choices">
          {choices.map((c, i) => (
            <button key={i} className="choice-btn" onClick={() => makeChoice(c)} disabled={streaming}>{c}</button>
          ))}
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
