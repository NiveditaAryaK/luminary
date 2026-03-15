import { useState, useEffect, useRef } from 'react'
import './Story.css'

export default function Story({ session, onExit }) {
  const [segments, setSegments] = useState([])
  const [choices, setChoices] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [title, setTitle] = useState(session.title || 'Your Story')
  const [error, setError] = useState('')
  const bottomRef = useRef(null)
  const wsRef = useRef(null)

  useEffect(() => {
    startStory()
    return () => wsRef.current?.close()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [segments, streaming])

  function connectWS(input) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/${session.sessionId}`)
    wsRef.current = ws
    setStreaming(true)
    setChoices([])
    setError('')
    let buf = ''
    let fullText = ''
    let receivedPayload = false
    let closedIntentionally = false

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'text') {
        receivedPayload = true
        buf += msg.content
        fullText += msg.content
        setSegments(s => {
          const last = s[s.length - 1]
          if (last?.type === 'text_stream') return [...s.slice(0,-1), { type:'text_stream', content: buf }]
          return [...s, { type:'text_stream', content: buf }]
        })
      } else if (msg.type === 'image') {
        receivedPayload = true
        buf = ''
        setSegments(s => [...s, { type:'image', content: msg.content, mime: msg.mime_type }])
      } else if (msg.type === 'status') {
        if (msg.content === 'generating') setStreaming(true)
        if (msg.content === 'complete') {
          const parsed = parseChoices(fullText)
          if (parsed.length) setChoices(parsed)
          setStreaming(false)
          closedIntentionally = true
          ws.close()
        }
      } else if (msg.type === 'choices') {
        receivedPayload = true
        setChoices(msg.choices || [])
        setStreaming(false)
        closedIntentionally = true
        ws.close()
      } else if (msg.type === 'title') {
        setTitle(msg.content)
      } else if (msg.type === 'done') {
        setStreaming(false)
        closedIntentionally = true
        ws.close()
      } else if (msg.type === 'system') {
        const titleMatch = /Connected:\s*(.*)$/.exec(msg.content || '')
        if (titleMatch?.[1]) setTitle(titleMatch[1])
      } else if (msg.type === 'error') {
        setError(msg.content || 'Story generation failed.')
        setStreaming(false)
        closedIntentionally = true
        ws.close()
      }
    }
    ws.onopen = () => ws.send(JSON.stringify({ type: 'choice', content: input }))
    ws.onerror = () => {
      if (!closedIntentionally && !receivedPayload) {
        setError('Live story connection failed.')
      }
      setStreaming(false)
    }
    ws.onclose = () => setStreaming(false)
  }

  function startStory() {
    setSegments([])
    connectWS(session.premise)
  }

  function makeChoice(choice) {
    setSegments(s => [...s, { type:'choice', content: choice }])
    connectWS(choice)
  }

  function parseChoices(text) {
    if (!text) return []
    const picks = []
    const direct = []
    const re = /CHOICE_[A-C]\s*:\s*([\s\S]*?)(?=CHOICE_[A-C]\s*:|$)/gi
    let match
    while ((match = re.exec(text)) !== null) {
      const cleaned = match[1].trim().replace(/^[\-\u2022]+/g, '').trim()
      if (cleaned) direct.push(cleaned)
    }
    if (direct.length >= 2) return direct

    const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
    const choiceLines = lines.filter(l => /^CHOICE_[A-C]\s*:/i.test(l))
    const scanLines = choiceLines.length ? choiceLines : lines.slice(-12)
    for (const line of scanLines) {
      const m1 = /^CHOICE_[A-C]\s*:\s*(.+)$/i.exec(line)
      if (m1) { picks.push(m1[1]); continue }
      const m2 = /^Choice\s*[A-C]\s*:\s*(.+)$/i.exec(line)
      if (m2) { picks.push(m2[1]); continue }
      const m3 = /^[A-C]\.\s*(.+)$/.exec(line)
      if (m3) { picks.push(m3[1]); continue }
      const m4 = /^[1-3]\.\s*(.+)$/.exec(line)
      if (m4) { picks.push(m4[1]); continue }
    }
    return picks.length >= 2 ? picks : []
  }

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
