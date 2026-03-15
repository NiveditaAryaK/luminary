import { useEffect, useRef, useState } from 'react'

import { useStorySession } from '../hooks/useStorySession'
import { useNarration } from '../hooks/useNarration'
import { useSpeechInput } from '../hooks/useSpeechInput'
import { stripChoiceMarkup } from '../utils/storyText'
import { fetchStorySnapshot } from '../utils/storyApi'

import './Story.css'

export default function Story({ session, onExit, onSnapshot }) {
  const { choices, error, makeChoice, saveVersion, segments, streaming, title } = useStorySession(session)
  const bottomRef = useRef(null)
  const [direction, setDirection] = useState('')
  const visibleSegments = segments
    .map((seg) => (
      seg.type === 'text' || seg.type === 'text_stream'
        ? { ...seg, content: stripChoiceMarkup(seg.content) }
        : seg
    ))
    .filter((seg) => (seg.type === 'text' || seg.type === 'text_stream' ? seg.content : true))
  const turnCount = segments.filter((seg) => seg.type === 'choice').length + 1
  const latestNarration = [...visibleSegments]
    .reverse()
    .find((seg) => seg.type === 'text' || seg.type === 'text_stream')?.content || ''
  const {
    cloudAvailable,
    cloudBudgetReached,
    cloudCharBudget,
    cloudCharsUsed,
    isSpeaking,
    mode,
    selectedVoice,
    setSelectedVoice,
    setVolume,
    speak,
    stop,
    supported: narrationSupported,
    voices,
    volume,
  } = useNarration(latestNarration, session.genre)
  const {
    isListening,
    startListening,
    stopListening,
    supported: speechInputSupported,
  } = useSpeechInput({
    onResult: (value) => setDirection(value),
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [segments, streaming])

  useEffect(() => {
    if (!onSnapshot || saveVersion === 0) return

    let cancelled = false

    async function syncSnapshot() {
      try {
        const snapshot = await fetchStorySnapshot(session.sessionId)
        if (!cancelled) {
          onSnapshot({
            ...snapshot,
            savedChoices: choices,
            storyId: session.storyId || snapshot.session_id,
            savedSegments: segments,
            title,
          })
        }
      } catch (err) {
        console.error('Failed to sync story snapshot', err)
      }
    }

    syncSnapshot()

    return () => {
      cancelled = true
    }
  }, [choices, onSnapshot, saveVersion, segments, session.sessionId, session.storyId, title])

  function submitDirection(event) {
    event.preventDefault()
    const nextDirection = direction.trim()
    if (!nextDirection || streaming) return
    makeChoice(nextDirection)
    setDirection('')
  }

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
          {narrationSupported && (
            <div className="panel-card">
              <span>Narration</span>
              <p className="narration-mode">
                {mode === 'cloud'
                  ? 'Cloud voice with SSML modulation'
                  : cloudAvailable
                    ? 'Browser voice fallback'
                    : 'Local browser voice. Enable Cloud TTS billing and credentials for cinematic modulation.'}
              </p>
              {cloudAvailable && (
                <p className="narration-budget">
                  {cloudBudgetReached
                    ? `Cloud narration limit reached (${cloudCharsUsed}/${cloudCharBudget} chars). Using local voice now.`
                    : `Cloud narration budget: ${cloudCharsUsed}/${cloudCharBudget} chars used.`}
                </p>
              )}
              <div className="voice-stack">
                <button className={`voice-action ${isSpeaking ? 'live' : ''}`} onClick={isSpeaking ? stop : speak} type="button">
                  {isSpeaking ? 'Stop voice' : 'Play voice'}
                </button>
                <select className="voice-select" value={selectedVoice} onChange={(e) => setSelectedVoice(e.target.value)}>
                  {voices.map((voice) => (
                    <option key={`${voice.name}-${voice.lang}`} value={voice.name}>
                      {voice.name}
                    </option>
                  ))}
                </select>
                <label className="voice-range">
                  <span>Volume</span>
                  <input type="range" min="0" max="1" step="0.05" value={volume} onChange={(e) => setVolume(Number(e.target.value))} />
                </label>
              </div>
            </div>
          )}
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

          <form className="director-box" onSubmit={submitDirection}>
            <div className="choices-header">
              <span>Direct the next scene</span>
              <p>Type your own instruction if you want to steer the story beyond the suggested branches.</p>
            </div>
            <div className="director-row">
              <textarea
                className="director-input"
                placeholder="Example: Follow the staircase into the moonlight, but keep the telescope recording everything."
                value={direction}
                onChange={(e) => setDirection(e.target.value)}
                disabled={streaming}
              />
              {speechInputSupported && (
                <div className="voice-tools inline">
                  <button className={`voice-btn ${isListening ? 'live' : ''}`} onClick={isListening ? stopListening : startListening} type="button">
                    {isListening ? 'Stop dictation' : 'Dictate direction'}
                  </button>
                  <span>{isListening ? 'Listening...' : 'Speak the next direction out loud.'}</span>
                </div>
              )}
              <button className="director-submit" type="submit" disabled={streaming || !direction.trim()}>
                Send Direction
              </button>
            </div>
          </form>
        </section>
      </div>
      <div ref={bottomRef} />
    </div>
  )
}
