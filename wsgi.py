"""Point d'entrée WSGI — utilisé par gunicorn (voir Dockerfile) et par
`flask run` en développement local (FLASK_APP=wsgi.py)."""
from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402  (après load_dotenv, volontairement)

app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=8000)
