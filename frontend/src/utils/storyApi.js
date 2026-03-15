export async function fetchStorySnapshot(sessionId) {
  const response = await fetch(`/api/story/${sessionId}`)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to fetch story snapshot.')
  }
  return data
}

export async function restoreStorySession(snapshot) {
  const response = await fetch('/api/story/restore', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(snapshot),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to restore story session.')
  }
  return data
}
