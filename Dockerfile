# Multi-stage build for StreamFlow application
# Stage 1: Build the React frontend
# Stage 2: Python backend with pre-built static files

# ── Stage 1: Frontend Build ───────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

# Copy package files first for better layer caching
COPY frontend/package.json frontend/package-lock.json ./

# Install dependencies (use ci for reproducible builds)
RUN npm ci --prefer-offline 2>/dev/null || npm install

# Copy frontend source
COPY frontend/ ./

# Build production bundle
RUN npm run build

# ── Stage 2: Python Backend ───────────────────────────────────────────────────
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create working directory for backend
WORKDIR /app

# Copy backend requirements first for better caching
COPY backend/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

# Copy backend application code
COPY backend/ ./

# Copy pre-built frontend from Stage 1
COPY --from=frontend-builder /frontend/build ./static

# Create necessary directories
# data directory will be mounted as volume for persistence
RUN mkdir -p csv logs data

# Set environment variable for config directory
ENV CONFIG_DIR=/app/data

# Set permissions for entrypoint
RUN chmod +x entrypoint.sh

# Create default configuration files in the data directory
RUN python3 apps/core/create_default_configs.py

# Expose the Flask port
EXPOSE 5000

# Health check for Flask API
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Use entrypoint script to start Flask API
ENTRYPOINT ["/app/entrypoint.sh"]
