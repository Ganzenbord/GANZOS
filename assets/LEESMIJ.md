# Pictogram en logo

- `logo.jpeg` — het logo zoals het is aangeleverd: de gans in een donkerblauwe cirkel op wit.
- `icon.png` — waar de app zijn pictogram uit haalt (1024 × 1024). Electron-builder maakt
  hier zelf een `.icns` voor macOS en een `.ico` voor Windows van; zie `directories.buildResources`
  in `package.json`.

`icon.png` is `logo.jpeg` met de witte rand eraf: de cirkel is uitgesneden en het vierkant
eromheen heeft dezelfde donkerblauwe kleur (`#102030`), zodat het pictogram op een taakbalk
een vol vierkant is in plaats van een witte tegel met een cirkel erin. De uitsnede loopt een
paar pixels binnen de rand, want een jpeg laat op zo'n harde overgang een lichte kartelrand
achter en die zie je terug als een dun ringetje.

Komt er ooit een nieuw logo, dan is dat hetzelfde kunstje: cirkel uitsnijden, vierkant
eromheen in de kleur van de cirkel, 1024 × 1024 opslaan als `icon.png`.
