# polymnemo — container image targeting Google Cloud Run.
#
# Cloud Run injects $PORT (default 8080) and expects the process to bind
# 0.0.0.0:$PORT. All state lives in Neon, so the container is stateless and can
# scale to zero. Provision >=1GB RAM (the local embedding model, added in #3,
# needs the headroom).

FROM python:3.11-slim

# Pinned so the baked model matches the runtime model. Must equal
# POLYMNEMO_EMBED_MODEL / the config default (and the DB schema's vector dim).
ARG POLYMNEMO_EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

# POLYMNEMO_REQUIRE_DATABASE=true: refuse to start on the in-memory store, so a
# missing POLYMNEMO_DATABASE_URL fails fast instead of silently losing memories.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POLYMNEMO_HOST=0.0.0.0 \
    POLYMNEMO_EMBED_MODEL=${POLYMNEMO_EMBED_MODEL} \
    POLYMNEMO_REQUIRE_DATABASE=true

WORKDIR /app

# Install the package. README/LICENSE are referenced by pyproject metadata.
# The durable store (postgres) and media (boto3) deps are core dependencies, so
# a plain install has everything the deployed server needs.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir "."

# Bake the embedding model AND its tokenizer (used for token-aware chunking)
# into the image so cold starts don't download them (first request still
# initializes the ONNX session, but hits no network).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${POLYMNEMO_EMBED_MODEL}')" \
 && python -c "from tokenizers import Tokenizer; Tokenizer.from_pretrained('${POLYMNEMO_EMBED_MODEL}')"

# Documentation only; Cloud Run routes to $PORT regardless.
EXPOSE 8080

CMD ["polymnemo"]
