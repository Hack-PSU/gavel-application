#!/bin/bash
set -e

# Find PostgreSQL bin directory (auto-detect version)
PG_BIN=$(find /usr/lib/postgresql -type d -name "bin" 2>/dev/null | head -1)
echo "Using PostgreSQL binaries from: $PG_BIN"

# Initialize PostgreSQL if needed
if [ ! -f /var/lib/postgresql/data/PG_VERSION ]; then
  echo "Initializing PostgreSQL database..."
  su - postgres -c "$PG_BIN/initdb -D /var/lib/postgresql/data"
  echo "PostgreSQL initialized"
fi

# Start PostgreSQL
echo "Starting PostgreSQL..."
su - postgres -c "$PG_BIN/pg_ctl -D /var/lib/postgresql/data -l /tmp/postgresql.log start"

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL to be ready..."
for i in {1..30}; do
  if su - postgres -c "psql -d postgres -c 'SELECT 1' > /dev/null 2>&1"; then
    echo "PostgreSQL is ready"
    break
  fi
  echo "Waiting for PostgreSQL... ($i/30)"
  sleep 1
done

# Verify gavel user and database exist
echo "Checking gavel database..."
if ! su - postgres -c "psql -d postgres -tAc \"SELECT 1 FROM pg_roles WHERE rolname='gavel'\"" | grep -q 1; then
  echo "Creating gavel user..."
  su - postgres -c "psql -d postgres -c \"CREATE USER gavel WITH PASSWORD 'gavel_prod_pass';\""
fi

if ! su - postgres -c "psql -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='gavel'\"" | grep -q 1; then
  echo "Creating gavel database..."
  su - postgres -c "psql -d postgres -c \"CREATE DATABASE gavel OWNER gavel;\""
fi

# Redis disabled for testing
# # Start Redis
# echo "Starting Redis..."
# redis-server --bind 127.0.0.1 --daemonize yes --dir /var/lib/redis

# # Wait for Redis to be ready
# echo "Waiting for Redis to be ready..."
# for i in {1..10}; do
#   if redis-cli ping > /dev/null 2>&1; then
#     echo "Redis is ready"
#     break
#   fi
#   echo "Waiting for Redis... ($i/10)"
#   sleep 1
# done

# Initialize Gavel database
echo "Initializing Gavel database..."
python initialize.py || true

# Stop PostgreSQL (supervisor will manage it)
echo "Stopping PostgreSQL for supervisor takeover..."
su - postgres -c "$PG_BIN/pg_ctl -D /var/lib/postgresql/data stop" || true

# Redis disabled for testing
# # Stop Redis (supervisor will manage it)
# echo "Stopping Redis for supervisor takeover..."
# redis-cli shutdown || true

sleep 2

# Start supervisor
echo "Starting all services via supervisor..."
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
