FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV FLASK_APP=gavel
ENV PYTHONUNBUFFERED=1
ENV IGNORE_CONFIG_FILE=true

# Expose port
EXPOSE 5000

# Initialize database and run with gunicorn
CMD ["sh", "-c", "python initialize.py && gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 120 gavel:app"]
