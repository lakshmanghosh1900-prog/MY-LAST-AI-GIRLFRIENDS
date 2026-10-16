FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    MLAG_HOST=0.0.0.0 \
    MLAG_ALLOW_NON_LOOPBACK_BINDING=true \
    MLAG_PORT=8787 \
    MLAG_DATA_DIR=/app/data \
    MLAG_ALLOWED_ROOT=/app/workspace

WORKDIR /app
COPY pyproject.toml README.md .python-version ./
COPY src ./src
COPY workspace ./workspace

RUN python -m compileall -q src && mkdir -p /app/data

EXPOSE 8787
CMD ["python", "-m", "my_last_ai_girlfriends.main"]
