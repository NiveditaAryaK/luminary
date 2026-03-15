import { useEffect, useRef, useState } from 'react'

import { parseChoices } from '../utils/storyChoices'

export function useStorySession(session) {
  const [segments, setSegments] = useState(session.savedSegments || [])
  const [choices, setChoices] = useState(session.savedChoices || [])
  const [streaming, setStreaming] = useState(false)
  const [title, setTitle] = useState(session.title || 'Your Story')
  const [error, setError] = useState('')
  const [saveVersion, setSaveVersion] = useState(0)
  const wsRef = useRef(null)
  const requestRef = useRef(0)

  useEffect(() => {
    setSegments(session.savedSegments || [])
    setTitle(session.title || 'Your Story')
    setChoices(session.savedChoices || [])
    setError('')
    if (session.autoStart !== false) {
      startStory()
    }
    return () => wsRef.current?.close()
  }, [session.sessionId])

  function connectWS(input) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/${session.sessionId}`)
    const requestId = ++requestRef.current
    wsRef.current = ws

    setStreaming(true)
    setChoices([])
    setError('')

    let buf = ''
    let fullText = ''
    let receivedPayload = false
    let closedIntentionally = false
    const isActiveSocket = () => wsRef.current === ws && requestRef.current === requestId

    ws.onmessage = (e) => {
      if (!isActiveSocket()) return
      const msg = JSON.parse(e.data)

      if (msg.type === 'text') {
        receivedPayload = true
        buf += msg.content
        fullText += msg.content
        setSegments((current) => {
          const last = current[current.length - 1]
          if (last?.type === 'text_stream') {
            return [...current.slice(0, -1), { type: 'text_stream', content: buf }]
          }
          return [...current, { type: 'text_stream', content: buf }]
        })
        return
      }

      if (msg.type === 'image') {
        receivedPayload = true
        buf = ''
        setSegments((current) => [
          ...current,
          { type: 'image', content: msg.content, mime: msg.mime_type },
        ])
        return
      }

      if (msg.type === 'status') {
        if (msg.content === 'generating') setStreaming(true)
        if (msg.content === 'complete') {
          const parsed = parseChoices(fullText)
          if (parsed.length) setChoices(parsed)
          setStreaming(false)
          setSaveVersion((version) => version + 1)
          closedIntentionally = true
          ws.close()
        }
        return
      }

      if (msg.type === 'choices') {
        receivedPayload = true
        setChoices(msg.choices || [])
        setStreaming(false)
        closedIntentionally = true
        ws.close()
        return
      }

      if (msg.type === 'title') {
        setTitle(msg.content)
        return
      }

      if (msg.type === 'done') {
        setStreaming(false)
        closedIntentionally = true
        ws.close()
        return
      }

      if (msg.type === 'system') {
        const titleMatch = /Connected:\s*(.*)$/.exec(msg.content || '')
        if (titleMatch?.[1]) setTitle(titleMatch[1])
        return
      }

      if (msg.type === 'error') {
        setError(msg.content || 'Story generation failed.')
        setStreaming(false)
        closedIntentionally = true
        ws.close()
      }
    }

    ws.onopen = () => ws.send(JSON.stringify({ type: 'choice', content: input }))
    ws.onerror = () => {
      if (!isActiveSocket()) return
      if (!closedIntentionally && !receivedPayload) {
        setError('Live story connection failed.')
      }
      setStreaming(false)
    }
    ws.onclose = () => {
      if (!isActiveSocket()) return
      setStreaming(false)
    }
  }

  function startStory() {
    setSegments([])
    connectWS(session.premise)
  }

  function makeChoice(choice) {
    const nextChoice = choice?.trim()
    if (!nextChoice) return
    setSegments((current) => [...current, { type: 'choice', content: nextChoice }])
    connectWS(nextChoice)
  }

  return {
    choices,
    error,
    makeChoice,
    saveVersion,
    segments,
    streaming,
    title,
  }
}
