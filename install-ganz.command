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

# Of er een wachtwoord nodig is, hangt niet af van de rol maar van backend/.env: dáár staat
# de verbinding in. Staat die er niet, dan moeten we er een kunnen zetten — ook als de rol
# al bestaat. Eerder stopte het script in dat geval met huiswerk ("geef het wachtwoord
# opnieuw uit"), en dat overkomt precies iedereen die Ganz opnieuw ophaalt naast een
# database van een eerdere poging.
bestaat_rol=$(psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='ganz'" postgres || echo "")

if [ -f backend/.env ]; then
  db_wachtwoord=""
else
  db_wachtwoord=$(python3.12 -c "import secrets; print(secrets.token_urlsafe(24))")
fi

if [ "$bestaat_rol" = "1" ] && [ -n "$db_wachtwoord" ]; then
  # De rol bestaat, maar niets weet nog welk wachtwoord erbij hoort. Een nieuw wachtwoord
  # uitgeven kan geen kwaad: er zijn geen gegevens die eraan hangen, alleen toegang.
  psql -q -c "ALTER ROLE ganz LOGIN PASSWORD '${db_wachtwoord}'" postgres
  goed "Gebruiker 'ganz' bestond al; nieuw wachtwoord uitgegeven"
  let_op "Draait er elders nog een Ganz op dezelfde database, dan moet die een nieuwe"
  let_op "GANZ_DATABASE_URL krijgen."
elif [ "$bestaat_rol" = "1" ]; then
  goed "Gebruiker 'ganz' bestaat al"
elif [ -n "$db_wachtwoord" ]; then
  psql -q -c "CREATE ROLE ganz LOGIN PASSWORD '${db_wachtwoord}'" postgres
  goed "Gebruiker 'ganz' aangemaakt"
else
  # backend/.env bestaat wél maar de rol niet: dan wijst dat bestand naar een database die
  # er niet is, en het wachtwoord erin kennen we niet. Dit is het enige geval dat niet
  # zonder jou op te lossen is.
  stop "backend/.env bestaat, maar de databasegebruiker 'ganz' niet.
   Dat bestand wijst dus naar een database die er niet meer is.
   Makkelijkste oplossing: hernoem backend/.env naar backend/.env.oud en start dit
   bestand opnieuw. Je maakt dan nieuwe sleutels aan, en elke koppeling (YouTube en de
   rest) moet daarna opnieuw."
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
