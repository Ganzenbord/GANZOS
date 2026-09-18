import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { resolveApiBase } from './api/client'
import './styles/theme.css'

/* Eerst vragen waar de backend draait, dan pas tekenen.
 *
 * In de browser is dat meteen bekend (`/api` op dezelfde host). In de desktopschil moet het
 * bij Electron opgehaald worden, en dat gaat over IPC — dus asynchroon. Zou React alvast
 * beginnen, dan vertrekt het eerste verzoek naar een adres dat nog niet klopt. */
void resolveApiBase().finally(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
