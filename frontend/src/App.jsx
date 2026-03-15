import { useState } from 'react'
import Landing from './components/Landing.jsx'
import Story from './components/Story.jsx'

export default function App() {
  const [session, setSession] = useState(null)
  return session
    ? <Story session={session} onExit={() => setSession(null)} />
    : <Landing onStart={setSession} />
}
