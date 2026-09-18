/* Waar de backend draait, bewaard tussen twee keer opstarten.
 *
 * Eén klein JSON-bestandje in de gebruikersmap van het besturingssysteem. Geen database,
 * geen dependency: het gaat om één regel tekst die je ook met de hand moet kunnen aanpassen
 * als de app niet meer opstart. */

const fs = require('node:fs')
const path = require('node:path')

const DEFAULT_API_URL = 'http://localhost:8000'

function settingsPath(app) {
  return path.join(app.getPath('userData'), 'settings.json')
}

function read(app) {
  try {
    return JSON.parse(fs.readFileSync(settingsPath(app), 'utf8'))
  } catch {
    // Bestaat nog niet, of iemand heeft er iets onleesbaars in gezet. Beide keren: opnieuw
    // beginnen is beter dan weigeren te starten.
    return {}
  }
}

function write(app, values) {
  const file = settingsPath(app)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(values, null, 2), 'utf8')
}

/** De backend-URL: omgeving wint, dan wat er bewaard is, anders de standaard.
 *
 *  De omgevingsvariabele staat bovenaan zodat je hem eenmalig kunt overrulen zonder het
 *  bewaarde adres kwijt te raken. */
function apiUrl(app) {
  const stored = read(app).apiUrl
  return normalise(process.env.GANZ_API_URL || stored || DEFAULT_API_URL)
}

function setApiUrl(app, url) {
  const schoon = normalise(url)
  write(app, { ...read(app), apiUrl: schoon })
  return schoon
}

function normalise(url) {
  return String(url || '').trim().replace(/\/+$/, '') || DEFAULT_API_URL
}

module.exports = { DEFAULT_API_URL, apiUrl, setApiUrl, settingsPath, normalise }
