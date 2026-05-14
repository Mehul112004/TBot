import os

# Render assigns a dynamic PORT; fallback to 5001 for local/dev
bind = f"0.0.0.0:{os.environ.get('PORT', 5001)}"
workers = int(os.environ.get("GUNICORN_WORKERS", 2))
worker_class = "sync"
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
