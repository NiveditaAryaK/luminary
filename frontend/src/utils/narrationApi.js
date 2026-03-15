export async function fetchNarrationVoices() {
  const response = await fetch('/api/narration/voices')
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to load narration voices.')
  }
  return data.voices || []
}

export async function synthesizeNarration(payload) {
  const response = await fetch('/api/narration/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to synthesize narration.')
  }
  return data
}
