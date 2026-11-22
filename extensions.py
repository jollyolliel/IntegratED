import os

from authlib.integrations.flask_client import OAuth
from flask_compress import Compress
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()
migrate = Migrate()
# memory:// is per-process: limits reset on restart and are not shared across
# Cloud Run instances. Point RATELIMIT_STORAGE_URI at Redis/memcached to get
# real cross-instance limiting once the service scales past one instance.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["300 per minute"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)
compress = Compress()