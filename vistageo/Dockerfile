FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_API_URL=/api npm run build

FROM python:3.13-slim AS backend
WORKDIR /app
COPY backend/ ./
RUN pip install --no-cache-dir .
COPY --from=frontend /build/dist /app/frontend-dist
ENV FRONTEND_DIST=/app/frontend-dist
ENV VISTAGEO_PHOTO_CLEANUP_ENABLED=true
CMD ["sh", "-c", "exec uvicorn app.unified:app --host 0.0.0.0 --port ${PORT:-8000}"]
