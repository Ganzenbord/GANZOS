#!/bin/bash
#
# Ganz installeren op een Mac. Eén keer nodig; daarna gebruik je start-ganz.command.
#
# Dubbelklik dit bestand. Zegt macOS dat het niet geopend kan worden omdat de ontwikkelaar
# onbekend is: klik het met de rechtermuisknop aan en kies Open, en dan nogmaals Open.

set -euo pipefail
cd "$(dirname "$0")"

# --- Hoe dit er in het venster uitziet ---------------------------------------
rood=$'\033[31m'; groen=$'\033[32m'; geel=$'\033[33m'; dik=$'\033[1m'; uit=$'\033[0m'
stap()  { printf '\n%s==> %s%s\n' "$dik" "$1" "$uit"; }
goed()  { printf '%s  ✓ %s%s\n' "$groen" "$1" "$uit"; }
let_op() { printf '%s  ! %s%s\n' "$geel" "$1" "$uit"; }
stop()  { printf '\n%s  ✗ %s%s\n\n' "$rood" "$1" "$uit"; echo "Los dit op en start dit bestand opnieuw."; exit 1; }

printf '%s\n' "  Ganz installeren"
printf '%s\n' "  ----------------"

# --- Wat er op de Mac moet staan ---------------------------------------------
stap "Kijken wat er al staat"

# Homebrew staat op een Apple-Mac ergens anders dan op een oudere Intel-Mac.
for brew_pad in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$brew_pad" ] && eval "$("$brew_pad" shellenv)" && break
done

command -v brew >/dev/null 2>&1 || stop \
  "Homebrew ontbreekt. Installeer het eerst met de opdracht op https://brew.sh en probeer het daarna opnieuw."
goed "Homebrew gevonden"

# Python 3.12: de versie waar Ganz op getest is.
if ! command -v python3.12 >/dev/null 2>&1; then
  let_op "Python 3.12 ontbreekt; die wordt nu geïnstalleerd (dit duurt even)."
  brew install python@3.12
  eval "$(brew shellenv)"
fi
command -v python3.12 >/dev/null 2>&1 || stop "Python 3.12 is nog steeds niet te vinden."
goed "Python 3.12: $(python3.12 --version)"

if ! command -v node >/dev/null 2>&1; then
  let_op "Node ontbreekt; die wordt nu geïnstalleerd."
  brew install node
  eval "$(brew shellenv)"
fi
command -v node >/dev/null 2>&1 || stop "Node is nog steeds niet te vinden."
goed "Node: $(node --version)"

if ! brew list postgresql@16 >/dev/null 2>&1; then
  let_op "PostgreSQL ontbreekt; die wordt nu geïnstalleerd."
  brew install postgresql@16
fi
# Homebrew zet postgresql@16 niet vanzelf in het pad.
export PATH="$(brew --prefix postgresql@16)/bin:$PATH"
goed "PostgreSQL: $(psql --version)"

stap "De database starten"
brew services start postgresql@16 >/dev/null 2>&1 || true
for _ in $(seq 1 30); do
  pg_isready -q && break
  sleep 1
done
pg_isready -q || stop "PostgreSQL wil niet starten. Kijk met: brew services list"
goed "PostgreSQL draait"

# --- De database zelf ---------------------------------------------------------
stap "De database van Ganz aanmaken"

bestaat_rol=$(psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='ganz'" postgres || echo "")
if [ "$bestaat_rol" = "1" ]; then
  goed "Gebruiker 'ganz' bestaat al"
  # Het wachtwoord staat in .env; dat laten we dan met rust.
  db_wachtwoord=""
else
  db_wachtwoord=$(python3.12 -c "import secrets; print(secrets.token_urlsafe(24))")
  psql -q -c "CREATE ROLE ganz LOGIN PASSWORD '${db_wachtwoord}'" postgres
  goed "Gebruiker 'ganz' aangemaakt"
fi

bestaat_db=$(psql -tAc "SELECT 1 FROM pg_database WHERE datname='ganz'" postgres || echo "")
if [ "$bestaat_db" = "1" ]; then
  goed "Database 'ganz' bestaat al"
else
  createdb -O ganz ganz
  goed "Database 'ganz' aangemaakt"
fi

# --- De instellingen ----------------------------------------------------------
stap "De instellingen klaarzetten"

if [ -f backend/.env ]; then
  goed "backend/.env bestaat al; die blijft zoals hij is"
else
  [ -n "$db_wachtwoord" ] || stop \
    "De database bestond al maar backend/.env niet, dus het databasewachtwoord is onbekend.
   Geef het opnieuw uit met:
     psql -c \"ALTER ROLE ganz PASSWORD 'iets-nieuws'\" postgres
   en zet daarna GANZ_DATABASE_URL in backend/.env."

  geheim=$(python3.12 -c "import secrets; print(secrets.token_urlsafe(48))")
  sleutel=$(python3.12 -c "
import base64, secrets
print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
")
  cp .env.example backend/.env
  # De drie waarden die per installatie verschillen. `sed -i ''` is de macOS-vorm.
  sed -i '' "s|^GANZ_SECRET_KEY=.*|GANZ_SECRET_KEY=${geheim}|" backend/.env
  sed -i '' "s|^GANZ_ENCRYPTION_KEY=.*|GANZ_ENCRYPTION_KEY=${sleutel}|" backend/.env
  sed -i '' "s|^GANZ_DATABASE_URL=.*|GANZ_DATABASE_URL=postgresql+asyncpg://ganz:${db_wachtwoord}@localhost:5432/ganz|" backend/.env
  chmod 600 backend/.env
  goed "backend/.env gemaakt, met eigen sleutels"
  let_op "Bewaar GANZ_ENCRYPTION_KEY ergens veilig. Raak je hem kwijt, dan moet je elke"
  let_op "koppeling (YouTube en de rest) opnieuw maken."
fi

# --- De backend ---------------------------------------------------------------
stap "De backend installeren (dit duurt het langst)"
[ -d backend/.venv ] || python3.12 -m venv backend/.venv
backend/.venv/bin/pip install --quiet --upgrade pip
backend/.venv/bin/pip install --quiet -r backend/requirements.txt
goed "Pakketten van de backend geïnstalleerd"

stap "De database inrichten"
(cd backend && .venv/bin/python -m alembic upgrade head >/dev/null)
goed "Tabellen staan klaar"

# --- Het scherm ---------------------------------------------------------------
stap "Het scherm installeren"
npm install --prefix frontend --silent
goed "Pakketten van het scherm geïnstalleerd"

# --- De eerste gebruiker ------------------------------------------------------
stap "Je eigen account"
aantal=$(psql -tAc "SELECT count(*) FROM users" ganz 2>/dev/null || echo 0)
if [ "$aantal" -gt 0 ]; then
  goed "Er is al een account; dat laten we met rust"
else
  echo "  Ganz heeft één account nodig om mee in te loggen."
  read -r -p "  E-mailadres: " email
  read -r -p "  Je naam: " naam
  (cd backend && .venv/bin/python -m scripts.create_user --email "$email" --name "$naam" --tier 1)
  goed "Account aangemaakt"
fi

printf '\n%s  Klaar.%s\n\n' "$groen" "$uit"
echo "  Start Ganz voortaan met start-ganz.command (dubbelklikken)."
echo
read -r -p "  Druk op Enter om dit venster te sluiten. "
