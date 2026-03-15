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
  const activeSessionRef = useRef(session.sessionId)
  const closedByAppRef = useRef(false)
  const pendingInputsRef = useRef([])
  const streamBufferRef = useRef('')
  const fullTextRef = useRef('')
  const receivedPayloadRef = useRef(false)
  const pingTimerRef = useRef(null)

  useEffect(() => {
    activeSessionRef.current = session.sessionId
  }, [session.sessionId])

  useEffect(() => {
    setSegments(session.savedSegments || [])
    setTitle(session.title || 'Your Story')
    setChoices(session.savedChoices || [])
    setError('')
    streamBufferRef.current = ''
    fullTextRef.current = ''
    receivedPayloadRef.current = false
    pendingInputsRef.current = []
    closeSocket()
    if (session.autoStart !== false) {
      startStory()
    }
    return () => closeSocket()
  }, [session.sessionId])

  function clearPingTimer() {
    if (pingTimerRef.current) {
      window.clearInterval(pingTimerRef.current)
      pingTimerRef.current = null
    }
  }

  function closeSocket() {
    closedByAppRef.current = true
    clearPingTimer()
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }

  function flushPendingInputs(ws) {
    while (pendingInputsRef.current.length > 0 && ws.readyState === WebSocket.OPEN) {
      const nextInput = pendingInputsRef.current.shift()
      ws.send(JSON.stringify({ type: 'choice', content: nextInput }))
    }
  }

  function handleMessage(msg) {
    if (msg.type === 'text') {
      receivedPayloadRef.current = true
      streamBufferRef.current += msg.content
      fullTextRef.current += msg.content
      setSegments((current) => {
        const last = current[current.length - 1]
        if (last?.type === 'text_stream') {
          return [...current.slice(0, -1), { type: 'text_stream', content: streamBufferRef.current }]
        }
        return [...current, { type: 'text_stream', content: streamBufferRef.current }]
      })
      return
    }

    if (msg.type === 'image') {
      receivedPayloadRef.current = true
      streamBufferRef.current = ''
      setSegments((current) => [
        ...current,
        { type: 'image', content: msg.content, mime: msg.mime_type },
      ])
      return
    }

    if (msg.type === 'status') {
      if (msg.content === 'generating') {
        setStreaming(true)
      }
      if (msg.content === 'complete') {
        const parsed = parseChoices(fullTextRef.current)
        if (parsed.length) {
          setChoices(parsed)
        }
        setStreaming(false)
        setSaveVersion((version) => version + 1)
        streamBufferRef.current = ''
        fullTextRef.current = ''
      }
      return
    }

    if (msg.type === 'choices') {
      receivedPayloadRef.current = true
      setChoices(msg.choices || [])
      setStreaming(false)
      return
    }

    if (msg.type === 'title') {
      setTitle(msg.content)
      return
    }

    if (msg.type === 'done') {
      setStreaming(false)
      streamBufferRef.current = ''
      return
    }

    if (msg.type === 'system') {
      const titleMatch = /Connected:\s*(.*)$/.exec(msg.content || '')
      if (titleMatch?.[1]) {
        setTitle(titleMatch[1])
      }
      return
    }

    if (msg.type === 'error') {
      setError(msg.content || 'Story generation failed.')
      setStreaming(false)
    }
  }

  function ensureWS() {
    const current = wsRef.current
    if (current && (current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING)) {
      return current
    }

    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/${session.sessionId}`)
    wsRef.current = ws
    closedByAppRef.current = false

    ws.onmessage = (e) => {
      if (activeSessionRef.current !== session.sessionId || wsRef.current !== ws) return
      const msg = JSON.parse(e.data)
      handleMessage(msg)
    }

    ws.onopen = () => {
      if (activeSessionRef.current !== session.sessionId || wsRef.current !== ws) return
      clearPingTimer()
      pingTimerRef.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 20000)
      flushPendingInputs(ws)
    }

    ws.onerror = () => {
      if (activeSessionRef.current !== session.sessionId || wsRef.current !== ws) return
      if (!closedByAppRef.current && !receivedPayloadRef.current) {
        setError('Live story connection failed.')
      }
      setStreaming(false)
    }

    ws.onclose = () => {
      if (wsRef.current === ws) {
        wsRef.current = null
      }
      clearPingTimer()
      if (activeSessionRef.current !== session.sessionId) return
      setStreaming(false)
      if (!closedByAppRef.current && !receivedPayloadRef.current) {
        setError('Live story connection failed.')
      }
    }

    return ws
  }

  function sendChoice(input) {
    const nextInput = input?.trim()
    if (!nextInput) return

    setStreaming(true)
    setChoices([])
    setError('')
    streamBufferRef.current = ''
    fullTextRef.current = ''
    receivedPayloadRef.current = false
    pendingInputsRef.current.push(nextInput)

    const ws = ensureWS()
    if (ws.readyState === WebSocket.OPEN) {
      flushPendingInputs(ws)
    }
  }

  function startStory() {
    setSegments([])
    sendChoice(session.premise)
  }

  function makeChoice(choice) {
    const nextChoice = choice?.trim()
    if (!nextChoice) return
    setSegments((current) => [...current, { type: 'choice', content: nextChoice }])
    sendChoice(nextChoice)
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
