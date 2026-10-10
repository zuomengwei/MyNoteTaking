import os
import sys
# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

ROOT_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(ROOT_DIR, '.env'))

from src.models.user import db
from src.routes.user import user_bp
from src.routes.note import note_bp
from src.models.note import Note

# On Vercel, static assets are served from the `public/` directory (CDN).
# Fall back to the legacy `src/static` folder when it is present (local dev).
PUBLIC_DIR = os.path.join(ROOT_DIR, 'public')
LEGACY_STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')
STATIC_DIR = PUBLIC_DIR if os.path.isdir(PUBLIC_DIR) else LEGACY_STATIC_DIR

app = Flask(__name__, static_folder=STATIC_DIR)
app.config['SECRET_KEY'] = 'asdf#FGSgvasgf$5$WGT'

# Enable CORS for all routes
CORS(app)

# register blueprints
app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(note_bp, url_prefix='/api')

def _normalize_db_uri(uri):
    """Normalize a Postgres URL so SQLAlchemy 2.x uses the psycopg (v3) driver."""
    if uri.startswith('postgres://'):
        uri = 'postgresql://' + uri[len('postgres://'):]
    if uri.startswith('postgresql://'):
        uri = 'postgresql+psycopg://' + uri[len('postgresql://'):]
    return uri


# Prefer an external database (Neon / Vercel Postgres) when one is configured.
# Vercel's local filesystem is read-only except /tmp, so a local SQLite file
# cannot persist across restarts.
DATABASE_URL = (
    os.environ.get('DATABASE_URL')
    or os.environ.get('POSTGRES_URL')
    or os.environ.get('POSTGRES_PRISMA_URL')
)

if DATABASE_URL:
    app.config['SQLALCHEMY_DATABASE_URI'] = _normalize_db_uri(DATABASE_URL)
    # Serverless-friendly connection handling for hosted Postgres.
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
else:
    DB_PATH = os.environ.get('DATABASE_PATH')
    if not DB_PATH:
        if os.environ.get('VERCEL'):
            DB_PATH = os.path.join('/tmp', 'app.db')
        else:
            DB_PATH = os.path.join(ROOT_DIR, 'database', 'app.db')
    # ensure database directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
with app.app_context():
    try:
        db.create_all()
    except Exception as exc:  # keep the app bootable if the DB is unreachable
        app.logger.warning('Database initialization failed: %s', exc)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    static_folder_path = app.static_folder
    if static_folder_path is None:
            return "Static folder not configured", 404

    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)
    else:
        index_path = os.path.join(static_folder_path, 'index.html')
        if os.path.exists(index_path):
            return send_from_directory(static_folder_path, 'index.html')
        else:
            return "index.html not found", 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
