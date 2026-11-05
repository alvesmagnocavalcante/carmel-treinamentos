FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    PORT=10000

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt gunicorn

COPY --chown=app:app manage.py ./
COPY --chown=app:app carmel_project/ ./carmel_project/
COPY --chown=app:app treinamentos/ ./treinamentos/
COPY --chown=app:app templates/ ./templates/
COPY --chown=app:app static/ ./static/
COPY --chown=app:app data/db.sqlite3 ./data/db.sqlite3
COPY --chown=app:app data/mock_drive/ ./data/mock_drive/
COPY --chown=app:app data/temp_docs/ ./data/temp_docs/

USER app

EXPOSE 10000

CMD ["/bin/sh", "-c", "set -e; python manage.py migrate --noinput; python manage.py collectstatic --noinput; exec gunicorn carmel_project.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --timeout 120 --access-logfile - --error-logfile -"]
