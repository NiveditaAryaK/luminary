import { useEffect, useMemo, useRef, useState } from 'react'

// Continuous speech capture for live narration mode. Unlike useSpeechInput's
// one-shot dictation, this keeps the microphone open across pauses by
// restarting recognition whenever the browser ends it, and reports each
// finalized transcript chunk through onChunk while exposing the interim
// (still-being-spoken) transcript for live display.
export function useLiveNarration({ onChunk } = {}) {
  const recognitionRef = useRef(null)
  const activeRef = useRef(false)
  const onChunkRef = useRef(onChunk)
  const [isNarrating, setIsNarrating] = useState(false)
  const [interimTranscript, setInterimTranscript] = useState('')
  const supported = useMemo(
    () => typeof window !== 'undefined' && Boolean(window.SpeechRecognition || window.webkitSpeechRecognition),
    []
  )

  useEffect(() => {
    onChunkRef.current = onChunk
  }, [onChunk])

  useEffect(() => () => {
    activeRef.current = false
    recognitionRef.current?.stop()
  }, [])

  function startRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SpeechRecognition()
    recognition.lang = 'en-US'
    recognition.interimResults = true
    recognition.continuous = true

    recognition.onresult = (event) => {
      let interim = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i]
        const transcript = result[0]?.transcript || ''
        if (result.isFinal) {
          const chunk = transcript.trim()
          if (chunk) onChunkRef.current?.(chunk)
        } else {
          interim += transcript
        }
      }
      setInterimTranscript(interim.trim())
    }

    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        activeRef.current = false
        setIsNarrating(false)
        setInterimTranscript('')
      }
      // Other errors (no-speech, network, aborted) fall through to onend,
      // which restarts recognition while narration is still active.
    }

    recognition.onend = () => {
      setInterimTranscript('')
      if (recognitionRef.current !== recognition) return
      if (activeRef.current) {
        // Browsers end continuous recognition after silence; reopen with a
        // fresh instance since restarting an ended one is unreliable.
        startRecognition()
      } else {
        setIsNarrating(false)
      }
    }

    recognitionRef.current = recognition
    try {
      recognition.start()
    } catch {
      activeRef.current = false
      setIsNarrating(false)
    }
  }

  function startNarrating() {
    if (!supported || activeRef.current) return
    activeRef.current = true
    setIsNarrating(true)
    setInterimTranscript('')
    startRecognition()
  }

  function stopNarrating() {
    activeRef.current = false
    setIsNarrating(false)
    setInterimTranscript('')
    recognitionRef.current?.stop()
  }

  return {
    interimTranscript,
    isNarrating,
    startNarrating,
    stopNarrating,
    supported,
  }
}
