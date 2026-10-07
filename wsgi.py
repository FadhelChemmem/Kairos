"""Point d'entrée WSGI — utilisé par gunicorn (voir Dockerfile) et par
`flask run` en développement local (FLASK_APP=wsgi.py)."""
from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402  (après load_dotenv, volontairement)

app = create_app()

if __name__ == "__main__":
    # 127.0.0.1 (audit QA m6) : en mode debug, le débogueur Werkzeug permet
    # d'exécuter du code — jamais exposé au réseau.
    app.run(debug=app.config["DEBUG"], host="127.0.0.1", port=8000)
