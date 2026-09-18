/* Draait er een Ganz op dit adres?
 *
 * Staat los van main.cjs zodat je hem kunt uitvoeren zonder venster — en zonder Electron.
 * Dat is precies wat je wilt kunnen naspelen: de gevallen waarin er níéts is.
 */

const http = require('node:http')
const https = require('node:https')

const HEALTH_TIMEOUT_MS = 2000

/** Draait er een Ganz op dit adres? Geeft ook terug wat er misging, want dat is wat de
 *  gebruiker moet lezen. */
function checkBackend(apiUrl) {
  return new Promise((resolve) => {
    let target
    try {
      target = new URL('/health', apiUrl)
    } catch {
      resolve({ ok: false, reason: `'${apiUrl}' is geen geldig adres.` })
      return
    }

    const client = target.protocol === 'https:' ? https : http
    const request = client.get(target, { timeout: HEALTH_TIMEOUT_MS }, (response) => {
      let body = ''
      response.on('data', (chunk) => {
        body += chunk
      })
      response.on('end', () => {
        if (response.statusCode === 200) {
          resolve({ ok: true })
          return
        }
        if (response.statusCode === 503) {
          // Ganz leeft, maar zijn database niet. Dat is iets anders dan onbereikbaar, en
          // vraagt om een ander antwoord van de gebruiker.
          let detail = 'De database antwoordt niet.'
          try {
            detail = JSON.parse(body).detail || detail
          } catch {
            /* geen JSON; de algemene melding blijft staan */
          }
          resolve({ ok: false, reason: detail })
          return
        }
        resolve({ ok: false, reason: `Ganz antwoordde met status ${response.statusCode}.` })
      })
    })
    request.on('error', (error) => {
      resolve({
        ok: false,
        reason:
          error.code === 'ECONNREFUSED'
            ? 'Er luistert niets op dit adres. Draait de backend al?'
            : `Geen verbinding: ${error.message}`,
      })
    })
    request.on('timeout', () => {
      request.destroy()
      resolve({ ok: false, reason: 'Geen antwoord binnen twee seconden.' })
    })
  })
}


module.exports = { checkBackend, HEALTH_TIMEOUT_MS }
