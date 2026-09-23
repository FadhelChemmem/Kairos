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
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "wsgi:app"]
