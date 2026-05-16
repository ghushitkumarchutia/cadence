# Stage 1: Build dependencies
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
# We need build-essential for some scientific packages that might need compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Final runtime image
FROM python:3.12-slim

WORKDIR /app

# Create a non-privileged user for security (Standard Industry Practice)
RUN groupadd -g 1000 cadence && \
    useradd -m -u 1000 -g cadence -s /bin/sh cadence

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Copy application code
COPY . .

# Ensure entrypoint is executable and set permissions
RUN chmod +x scripts/docker-entrypoint.sh && \
    chown -R cadence:cadence /app

USER cadence

ENTRYPOINT ["scripts/docker-entrypoint.sh"]
