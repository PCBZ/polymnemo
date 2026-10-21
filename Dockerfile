# polymnemo — container image targeting Google Cloud Run.
#
# Cloud Run injects $PORT (default 8080) and expects the process to bind
# 0.0.0.0:$PORT. All state lives in Neon, so the container is stateless and can
# scale to zero. Provision >=1GB RAM (the local embedding model, added in #3,
# needs the headroom).

FROM python:3.11-slim

# POLYMNEMO_REQUIRE_DATABASE=true: refuse to start on the in-memory store, so a
# missing POLYMNEMO_DATABASE_URL fails fast instead of silently losing memories.
# The embedding model is NOT pinned here — it comes from the app config
# (settings.embed_model), the single source of truth, and is baked in below.
# Both caches are pinned off their defaults onto one stable, ownable path:
# fastembed otherwise uses /tmp, which a runtime tmpfs can shadow, discarding
# the baked model with it.
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POLYMNEMO_HOST=0.0.0.0 \
    POLYMNEMO_REQUIRE_DATABASE=true \
    FASTEMBED_CACHE_PATH=/opt/model-cache/fastembed \
    HF_HOME=/opt/model-cache/huggingface

WORKDIR /app

# Install the package. README/LICENSE are referenced by pyproject metadata.
# The durable store (postgres) and media (boto3) deps are core dependencies, so
# a plain install has everything the deployed server needs.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[rsp]"

# The vendored gitleaks plugin and the scanner config (#163). Our own plugin
# is not here -- it ships inside the package as polymnemo.plugins.tokens.
# Inert unless POLYMNEMO_RSP_CONFIG names a config: nothing is imported and
# nothing is spawned, so the scanners cost runtime nothing when unused.
COPY plugins ./plugins

# gitleaks, copied out of its own published image rather than downloaded and
# checksummed by hand. The tag pins the version, and Docker verifies the image
# it pulls, so there is no hash here to keep in step with the version.
#
# Two things checked before relying on this: the binary is at /usr/bin/gitleaks
# in that image, and although the image is Alpine, the binary is statically
# linked (ELF EXEC, no interpreter), so it runs on this Debian base. The
# `gitleaks version` below is what would catch that changing.
#
# Copied as root, before the user switch, and left world-executable so the
# unprivileged runtime user can run it. ~22 MB.
COPY --from=zricethezav/gitleaks:v8.30.1 /usr/bin/gitleaks /usr/local/bin/gitleaks
RUN chmod 0755 /usr/local/bin/gitleaks && gitleaks version

# Drop root before baking, so the cache is written by the uid that later reads
# it. Nothing in the app writes to disk, so read-only ownership is enough.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /opt/model-cache \
    && chown app:app /opt/model-cache
USER app

# Bake the embedding model AND its tokenizer (used for token-aware chunking)
# into the image so cold starts don't download them (first request still
# initializes the ONNX session, but hits no network). The model name is read
# from the app config (settings.embed_model) so there's exactly one source of
# truth — the baked model can't drift from what the runtime loads.
RUN python -c "from polymnemo.config import settings; from fastembed import TextEmbedding; from tokenizers import Tokenizer; TextEmbedding(settings.embed_model); Tokenizer.from_pretrained(settings.embed_model)"

# Documentation only; Cloud Run routes to $PORT regardless.
EXPOSE 8080

CMD ["polymnemo"]
