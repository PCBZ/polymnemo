# polymnemo — container image targeting Google Cloud Run.
#
# Cloud Run injects $PORT (default 8080) and expects the process to bind
# 0.0.0.0:$PORT. All state lives in Neon, so the container is stateless and can
# scale to zero. Provision >=1GB RAM (the local embedding model, added in #3,
# needs the headroom).

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POLYMNEMO_HOST=0.0.0.0

WORKDIR /app

# Install the package. README/LICENSE are referenced by pyproject metadata.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# NOTE (#3): preload the embedding model here so cold starts don't download it
# on first request, e.g.:
#   RUN python -c "from fastembed import TextEmbedding; TextEmbedding('intfloat/multilingual-e5-small')"

# Documentation only; Cloud Run routes to $PORT regardless.
EXPOSE 8080

CMD ["polymnemo"]
