import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchFilmStatus, filmDownloadUrl, startFilmRender } from '../utils/storyApi'

const POLL_MS = 2500

const IDLE = { status: 'idle', progress: 0, message: '', error: '', videoUrl: '' }

export function useFilmRender(sessionId) {
  const [film, setFilm] = useState(IDLE)
  const pollRef = useRef(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const applyJob = useCallback((job) => {
    if (!job) return
    if (job.status === 'done') {
      stopPolling()
      setFilm({
        status: 'done',
        progress: 1,
        message: job.message || 'Film ready',
        error: '',
        videoUrl: `${filmDownloadUrl(sessionId)}?v=${job.job_id}`,
      })
    } else if (job.status === 'error') {
      stopPolling()
      setFilm({ ...IDLE, status: 'error', error: job.error || 'The film render failed.' })
    } else {
      setFilm({
        status: 'rendering',
        progress: job.progress || 0,
        message: job.message || 'Rendering…',
        error: '',
        videoUrl: '',
      })
    }
  }, [sessionId, stopPolling])

  const startPolling = useCallback(() => {
    stopPolling()
    pollRef.current = window.setInterval(async () => {
      try {
        const job = await fetchFilmStatus(sessionId)
        applyJob(job)
      } catch (err) {
        console.error('Film status poll failed', err)
      }
    }, POLL_MS)
  }, [applyJob, sessionId, stopPolling])

  // Pick up an in-flight or finished render when the page (re)loads.
  useEffect(() => {
    let cancelled = false
    setFilm(IDLE)
    stopPolling()

    fetchFilmStatus(sessionId)
      .then((job) => {
        if (cancelled || !job) return
        applyJob(job)
        if (job.status === 'queued' || job.status === 'rendering') {
          startPolling()
        }
      })
      .catch(() => {})

    return () => {
      cancelled = true
      stopPolling()
    }
  }, [applyJob, sessionId, startPolling, stopPolling])

  const createFilm = useCallback(async () => {
    setFilm({ ...IDLE, status: 'rendering', message: 'Starting render…' })
    try {
      const job = await startFilmRender(sessionId)
      applyJob(job)
      startPolling()
    } catch (err) {
      stopPolling()
      setFilm({ ...IDLE, status: 'error', error: err.message })
    }
  }, [applyJob, sessionId, startPolling, stopPolling])

  return { film, createFilm }
}
