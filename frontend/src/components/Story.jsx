import { useEffect, useRef } from 'react'

import { useStorySession } from '../hooks/useStorySession'
import { stripChoiceMarkup } from '../utils/storyText'

import './Story.css'

export default function Story({ session, onExit }) {
  const { choices, error, makeChoice, segments, streaming, title } = useStorySession(session)
  const bottomRef = useRef(null)
  const visibleSegments = segments
    .map((seg) => (
      seg.type === 'text' || seg.type === 'text_stream'
        ? { ...seg, content: stripChoiceMarkup(seg.content) }
        : seg
    ))
    .filter((seg) => (seg.type === 'text' || seg.type === 'text_stream' ? seg.content : true))
  const turnCount = segments.filter((seg) => seg.type === 'choice').length + 1

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [segments, streaming])

  return (
    <div className="story-page">
      <div className="story-header">
        <div>
          <p className="story-kicker">Live Story Room</p>
          <h2 className="story-title">{title}</h2>
        </div>
        <button className="exit-btn" onClick={onExit}>New Story</button>
      </div>

      <div className="story-layout">
        <aside className="story-panel">
          <div className="panel-card">
            <span>Genre</span>
            <strong>{session.genre}</strong>
          </div>
          <div className="panel-card">
            <span>Current beat</span>
            <strong>{turnCount}</strong>
          </div>
          <div className="panel-card wide">
            <span>Premise</span>
            <p>{session.premise}</p>
          </div>
          <div className={`panel-status ${streaming ? 'live' : ''}`}>
            <span className="status-dot" />
            {streaming ? 'Generating scene' : 'Awaiting your direction'}
          </div>
        </aside>

        <section className="story-main">
          <div className="segments">
            {error && <div className="story-alert">{error}</div>}

            {visibleSegments.map((seg, i) => (
              <div key={i} className={`segment-card ${seg.type === 'image' ? 'image-card' : ''}`}>
                {(seg.type === 'text' || seg.type === 'text_stream') && (
                  <p className="seg-text">{seg.content}</p>
                )}
                {seg.type === 'image' && (
                  <div className="seg-image">
                    <img src={`data:${seg.mime};base64,${seg.content}`} alt="Story illustration" />
                  </div>
                )}
                {seg.type === 'choice' && (
                  <p className="choice-echo">Last direction: {seg.content}</p>
                )}
              </div>
            ))}

            {streaming && (
              <div className="streaming">
                <span className="dot">◆</span> Luminary is blocking the next scene...
              </div>
            )}
          </div>

          {choices.length > 0 && (
            <div className="choices-wrap">
              <div className="choices-header">
                <span>Choose the next beat</span>
                <p>Push the tone, reveal more of the world, or make the danger worse.</p>
              </div>
              <div className="choices">
                {choices.map((c, i) => (
                  <button key={i} className="choice-btn" onClick={() => makeChoice(c)} disabled={streaming}>
                    <span className="choice-index">0{i + 1}</span>
                    <span>{c}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
      <div ref={bottomRef} />
    </div>
  )
}
