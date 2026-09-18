/* De desktopschil van Ganz.
 *
 * Alleen een schil: hij start geen backend en doet zelf niets met gegevens. Hij zoekt een
 * draaiende Ganz op het ingestelde adres en toont het scherm. Is die er niet, dan komt er
 * een pagina die zegt wat eraan scheelt — nooit een wit venster.
 *
 * Eerder startte deze schil de backend zelf op als er een virtualomgeving in de map stond.
 * Dat leek handig maar maakt de schil verantwoordelijk voor iets wat hij niet kan overzien:
 * welke Python, welke database, welke migraties. De backend start je nu zelf (of hij draait
 * al als dienst), en de schil sluit erop aan.
 */

const { app, BrowserWindow, ipcMain, shell } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const settings = require('./settings.cjs')
const { checkBackend } = require('./backend.cjs')

const DEV_URL = process.env.GANZ_DEV_URL || 'http://localhost:5173'

let mainWindow = null

function bundledIndex() {
  return path.join(__dirname, '..', 'frontend', 'dist', 'index.html')
}

/** Laad het scherm, of de uitlegpagina als er iets niet klopt. */
async function loadApp(window) {
  const apiUrl = settings.apiUrl(app)
  const health = await checkBackend(apiUrl)

  if (!health.ok) {
    await showOffline(window, apiUrl, health.reason)
    return
  }

  if (process.env.GANZ_DEV === '1') {
    await window.loadURL(DEV_URL)
    return
  }
  if (fs.existsSync(bundledIndex())) {
    await window.loadFile(bundledIndex())
    return
  }
  // Wel een backend, geen gebouwd scherm. Ook dat is iets om uit te leggen in plaats van
  // een leeg venster te tonen.
  await showOffline(
    window,
    apiUrl,
    'Het scherm is nog niet gebouwd. Draai eerst: npm run build:frontend',
  )
}

function showOffline(window, apiUrl, reason) {
  return window.loadFile(path.join(__dirname, 'offline.html'), {
    query: { api: apiUrl, reason: reason || 'Onbekende oorzaak' },
  })
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
      // De schil heeft geen Node nodig; alles loopt via de API.
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  })

  // Externe links horen in de gewone browser, niet in de app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Laadt het scherm niet (netwerk weg, adres verkeerd), dan alsnog de uitlegpagina in
  // plaats van het lege venster dat Electron anders laat staan.
  mainWindow.webContents.on('did-fail-load', (_event, code, description, url, isMainFrame) => {
    if (!isMainFrame || code === -3) return // -3 = door ons afgebroken
    void showOffline(mainWindow, settings.apiUrl(app), `Het scherm laadde niet: ${description}`)
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  return mainWindow
}

ipcMain.handle('ganz:api-url', () => settings.apiUrl(app))

ipcMain.handle('ganz:set-api-url', async (_event, url) => {
  const schoon = settings.setApiUrl(app, url)
  return { apiUrl: schoon, health: await checkBackend(schoon) }
})

ipcMain.handle('ganz:retry', async () => {
  if (mainWindow) await loadApp(mainWindow)
})

app.whenReady().then(async () => {
  const window = createWindow()
  await loadApp(window)

  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      await loadApp(createWindow())
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
