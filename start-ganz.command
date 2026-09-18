#!/bin/bash
#
# Ganz starten op een Mac. Dubbelklik dit bestand.
#
# Er gaan twee dingen draaien: de backend (de database en alle logica) en het scherm. Zolang
# dit venster openstaat, draait Ganz. Sluit je het venster, dan stopt hij.

set -euo pipefail
cd "$(dirname "$0")"

rood=$'\033[31m'; groen=$'\033[32m'; geel=$'\033[33m'; dik=$'\033[1m'; uit=$'\033[0m'
stap()  { printf '\n%s==> %s%s\n' "$dik" "$1" "$uit"; }
goed()  { printf '%s  ✓ %s%s\n' "$groen" "$1" "$uit"; }
let_op() { printf '%s  ! %s%s\n' "$geel" "$1" "$uit"; }
stop()  { printf '\n%s  ✗ %s%s\n\n' "$rood" "$1" "$uit"; read -r -p "  Druk op Enter om te sluiten. "; exit 1; }

printf '%s\n' "  Ganz starten"
printf '%s\n' "  ------------"

for brew_pad in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$brew_pad" ] && eval "$("$brew_pad" shellenv)" && break
done
if command -v brew >/dev/null 2>&1; then
  pg_prefix=$(brew --prefix postgresql@16 2>/dev/null || true)
  [ -n "$pg_prefix" ] && export PATH="$pg_prefix/bin:$PATH"
fi

[ -d backend/.venv ] || stop "Ganz is nog niet geïnstalleerd. Dubbelklik eerst install-ganz.command."
[ -f backend/.env ] || stop "backend/.env ontbreekt. Dubbelklik eerst install-ganz.command."
[ -d frontend/node_modules ] || stop "Het scherm is nog niet geïnstalleerd. Dubbelklik eerst install-ganz.command."

# --- De database --------------------------------------------------------------
stap "De database"
if ! pg_isready -q 2>/dev/null; then
  let_op "PostgreSQL draait niet; hij wordt nu gestart."
  brew services start postgresql@16 >/dev/null 2>&1 || true
  for _ in $(seq 1 30); do pg_isready -q 2>/dev/null && break; sleep 1; done
fi
pg_isready -q 2>/dev/null || stop "PostgreSQL wil niet starten. Kijk met: brew services list"
goed "PostgreSQL draait"

# Migraties die nog niet gedraaid zijn. Na een update staan die er, en dan start de backend
# anders op een database die niet meer klopt.
stap "Bijwerken waar nodig"
mkdir -p logs
(cd backend && .venv/bin/python -m alembic upgrade head) >logs/migratie.log 2>&1 \
  || stop "De database bijwerken mislukte. Wat er misging staat in logs/migratie.log"
goed "Database is bij"

# --- Alles weer netjes stoppen -------------------------------------------------
backend_pid=""
scherm_pid=""

# Job control aan. Daarmee krijgt elk onderdeel dat hieronder start zijn eigen procesgroep,
# en kan `kill -- -PID` de hele groep meenemen. Dat is nodig omdat een programma zelf weer
# kinderen start: dood je alleen de ouder, dan blijft het kind draaien — en dan is poort
# 5173 de volgende keer nog bezet terwijl je denkt dat Ganz uit staat.
set -m

stop_groep() {
  [ -n "$1" ] || return 0
  kill -- -"$1" 2>/dev/null || kill "$1" 2>/dev/null || true
}

opruimen() {
  printf '\n%s==> Ganz stoppen%s\n' "$dik" "$uit"
  stop_groep "$scherm_pid"
  stop_groep "$backend_pid"
  wait 2>/dev/null || true
  goed "Gestopt"
}
trap opruimen EXIT INT TERM

# --- De backend ---------------------------------------------------------------
stap "De backend starten"
for poort in 8000 5173; do
  if lsof -nP -iTCP:"$poort" -sTCP:LISTEN >/dev/null 2>&1; then
    stop "Poort $poort is al bezet. Draait Ganz misschien al in een ander venster?
   Sluit dat venster, of zoek uit wat het is met:
     lsof -nP -iTCP:$poort -sTCP:LISTEN"
  fi
done
(cd backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) \
  >logs/backend.log 2>&1 &
backend_pid=$!

for _ in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then break; fi
  kill -0 "$backend_pid" 2>/dev/null || stop "De backend is meteen gestopt. Wat er misging staat in logs/backend.log"
  sleep 0.5
done
curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 \
  || stop "De backend antwoordt niet. Wat er misging staat in logs/backend.log"
goed "Backend draait op http://localhost:8000"

# --- Het scherm ---------------------------------------------------------------
stap "Het scherm starten"
# Rechtstreeks en niet via `npm run dev`: npm zet er een proces tussen dat bij het stoppen
# blijft hangen, en dan draait het scherm door terwijl Ganz volgens jou uit is.
(cd frontend && exec node_modules/.bin/vite) >logs/scherm.log 2>&1 &
scherm_pid=$!

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:5173/ >/dev/null 2>&1; then break; fi
  kill -0 "$scherm_pid" 2>/dev/null || stop "Het scherm is meteen gestopt. Kijk in logs/scherm.log"
  sleep 0.5
done
curl -fsS http://127.0.0.1:5173/ >/dev/null 2>&1 || stop "Het scherm antwoordt niet. Kijk in logs/scherm.log"
goed "Scherm draait op http://localhost:5173"

open http://localhost:5173 >/dev/null 2>&1 || true

printf '\n%s  Ganz draait.%s\n\n' "$groen" "$uit"
echo "  Het scherm is nu geopend in je browser: http://localhost:5173"
echo
echo "  Wil je hem op je telefoon openen? Stop Ganz (Ctrl-C) en start hem met:"
echo "      npm run dev:telefoon --prefix frontend"
echo "  Alleen op je eigen wifi; zie docs/server.md voor hoe het veilig van buitenaf kan."
echo
printf '%s  Dit venster open laten staan. Ctrl-C of het venster sluiten stopt Ganz.%s\n' "$dik" "$uit"

# Wachten tot een van de twee stopt; de trap ruimt daarna de ander op.
#
# Met opzet geen `wait -n`: die bestaat pas vanaf bash 4.3, en de bash die Apple meelevert
# is 3.2 uit 2007. Dit werkt op allebei.
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$scherm_pid" 2>/dev/null; do
  sleep 1
done
let_op "Een van de twee is gestopt. Kijk in logs/backend.log of logs/scherm.log."
read -r -p "  Druk op Enter om te sluiten. "
