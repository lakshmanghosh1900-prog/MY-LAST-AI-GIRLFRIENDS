FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    JARVIS_HOST=0.0.0.0 \
    JARVIS_ALLOW_NON_LOOPBACK_BINDING=true \
    JARVIS_PORT=8787 \
    JARVIS_DATA_DIR=/app/data \
    JARVIS_ALLOWED_ROOT=/app/workspace

WORKDIR /app
COPY pyproject.toml README.md .python-version ./
COPY src ./src
COPY workspace ./workspace

RUN python -m compileall -q src && mkdir -p /app/data

EXPOSE 8787
CMD ["python", "-m", "jarvis_omega.main"]
