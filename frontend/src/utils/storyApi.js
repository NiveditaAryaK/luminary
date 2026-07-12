export async function fetchStorySnapshot(sessionId) {
  const response = await fetch(`/api/story/${sessionId}`)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to fetch story snapshot.')
  }
  return data
}

export async function startFilmRender(sessionId, options = {}) {
  const response = await fetch(`/api/story/${sessionId}/film`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to start the film render.')
  }
  return data
}

export async function fetchFilmStatus(sessionId) {
  const response = await fetch(`/api/story/${sessionId}/film/status`)
  if (response.status === 404) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to fetch film status.')
  }
  return data
}

export function filmDownloadUrl(sessionId) {
  return `/api/story/${sessionId}/film/download`
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
