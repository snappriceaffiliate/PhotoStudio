# One image for the whole product. Targets:
#   dev         - Python and dependencies only; code is mounted by Docker Compose
#   production  - built React files collected into Django static files, run by Gunicorn;
#                 the copy tool is served at /copy/

FROM node:24-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# The copy tool: a separate small app for the studio's computer, served by Django at /copy/.
FROM node:24-slim AS copy-tool-build
WORKDIR /copy-tool
COPY copy-tool/package.json copy-tool/package-lock.json ./
RUN npm ci
COPY copy-tool/ ./
RUN npm run build

FROM python:3.12-slim AS dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.10.11
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project
COPY backend/ ./
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM dev AS production
RUN uv sync --frozen --no-install-project --no-dev
COPY --from=frontend-build /frontend/dist /app/frontend_dist
COPY --from=copy-tool-build /copy-tool/dist /app/copy_tool_dist/copy
ENV DJANGO_DEBUG=false
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput
RUN useradd --create-home app && chown -R app /app
USER app
# The worker process runs the same image with: python manage.py procrastinate worker
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
