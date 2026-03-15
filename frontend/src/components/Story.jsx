import { useState, useEffect, useRef } from 'react'
import './Story.css'

export default function Story({ session, onExit }) {
  const [segments, setSegments] = useState([])
  const [choices, setChoices] = useState([])
  const [streaming, setStreaming] = useState(false)
  const [title, setTitle] = useState(session.title || 'Your Story')
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
    let buf = ''

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'text') {
        buf += msg.content
        setSegments(s => {
          const last = s[s.length - 1]
          if (last?.type === 'text_stream') return [...s.slice(0,-1), { type:'text_stream', content: buf }]
          return [...s, { type:'text_stream', content: buf }]
        })
      } else if (msg.type === 'image') {
        buf = ''
        setSegments(s => [...s, { type:'image', content: msg.content, mime: msg.mime_type }])
      } else if (msg.type === 'choices') {
        setChoices(msg.choices || [])
        setStreaming(false)
        ws.close()
      } else if (msg.type === 'title') {
        setTitle(msg.content)
      } else if (msg.type === 'done') {
        setStreaming(false)
        ws.close()
      }
    }
    ws.onopen = () => ws.send(JSON.stringify({ input }))
    ws.onerror = () => setStreaming(false)
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
    const lines = text.split('\n').filter(l => /choice|^[A-C]\.|^[1-3]\./i.test(l) || l.includes('❧'))
    return lines.length >= 2 ? lines : []
  }

  return (
    <div className="story-page">
      <div className="story-header">
        <h2 className="story-title">{title}</h2>
        <button className="exit-btn" onClick={onExit}>✕ New Story</button>
      </div>
      <div className="segments">
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
