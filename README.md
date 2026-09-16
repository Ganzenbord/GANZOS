# Ganz — Command Center

Een persoonlijk AI Command Center. Eén scherm dat antwoord geeft op:

1. Wat moet ik vandaag nog doen?
2. Hoeveel geld heb ik in totaal?
3. Hoe presteren mijn social-kanalen samen?
4. Wanneer gaat de volgende upload eruit?
5. Draait alles nog?

FastAPI + PostgreSQL aan de achterkant, React + Vite aan de voorkant, en een
Electron-schil zodat het ook gewoon een programma op je computer is.

---

## Wat je zelf moet regelen

Ganz kan geen accounts voor je aanmaken en geen sleutels voor je opvragen. Dit moet je
zelf doen, en alleen voor de onderdelen die je wilt gebruiken:

| Wat | Waar | Waarvoor |
| --- | --- | --- |
| PostgreSQL-database | je eigen server of computer | alles |
| YouTube API-sleutel | Google Cloud Console → YouTube Data API v3 | kanaalstatistieken |
| YouTube OAuth-client | Google Cloud Console, scope `yt-analytics-monetary` | omzetcijfers |
| Instagram-token | Meta for Developers → Instagram Graph API | volgers en berichten |
| TikTok-token | TikTok for Developers → Display API | volgers, likes, video's |

Wisselkoersen (ECB via frankfurter.app) en cryptokoersen (CoinGecko) werken **zonder**
sleutel. Voor gewone bankrekeningen is er de handmatige provider: je vult het bedrag
zelf in, en Ganz laat eerlijk zien wanneer dat voor het laatst gebeurde.

Sleutels vul je in via het scherm, niet in een bestand. Ze gaan versleuteld de database
in en komen nooit terug op je scherm.

---

## Installeren

### 1. Database

```bash
createdb ganz
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example .env
```

Open `backend/.env` en vul twee sleutels in. Maak ze met deze commando's:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

De eerste is `GANZ_SECRET_KEY`, de tweede `GANZ_ENCRYPTION_KEY`. Bewaar die tweede goed:
wissel je hem, dan moet je alle koppelingen opnieuw maken.

Daarna de tabellen aanmaken en jezelf toevoegen:

```bash
alembic upgrade head
python -m scripts.create_user --email jij@example.com --name Stef --tier 1
uvicorn app.main:app --reload
```

De API draait nu op http://127.0.0.1:8000 (documentatie op `/docs`).

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 en log in.

### 4. Desktop-app (optioneel)

```bash
npm install
npm run build:frontend
npm run app
```

Draait er nog geen backend, dan start Electron hem er zelf bij vanuit
`backend/.venv`.

---

## Instellingen

Alles via omgevingsvariabelen in `backend/.env`. Zie `.env.example` voor de volledige
lijst met uitleg.

| Variabele | Standaard | Waarvoor |
| --- | --- | --- |
| `GANZ_ENVIRONMENT` | `development` | `development`, `test` of `production` |
| `GANZ_DATABASE_URL` | localhost | de databaseverbinding |
| `GANZ_SECRET_KEY` | *ontwikkelwaarde* | ondertekent de inlogtokens |
| `GANZ_ENCRYPTION_KEY` | *ontwikkelwaarde* | versleutelt de provider-tokens |
| `GANZ_ACCESS_TOKEN_MINUTES` | `720` | hoe lang een sessie geldig is |
| `GANZ_CONFIRMATION_TOKEN_MINUTES` | `5` | hoe kort een tweede bevestiging meegaat |
| `GANZ_CORS_ORIGINS` | `http://localhost:5173` | waar de frontend vandaan mag komen |
| `GANZ_SCHEDULER_ENABLED` | `true` | achtergrondsynchronisatie aan of uit |
| `GANZ_FINANCE_SYNC_MINUTES` | `15` | hoe vaak financiële accounts worden opgehaald |
| `GANZ_SOCIAL_SYNC_MINUTES` | `30` | hoe vaak social-kanalen worden opgehaald |
| `GANZ_STALE_AFTER_MINUTES` | `60` | wanneer gegevens "verouderd" heten |
| `GANZ_ALLOW_SEED_DATA` | `false` | voorbeelddata toestaan (nooit in productie) |

**In productie start Ganz niet** zolang `GANZ_SECRET_KEY` en `GANZ_ENCRYPTION_KEY` nog
op de ontwikkelwaarden staan. Dat is met opzet: een standaardsleutel betekent dat
versleutelde tokens door iedereen te lezen zijn.

Zet de synchronisatie-intervallen niet onnodig laag. De API's van YouTube, Instagram en
TikTok hebben stevige rate limits.

---

## Ontwikkelen

```bash
cd backend
pytest                              # de hele testsuite
alembic check                       # staan database en modellen gelijk?
alembic revision --autogenerate -m "wat je veranderde"

cd frontend
npm run typecheck
npm run build
```

### Voorbeelddata

Om tijdens het bouwen iets op het scherm te hebben:

```bash
cd backend
GANZ_ALLOW_SEED_DATA=true python -m scripts.seed_dev --email jij@example.com
```

Alles wat hiermee wordt aangemaakt begint met `[DEMO]`, zodat je in één oogopslag ziet
dat het geen echte gegevens zijn. Het script weigert te draaien in productie.

**In productie staan er geen verzonnen cijfers.** Niets gekoppeld betekent een leeg
paneel met uitleg, geen voorbeeldbedrag.

---

## Documentatie

| Bestand | Waarover |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | hoe de delen samenwerken |
| [docs/database.md](docs/database.md) | de tabellen en waarom ze zo zijn |
| [docs/api.md](docs/api.md) | alle eindpunten |
| [docs/security.md](docs/security.md) | tiers, bevestiging, sleutels |
| [docs/todos.md](docs/todos.md) | de dagelijkse takenlijst |
| [docs/finance.md](docs/finance.md) | vermogen, valuta, providers |
| [docs/social.md](docs/social.md) | gecombineerde kanaalstatistieken |
| [docs/upload-schedule.md](docs/upload-schedule.md) | uploadschema en aftelling |

---

## Een paar keuzes, kort toegelicht

**Het dashboard roept nooit een provider aan.** De scheduler haalt op, het dashboard
leest. Anders zit je binnen een dag tegen rate limits aan en wordt het scherm zo traag
als de traagste bank.

**Bedragen zijn `Decimal`, nooit floats.** Bij twintig rekeningen loopt een
float-optelling tientallen centen uit de pas — precies bij het getal dat het grootst in
beeld staat. Ook in de API gaan ze als tekst de deur uit.

**Leeg is niet nul.** Levert een platform geen weergaven, dan staat er een streepje. Is
er geen wisselkoers, dan telt dat account zichtbaar niet mee. Verzonnen cijfers zijn
erger dan ontbrekende cijfers.

**Alleen jij vinkt taken af.** Geen enkele integratie kan een to-do op voltooid zetten.
Dat is precies wat de lijst bruikbaar maakt.

**De aftelling wordt niet opgeslagen.** Er staat één exact moment; de rest is rekenwerk.
