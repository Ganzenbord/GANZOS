/* De desktopschil van Ganz.
 *
 * Electron toont hetzelfde scherm als de webversie. Staat er een backend in de map
 * (met een virtualomgeving), dan start hij die er zelf bij; draait er al een server
 * op de ingestelde poort, dan sluit hij daarop aan. */

const { app, BrowserWindow, shell } = require('electron')
const { spawn } = require('node:child_process')
const path = require('node:path')
const fs = require('node:fs')
const http = require('node:http')

const API_PORT = Number(process.env.GANZ_PORT || 8000)
const API_HOST = '127.0.0.1'
const DEV_URL = process.env.GANZ_DEV_URL || 'http://localhost:5173'

let backend = null
let mainWindow = null

function backendPython() {
  const root = path.join(__dirname, '..', 'backend')
  // Windows zet de uitvoerbare bestanden in Scripts/, macOS en Linux in bin/.
  const candidates = [
    path.join(root, '.venv', 'bin', 'python'),
    path.join(root, '.venv', 'Scripts', 'python.exe'),
  ]
  return candidates.find((candidate) => fs.existsSync(candidate)) || null
}

function isBackendUp() {
  return new Promise((resolve) => {
    const request = http.get(
      { host: API_HOST, port: API_PORT, path: '/health', timeout: 800 },
      (response) => {
        response.resume()
        resolve(response.statusCode === 200)
      },
    )
    request.on('error', () => resolve(false))
    request.on('timeout', () => {
      request.destroy()
      resolve(false)
    })
  })
}

async function waitForBackend(attempts = 40) {
  for (let i = 0; i < attempts; i += 1) {
    if (await isBackendUp()) return true
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  return false
}

async function startBackend() {
  if (await isBackendUp()) return
  const python = backendPython()
  if (!python) return

  backend = spawn(
    python,
    ['-m', 'uvicorn', 'app.main:app', '--host', API_HOST, '--port', String(API_PORT)],
    {
      cwd: path.join(__dirname, '..', 'backend'),
      // Anders flitsen er op Windows zwarte vensters op bij het starten.
      windowsHide: true,
      stdio: 'ignore',
    },
  )
  backend.on('error', () => {
    backend = null
  })
  await waitForBackend()
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1540,
    height: 980,
    minWidth: 900,
    minHeight: 620,
    backgroundColor: '#080c14',
    title: 'Ganz — Command Center',
    webPreferences: {
      // De schil heeft geen toegang tot Node nodig; alles loopt via de API.
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  const bundled = path.join(__dirname, '..', 'frontend', 'dist', 'index.html')
  if (process.env.GANZ_DEV === '1') {
    mainWindow.loadURL(DEV_URL)
  } else if (fs.existsSync(bundled)) {
    mainWindow.loadFile(bundled)
  } else {
    mainWindow.loadURL(`http://${API_HOST}:${API_PORT}/health`)
  }

  // Externe links horen in de gewone browser, niet in de app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

app.whenReady().then(async () => {
  await startBackend()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (backend) {
    backend.kill()
    backend = null
  }
})
