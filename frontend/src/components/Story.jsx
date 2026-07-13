import { useEffect, useRef, useState } from 'react'

import { useAuth } from '../hooks/useAuth'
import { useStorySession } from '../hooks/useStorySession'
import { useFilmRender } from '../hooks/useFilmRender'
import { useLiveNarration } from '../hooks/useLiveNarration'
import { useYouTubePublish } from '../hooks/useYouTubePublish'
import { useNarration } from '../hooks/useNarration'
import { useSpeechInput } from '../hooks/useSpeechInput'
import { stripChoiceMarkup } from '../utils/storyText'
import { fetchStorySnapshot } from '../utils/storyApi'

import './Story.css'

const DIRECTOR_MODES = [
  { id: 'cinematic', label: 'Cinematic' },
  { id: 'tender', label: 'Tender' },
  { id: 'suspenseful', label: 'Suspenseful' },
  { id: 'heartbreaking', label: 'Heartbreaking' },
  { id: 'chaotic', label: 'Chaotic' },
]

export default function Story({ session, onExit, onSnapshot }) {
  const {
    choices,
    directorMode,
    error,
    flushNarration,
    makeChoice,
    memory,
    narrationStatus,
    saveVersion,
    segments,
    sendNarration,
    setDirectorMode,
    storyboard,
    streaming,
    title,
  } = useStorySession(session)
  const bottomRef = useRef(null)
  const [direction, setDirection] = useState('')
  const { film, createFilm } = useFilmRender(session.sessionId)
  const { user } = useAuth()
  const {
    configured: youtubeConfigured,
    connected: youtubeConnected,
    connect: connectYouTube,
    publish,
    publishFilm,
  } = useYouTubePublish(session.sessionId, user?.uid)
  const hasIllustratedBeats = storyboard.some((beat) => beat.image)
  const {
    interimTranscript,
    isNarrating,
    startNarrating,
    stopNarrating,
    supported: liveNarrationSupported,
  } = useLiveNarration({
    onChunk: (chunk) => sendNarration(chunk),
  })
  const visibleSegments = segments
    .map((seg) => (
      seg.type === 'text' || seg.type === 'text_stream'
        ? { ...seg, content: stripChoiceMarkup(seg.content) }
        : seg
    ))
    .filter((seg) => (seg.type === 'text' || seg.type === 'text_stream' ? seg.content : true))
  const turnCount = segments.filter((seg) => seg.type === 'choice').length + 1
  const storyboardHistory = storyboard
    .filter((beat) => beat.turn < turnCount)
    .slice(-3)
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
  }, [segments, streaming, interimTranscript, narrationStatus])

  function toggleLiveNarration() {
    if (isNarrating) {
      stopNarrating()
      flushNarration()
    } else {
      startNarrating()
    }
  }

  useEffect(() => {
    if (!onSnapshot || saveVersion === 0) return

    let cancelled = false

    async function syncSnapshot() {
      try {
        const snapshot = await fetchStorySnapshot(session.sessionId)
        if (!cancelled) {
          onSnapshot({
            ...snapshot,
            directorMode,
            savedMemory: memory,
            savedChoices: choices,
            savedStoryboard: storyboard,
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
  }, [choices, directorMode, memory, onSnapshot, saveVersion, segments, session.sessionId, session.storyId, storyboard, title])

  function submitDirection(event) {
    event.preventDefault()
    const nextDirection = direction.trim()
    if (!nextDirection || streaming || isNarrating) return
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
          <div className="panel-card">
            <span>Director mode</span>
            <div className="mode-pills">
              {DIRECTOR_MODES.map((modeOption) => (
                <button
                  key={modeOption.id}
                  className={`mode-pill ${directorMode === modeOption.id ? 'active' : ''}`}
                  type="button"
                  onClick={() => setDirectorMode(modeOption.id)}
                  disabled={streaming}
                >
                  {modeOption.label}
                </button>
              ))}
            </div>
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
          <div className="panel-card">
            <span>Story memory</span>
            <div className="memory-stack">
              {memory.length
                ? memory.map((item) => (
                  <div key={`${item.label}-${item.detail}`} className="memory-card">
                    <strong>{item.label}</strong>
                    <p>{item.detail}</p>
                  </div>
                ))
                : <p className="memory-empty">Luminary will pin the promises, secrets, and emotional anchors it should not forget.</p>}
            </div>
          </div>
        </aside>

        <section className="story-main">
          {liveNarrationSupported && (
            <div className={`narrate-bar ${isNarrating ? 'live' : ''}`}>
              <button
                className={`narrate-toggle ${isNarrating ? 'live' : ''}`}
                type="button"
                onClick={toggleLiveNarration}
                disabled={streaming || isListening}
              >
                <span className="narrate-mic" aria-hidden="true" />
                {isNarrating ? 'Stop narrating' : 'Narrate live'}
              </button>
              <span className="narrate-hint">
                {isNarrating
                  ? narrationStatus === 'illustrating'
                    ? 'Painting the scene…'
                    : 'Listening — tell the story out loud, it appears below as you speak.'
                  : 'Speak the story yourself and Luminary illustrates each scene as you describe it.'}
              </span>
            </div>
          )}

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
                {seg.type === 'narration' && (
                  <>
                    <span className="narration-label">You narrate</span>
                    <p className="seg-text narration-text">{seg.content}</p>
                  </>
                )}
              </div>
            ))}

            {isNarrating && (
              <div className="segment-card narration-live-card">
                <span className="narration-label live">Narrating live</span>
                <p className="seg-text narration-text interim">
                  {interimTranscript || 'Listening…'}
                </p>
              </div>
            )}

            {narrationStatus === 'illustrating' && (
              <div className="streaming narration-illustrating">
                <span className="dot">◆</span> Painting the scene…
              </div>
            )}

            {streaming && (
              <div className="streaming">
                <span className="dot">◆</span> Luminary is blocking the next scene...
              </div>
            )}
          </div>

          {storyboardHistory.length > 0 && (
            <div className="storyboard-strip">
              <div className="choices-header">
                <span>Story so far</span>
                <p>Recent visual beats from earlier scenes.</p>
              </div>
              <div className="storyboard-grid">
                {storyboardHistory.map((beat) => (
                  <article key={`${beat.turn}-${beat.caption}`} className="storyboard-card">
                    {beat.image && (
                      <img
                        src={`data:${beat.mime_type};base64,${beat.image}`}
                        alt={beat.caption || `Storyboard beat ${beat.turn}`}
                      />
                    )}
                    <div className="storyboard-copy">
                      <span>Beat {beat.turn}</span>
                      <p>{beat.caption}</p>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}

          {choices.length > 0 && (
            <div className="choices-wrap">
              <div className="choices-header">
                <span>Choose the next beat</span>
                <p>Push the tone, reveal more of the world, or make the danger worse.</p>
              </div>
              <div className="choices">
                {choices.map((c, i) => (
                  <button key={i} className="choice-btn" onClick={() => makeChoice(c)} disabled={streaming || isNarrating}>
                    <span className="choice-index">0{i + 1}</span>
                    <span>{c}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="film-panel">
            <div className="choices-header">
              <span>Finish story</span>
              <p>Cut the illustrated beats into a narrated short film with title cards and crossfades.</p>
            </div>

            {film.status === 'rendering' && (
              <div className="film-progress">
                <div className="film-progress-track">
                  <div className="film-progress-fill" style={{ width: `${Math.round(film.progress * 100)}%` }} />
                </div>
                <span>{film.message || 'Rendering…'}</span>
              </div>
            )}

            {film.status === 'error' && (
              <div className="story-alert">{film.error}</div>
            )}

            {film.status === 'done' && (
              <div className="film-result">
                <video className="film-player" controls src={film.videoUrl} />
                <div className="film-actions">
                  <a className="film-download" href={film.videoUrl} download>
                    Download MP4
                  </a>
                  {youtubeConfigured && publish.status !== 'done' && (
                    <button
                      className="film-download yt-btn"
                      type="button"
                      onClick={youtubeConnected ? publishFilm : connectYouTube}
                      disabled={publish.status === 'uploading'}
                    >
                      {publish.status === 'uploading'
                        ? `Publishing… ${Math.round(publish.progress * 100)}%`
                        : youtubeConnected
                          ? 'Publish to YouTube'
                          : 'Connect YouTube'}
                    </button>
                  )}
                </div>
                {publish.status === 'done' && (
                  <p className="yt-result">
                    Published to your channel (private) —{' '}
                    <a href={publish.url} target="_blank" rel="noreferrer">{publish.title || 'Watch on YouTube'}</a>
                  </p>
                )}
                {publish.status === 'error' && (
                  <div className="story-alert">{publish.error}</div>
                )}
              </div>
            )}

            <button
              className="film-btn"
              type="button"
              onClick={createFilm}
              disabled={streaming || isNarrating || film.status === 'rendering' || !hasIllustratedBeats}
            >
              {film.status === 'rendering'
                ? 'Rendering film…'
                : film.status === 'done'
                  ? 'Re-render film'
                  : 'Create Film'}
            </button>
            {!hasIllustratedBeats && (
              <p className="film-hint">Play a few scenes first — the film is cut from your storyboard beats.</p>
            )}
          </div>

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
                disabled={streaming || isNarrating}
              />
              {speechInputSupported && (
                <div className="voice-tools inline">
                  <button className={`voice-btn ${isListening ? 'live' : ''}`} onClick={isListening ? stopListening : startListening} type="button" disabled={isNarrating}>
                    {isListening ? 'Stop dictation' : 'Dictate direction'}
                  </button>
                  <span>{isNarrating ? 'Live narration is using the microphone.' : isListening ? 'Listening...' : 'Speak the next direction out loud.'}</span>
                </div>
              )}
              <button className="director-submit" type="submit" disabled={streaming || isNarrating || !direction.trim()}>
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
