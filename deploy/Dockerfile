# De backend van Ganz. Alleen de backend: het scherm is een map met bestanden die Caddy
# uitserveert, en de desktopschil draait op je eigen computer.
FROM python:3.12-slim

# Niet als root draaien. Gaat er iets mis in een afhankelijkheid, dan is het verschil tussen
# "een proces met te veel rechten" en "een proces met bijna geen" het hele verschil.
RUN useradd --create-home --uid 10001 ganz

WORKDIR /app

# Eerst alleen de lijst met pakketten kopiëren: verandert die niet, dan hergebruikt Docker
# deze laag en duurt een nieuwe build seconden in plaats van minuten.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/

USER ganz

EXPOSE 8000

# --proxy-headers: achter Caddy is het adres van de bezoeker alleen te zien in een header.
# --forwarded-allow-ips: en die header geloven we alleen als hij van Caddy zelf komt, anders
# kan iedereen zijn eigen adres verzinnen en staat er onzin in je apparatenlijst.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--timeout-graceful-shutdown", "20"]
