# syntax=docker/dockerfile:1

# --- Stage 1: build the React SPA (Vite → frontend/dist) --------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend

# Install deps from the lockfile first for better layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Build the static bundle.
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime (FastAPI serves /api + the built SPA) ----------
FROM python:3.13-slim

# uv provides fast, reproducible installs straight from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install backend dependencies only (no dev group, no editable project build);
# `backend` is imported from the copied source tree, not installed as a package.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code and the built frontend. server.py expects the SPA at
# ./frontend/dist relative to the repo root (this WORKDIR).
COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Data volume mount point for the SQLite file.
RUN mkdir -p /app/data

# Put the project virtualenv on PATH so `uvicorn` resolves directly.
ENV PATH="/app/.venv/bin:$PATH"
ENV LLM_LESUNG_DB=/app/data/llm-lesung.db

EXPOSE 8000
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]
