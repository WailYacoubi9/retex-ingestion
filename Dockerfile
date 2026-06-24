FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./
COPY config/ ./config/
COPY scripts/ ./scripts/

# data/samples monté en volume au runtime
# .env monté en volume au runtime

CMD ["python", "scripts/ingest_incident_securite_v2.py", \
     "--input", "data/samples/incidents_securites.json"]
