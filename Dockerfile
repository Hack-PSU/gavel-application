FROM python:3.9-slim

# Install PostgreSQL, Redis, and dependencies
RUN apt-get update && apt-get install -y \
    postgresql \
    postgresql-contrib \
    redis-server \
    gcc \
    python3-dev \
    libpq-dev \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY . .

# Create PostgreSQL data directory
RUN mkdir -p /var/lib/postgresql/data && \
    chown -R postgres:postgres /var/lib/postgresql

# Create Redis data directory
RUN mkdir -p /var/lib/redis && \
    chown -R redis:redis /var/lib/redis

# Set defaults and internal config
ENV PYTHONUNBUFFERED=1 \
    FLASK_APP=gavel \
    PORT=5000 \
    # Database - localhost since bundled
    DATABASE_URL=postgresql://gavel:gavel_prod_pass@localhost:5432/gavel \
    DB_URI=postgresql://gavel:gavel_prod_pass@localhost:5432/gavel \
    # Redis - localhost since bundled
    REDIS_URL=redis://localhost:6379/0 \
    BROKER_URI=redis://localhost:6379/0 \
    # HackPSU Auth
    AUTH_ENVIRONMENT=production \
    MIN_JUDGE_ROLE=2 \
    MIN_ADMIN_ROLE=4 \
    AUTH_LOGIN_URL=https://auth.hackpsu.org/login \
    # HackPSU API
    HACKPSU_API_BASE_URL=https://apiv3.hackpsu.org \
    # App defaults
    DEBUG=false \
    DISABLE_EMAIL=true \
    PROXY=true \
    SEND_STATS=false \
    MIN_VIEWS=2 \
    TIMEOUT=5.0 \
    SYNC_INTERVAL_MINUTES=30 \
    IGNORE_CONFIG_FILE=true \
    # Firebase
    FIREBASE_PROJECT_ID=hackpsu-408118 \
    FIREBASE_API_KEY=AIzaSyBG636oXijUAzCq6Makd2DNU_0WzPJRw8s

# Required runtime env vars (set in Portainer):
# - SECRET_KEY
# - ADMIN_PASSWORD
# - HACKPSU_API_KEY (optional)

# Create supervisor config (auto-detect PostgreSQL version)
RUN PG_BIN=$(find /usr/lib/postgresql -type d -name "bin" | head -1) && \
    echo "[supervisord]\n\
nodaemon=true\n\
user=root\n\
\n\
[program:postgresql]\n\
user=postgres\n\
command=${PG_BIN}/postgres -D /var/lib/postgresql/data\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:redis]\n\
command=/usr/bin/redis-server --bind 127.0.0.1 --dir /var/lib/redis\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:celery]\n\
command=celery -A gavel.celery worker --loglevel=info\n\
directory=/app\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:celery-beat]\n\
command=celery -A gavel.celery beat --loglevel=info\n\
directory=/app\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0\n\
\n\
[program:gavel]\n\
command=gunicorn -b 0.0.0.0:5000 -w 2 --timeout 120 gavel:app\n\
directory=/app\n\
autostart=true\n\
autorestart=true\n\
stdout_logfile=/dev/stdout\n\
stdout_logfile_maxbytes=0\n\
stderr_logfile=/dev/stderr\n\
stderr_logfile_maxbytes=0" > /etc/supervisor/conf.d/supervisord.conf

# Copy startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Expose port
EXPOSE 5000

# Volume for PostgreSQL data persistence
VOLUME ["/var/lib/postgresql/data"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Start script
CMD ["/app/start.sh"]
