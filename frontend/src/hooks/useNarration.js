import { useEffect, useMemo, useRef, useState } from 'react'

import { fetchNarrationVoices, synthesizeNarration } from '../utils/narrationApi'

const CLOUD_CHAR_BUDGET = 50000
const STORAGE_KEY = 'luminary_tts_usage_chars'

export function useNarration(text, genre) {
  const synth = useMemo(
    () => (typeof window !== 'undefined' ? window.speechSynthesis : null),
    []
  )
  const utteranceRef = useRef(null)
  const audioRef = useRef(null)
  const [voices, setVoices] = useState([])
  const [selectedVoice, setSelectedVoice] = useState('')
  const [volume, setVolume] = useState(0.9)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [mode, setMode] = useState('browser')
  const [cloudAvailable, setCloudAvailable] = useState(false)
  const [cloudCharsUsed, setCloudCharsUsed] = useState(() => {
    if (typeof window === 'undefined') return 0
    return Number(window.localStorage.getItem(STORAGE_KEY) || 0)
  })
  const cloudBudgetReached = cloudCharsUsed >= CLOUD_CHAR_BUDGET

  useEffect(() => {
    let cancelled = false

    async function loadCloudVoices() {
      try {
        const cloudVoices = await fetchNarrationVoices()
        if (!cancelled && cloudVoices.length) {
          setCloudAvailable(true)
          setVoices(cloudVoices)
          setSelectedVoice((current) => current || cloudVoices[0].name)
          setMode(cloudBudgetReached ? 'browser' : 'cloud')
        }
      } catch {
        setCloudAvailable(false)
        setMode('browser')
      }
    }

    loadCloudVoices()

    if (!synth) return () => {
      cancelled = true
    }

    function loadVoices() {
      if (mode === 'cloud') return
      const nextVoices = synth.getVoices().filter((voice) => voice.lang?.toLowerCase().startsWith('en'))
      setVoices(nextVoices)
      if (!selectedVoice && nextVoices.length) {
        const preferred = nextVoices.find((voice) => /google|samantha|aria|zira|davis/i.test(voice.name))
        setSelectedVoice((preferred || nextVoices[0]).name)
      }
    }

    loadVoices()
    synth.onvoiceschanged = loadVoices

    return () => {
      cancelled = true
      synth.onvoiceschanged = null
    }
  }, [cloudBudgetReached, mode, selectedVoice, synth])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(STORAGE_KEY, String(cloudCharsUsed))
    if (cloudBudgetReached) {
      setMode('browser')
    }
  }, [cloudBudgetReached, cloudCharsUsed])

  useEffect(() => {
    return () => {
      synth?.cancel()
      if (audioRef.current) {
        audioRef.current.pause()
        URL.revokeObjectURL(audioRef.current.src)
      }
    }
  }, [synth])

  async function speak() {
    if (!text?.trim()) return

    if (mode === 'cloud' && !cloudBudgetReached) {
      try {
        setIsSpeaking(true)
        const data = await synthesizeNarration({
          genre,
          text,
          voice_name: selectedVoice || undefined,
        })
        setCloudCharsUsed((current) => current + (data.characters_used || 0))
        const binary = atob(data.audio_base64)
        const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0))
        const blob = new Blob([bytes], { type: data.mime_type || 'audio/mpeg' })
        const url = URL.createObjectURL(blob)
        if (audioRef.current?.src) {
          URL.revokeObjectURL(audioRef.current.src)
        }
        const audio = new Audio(url)
        audio.volume = volume
        audio.onended = () => setIsSpeaking(false)
        audio.onerror = () => setIsSpeaking(false)
        audioRef.current = audio
        await audio.play()
        return
      } catch {
        setMode('browser')
      }
    }

    if (!synth) return

    synth.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    const voice = voices.find((entry) => entry.name === selectedVoice)
    if (voice) utterance.voice = voice
    utterance.volume = volume
    utterance.rate = 1
    utterance.pitch = 1
    utterance.onstart = () => setIsSpeaking(true)
    utterance.onend = () => setIsSpeaking(false)
    utterance.onerror = () => setIsSpeaking(false)
    utteranceRef.current = utterance
    synth.speak(utterance)
  }

  function stop() {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
    }
    synth?.cancel()
    setIsSpeaking(false)
  }

  return {
    cloudAvailable,
    cloudBudgetReached,
    cloudCharsUsed,
    isSpeaking,
    selectedVoice,
    setSelectedVoice,
    setVolume,
    speak,
    stop,
    supported: Boolean(synth),
    voices,
    volume,
    mode,
    cloudCharBudget: CLOUD_CHAR_BUDGET,
  }
}
