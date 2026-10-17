# =============================================================
# Stage 1: Build the React + Vite Frontend
# =============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

COPY frontend ./
RUN npm run build

# =============================================================
# Stage 2: Production Python Backend + Static Files
# =============================================================
FROM python:3.12-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    FRONTEND_DIST_DIR=/app/frontend/dist

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/pyproject.toml* /app/backend/
RUN pip install --no-cache-dir --upgrade pip && \
    if [ -f /app/backend/pyproject.toml ]; then pip install --no-cache-dir "/app/backend"; else pip install --no-cache-dir fastapi uvicorn[standard] falkordb redis pydantic python-dotenv; fi

# Copy backend application source, cypher queries, and fixtures
COPY backend /app/backend
COPY fixtures /app/fixtures

# Copy built frontend assets from builder stage
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

EXPOSE 8000

# Start Uvicorn serving both API and Frontend (binds to Render's dynamic $PORT or 8000)
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

