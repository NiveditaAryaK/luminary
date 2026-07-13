import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchPublishStatus,
  fetchYouTubeStatus,
  startPublish,
  youtubeConnectUrl,
} from '../utils/storyApi'

const POLL_MS = 3000

function fallbackUid() {
  let uid = window.localStorage.getItem('luminary-publish-id')
  if (!uid) {
    uid = crypto.randomUUID()
    window.localStorage.setItem('luminary-publish-id', uid)
  }
  return uid
}

export function useYouTubePublish(sessionId, userId) {
  const uid = userId || fallbackUid()
  const [configured, setConfigured] = useState(false)
  const [connected, setConnected] = useState(false)
  const [publish, setPublish] = useState({ status: 'idle', progress: 0, url: '', title: '', error: '' })
  const pollRef = useRef(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      const status = await fetchYouTubeStatus(uid)
      setConfigured(Boolean(status.configured))
      setConnected(Boolean(status.connected))
    } catch {
      setConfigured(false)
    }
  }, [uid])

  const applyJob = useCallback((job) => {
    if (!job) return
    if (job.status === 'done') {
      stopPolling()
      setPublish({ status: 'done', progress: 1, url: job.url || '', title: job.title || '', error: '' })
    } else if (job.status === 'error') {
      stopPolling()
      setPublish({ status: 'error', progress: 0, url: '', title: '', error: job.error || 'Upload failed.' })
    } else {
      setPublish({ status: 'uploading', progress: job.progress || 0, url: '', title: job.title || '', error: '' })
    }
  }, [stopPolling])

  const startPolling = useCallback(() => {
    stopPolling()
    pollRef.current = window.setInterval(async () => {
      try {
        applyJob(await fetchPublishStatus(sessionId))
      } catch (err) {
        console.error('Publish status poll failed', err)
      }
    }, POLL_MS)
  }, [applyJob, sessionId, stopPolling])

  useEffect(() => {
    setPublish({ status: 'idle', progress: 0, url: '', title: '', error: '' })
    stopPolling()
    refreshStatus()

    fetchPublishStatus(sessionId)
      .then((job) => {
        if (!job) return
        applyJob(job)
        if (job.status === 'queued' || job.status === 'uploading') {
          startPolling()
        }
      })
      .catch(() => {})

    function onMessage(event) {
      if (event.data === 'yt-oauth-done') {
        refreshStatus()
      }
    }
    window.addEventListener('message', onMessage)
    return () => {
      window.removeEventListener('message', onMessage)
      stopPolling()
    }
  }, [applyJob, refreshStatus, sessionId, startPolling, stopPolling])

  const connect = useCallback(() => {
    window.open(
      youtubeConnectUrl(uid),
      'luminary-youtube-auth',
      'width=520,height=680,menubar=no,toolbar=no',
    )
  }, [uid])

  const publishFilm = useCallback(async () => {
    setPublish({ status: 'uploading', progress: 0, url: '', title: '', error: '' })
    try {
      const job = await startPublish(sessionId, uid)
      applyJob(job)
      startPolling()
    } catch (err) {
      stopPolling()
      setPublish({ status: 'error', progress: 0, url: '', title: '', error: err.message })
    }
  }, [applyJob, sessionId, startPolling, stopPolling, uid])

  return { configured, connected, connect, publish, publishFilm }
}
