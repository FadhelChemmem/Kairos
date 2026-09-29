FROM python:3.12-slim

# libpq-dev n'est pas nécessaire avec psycopg2-binary, mais on garde les
# certificats à jour et un utilisateur non-root par hygiène de base.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Le dossier uploads/ est un volume Docker monté par-dessus /app/uploads
# (voir docker-compose.yml) : le créer ici, avec les bonnes permissions,
# AVANT le montage garantit que Docker copie ces permissions dans le
# volume à sa toute première création. Sur un volume déjà existant créé
# avant ce correctif (2026-09-20), un chown manuel une seule fois reste
# nécessaire : `docker compose exec -u root web chown -R appuser:appuser
# /app/uploads` — voir le README.
RUN useradd --create-home appuser \
    && mkdir -p /app/uploads \
    && chown -R appuser:appuser /app
USER appuser

ENV FLASK_APP=wsgi.py \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# gunicorn en production ; pour du debug local, `flask run` fonctionne
# aussi (voir README.md).
#
# Audit n°2 :
# - gthread (3 workers x 4 threads) : avec 3 workers synchrones, trois
#   clients lents (upload de 25 Mo, envoi SMTP) bloquaient toute l'appli.
#   Le pool de connexions (db.py, 10 max par worker) couvre les 4 threads.
# - --access-logfile - : les requêtes apparaissent dans `docker compose
#   logs web` (utile pour reconstituer un incident).
# - --worker-tmp-dir /dev/shm : évite les blocages de heartbeat gunicorn
#   sur un disque lent (NAS).
# Les en-têtes X-Forwarded-* d'un reverse proxy sont interprétés par
# l'appli elle-même (ProxyFix, TRUSTED_PROXY_COUNT dans .env), pas par
# gunicorn.
#
# Migrations appliquées AU DÉMARRAGE, avant gunicorn (audit du 2026-09-29) :
# entre `docker compose up -d --build` et `flask migrer`, personne ne
# pouvait se connecter (erreur 500 sur une table pas encore créée) alors
# que le healthcheck disait "healthy" — et l'étape était facile à oublier
# depuis l'interface d'un NAS. `flask migrer` ne fait rien si tout est à
# jour ; si une migration échoue, le conteneur ne démarre pas (erreur
# visible dans `docker compose logs web`) plutôt que de servir une appli
# à moitié à jour.
CMD ["sh", "-c", "flask migrer && exec gunicorn --bind 0.0.0.0:8000 --workers 3 --threads 4 --worker-class gthread --timeout 60 --worker-tmp-dir /dev/shm --access-logfile - wsgi:app"]
