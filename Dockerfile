FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Expose API port
EXPOSE 6002

# Run both the scheduler and the API server
CMD ["sh", "-c", "python -m uvicorn src.api:app --host 0.0.0.0 --port 6002 & python -m src.main"]
