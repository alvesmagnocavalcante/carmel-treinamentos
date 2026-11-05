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
    && pip install -r requirements.txt gunicorn "whitenoise>=6.8,<7"

COPY --chown=app:app manage.py ./
COPY --chown=app:app carmel_project/ ./carmel_project/
COPY --chown=app:app treinamentos/ ./treinamentos/
COPY --chown=app:app templates/ ./templates/
COPY --chown=app:app static/ ./static/
COPY --chown=app:app data/mock_drive/ ./data/mock_drive/

RUN mkdir -p data/temp_docs data/staticfiles \
    && chown -R app:app data

RUN printf '%s\n' \
    'from carmel_project.wsgi import application as django_application' \
    'from whitenoise import WhiteNoise' \
    'application = WhiteNoise(django_application, root="/app/data/staticfiles", prefix="static/")' \
    > render_wsgi.py \
    && chown app:app render_wsgi.py

USER app

EXPOSE 10000

CMD ["/bin/sh", "-c", "set -e; python manage.py migrate --noinput; python manage.py seed_carmel; python manage.py collectstatic --noinput; exec gunicorn render_wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --timeout 120 --access-logfile - --error-logfile -"]
