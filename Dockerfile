FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (gcc for C extensions, supervisor for process management)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy supervisor config
COPY config/supervisord.conf /etc/supervisor/conf.d/infohunter.conf

# Create logs directory
RUN mkdir -p /app/logs

# Expose API port
EXPOSE 6002

# Use supervisord to manage both API server and scheduler
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/infohunter.conf"]
