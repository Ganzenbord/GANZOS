/* De brug tussen het venster en het hoofdproces.
 *
 * Bewust smal: het venster krijgt geen Node, alleen deze paar functies. Alles wat de app
 * met gegevens doet, loopt over de gewone API. */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('ganz', {
  /** Waar de backend draait. De webversie gebruikt hier een relatief pad voor; in de
   *  desktopschil kan dat niet, want de pagina komt van schijf (file://). */
  apiUrl: () => ipcRenderer.invoke('ganz:api-url'),
  setApiUrl: (url) => ipcRenderer.invoke('ganz:set-api-url', url),
  retry: () => ipcRenderer.invoke('ganz:retry'),
  platform: process.platform,
})
