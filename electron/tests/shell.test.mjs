/* Wat de desktopschil moet doen, zonder dat er een venster aan te pas komt.
 *
 * Draaien met: node electron/tests/shell.test.mjs
 *
 * Electron zelf laden kan hier niet (dat wil een scherm), en dat hoeft ook niet: de twee
 * stukken die echt beslissingen nemen — waar de backend staat en of die er is — staan met
 * opzet in aparte modules.
 */

import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const hier = path.dirname(fileURLToPath(import.meta.url))
const schil = path.join(hier, '..')
const require = createRequire(path.join(schil, '/'))

const settings = require('./settings.cjs')
const { checkBackend } = require('./backend.cjs')

let goed = 0
function ok(wat) {
  goed += 1
  console.log('  ✓', wat)
}

console.log('waar de backend staat')
{
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ganz-schil-'))
  const nepApp = { getPath: () => tmp }

  assert.equal(settings.apiUrl(nepApp), 'http://localhost:8000')
  ok('zonder instelling: localhost:8000')

  settings.setApiUrl(nepApp, 'http://192.168.1.50:9000/')
  assert.equal(settings.apiUrl(nepApp), 'http://192.168.1.50:9000')
  ok('een ingesteld adres wordt bewaard, zonder slash aan het eind')

  process.env.GANZ_API_URL = 'http://elders:1234'
  assert.equal(settings.apiUrl(nepApp), 'http://elders:1234')
  delete process.env.GANZ_API_URL
  ok('de omgevingsvariabele wint, zonder het bewaarde adres te wissen')

  assert.equal(settings.apiUrl(nepApp), 'http://192.168.1.50:9000')
  ok('en daarna staat het bewaarde adres er nog')

  fs.writeFileSync(path.join(tmp, 'settings.json'), 'dit is geen json')
  assert.equal(settings.apiUrl(nepApp), 'http://localhost:8000')
  ok('een onleesbaar bestand laat de app starten in plaats van struikelen')
}

console.log('\nis er een Ganz op dat adres')
{
  const draait = http.createServer((req, res) => {
    res.writeHead(req.url === '/health' ? 200 : 404, { 'content-type': 'application/json' })
    res.end('{"status":"ok"}')
  })
  const zonderDatabase = http.createServer((_req, res) => {
    res.writeHead(503, { 'content-type': 'application/json' })
    res.end('{"detail":"Geen verbinding met de database. Draait PostgreSQL?"}')
  })
  await new Promise((r) => draait.listen(0, '127.0.0.1', r))
  await new Promise((r) => zonderDatabase.listen(0, '127.0.0.1', r))
  const poortA = draait.address().port
  const poortB = zonderDatabase.address().port

  assert.deepEqual(await checkBackend(`http://127.0.0.1:${poortA}`), { ok: true })
  ok('een draaiende Ganz wordt gevonden')

  const weg = await checkBackend('http://127.0.0.1:1')
  assert.equal(weg.ok, false)
  assert.match(weg.reason, /Draait de backend al/)
  ok('niets op dat adres: zegt wat je moet doen')

  const kapot = await checkBackend(`http://127.0.0.1:${poortB}`)
  assert.equal(kapot.ok, false)
  assert.match(kapot.reason, /PostgreSQL/)
  ok('"database ligt plat" is iets anders dan "niet bereikbaar"')

  const onzin = await checkBackend('geen adres')
  assert.equal(onzin.ok, false)
  assert.match(onzin.reason, /geen geldig adres/)
  ok('een verkeerd ingetypt adres geeft geen crash maar uitleg')

  draait.close()
  zonderDatabase.close()
}

console.log('\nde schil blijft een schil')
{
  const bron = fs.readFileSync(path.join(schil, 'main.cjs'), 'utf8')

  assert.ok(!bron.includes('spawn('), 'main.cjs start nog een proces')
  assert.ok(!bron.includes('child_process'), 'main.cjs gebruikt nog child_process')
  ok('start zelf geen backend')

  assert.ok(bron.includes('offline.html'))
  ok('heeft een uitlegpagina in plaats van een leeg venster')

  assert.ok(bron.includes('did-fail-load'))
  ok('vangt ook een mislukte lading af')

  assert.ok(fs.existsSync(path.join(schil, 'offline.html')))
  const pagina = fs.readFileSync(path.join(schil, 'offline.html'), 'utf8')
  assert.ok(pagina.includes('window.ganz.retry'))
  assert.ok(pagina.includes('window.ganz.setApiUrl'))
  ok('de uitlegpagina kan opnieuw proberen en het adres wijzigen')
}

console.log(`\n${goed} controles goed`)
