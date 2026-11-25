FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_API_URL=/api npm run build

FROM python:3.13-slim-bookworm AS backend
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app --home /home/app app
COPY backend/ ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .
COPY --from=frontend /build/dist /app/frontend-dist
ENV FRONTEND_DIST=/app/frontend-dist \
    VISTAGEO_PHOTO_CLEANUP_ENABLED=true
RUN chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8000') + '/api/health', timeout=4).read()"
CMD ["sh", "-c", "exec uvicorn app.unified:app --host 0.0.0.0 --port ${PORT:-8000}"]