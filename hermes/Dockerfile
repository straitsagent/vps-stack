FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "hermes-agent[messaging] @ git+https://github.com/NousResearch/hermes-agent.git@f3d8f20a598cecd1ac1ec17fe44e9959ae5ed23a"

RUN groupadd -g 1000 hermes && useradd -u 1000 -g 1000 -m -d /workspace hermes

ENV HOME=/workspace \
    HERMES_HOME=/workspace \
    HERMES_DISABLE_LAZY_INSTALLS=1 \
    HERMES_WRITE_SAFE_ROOT=/workspace \
    PATH="/usr/local/bin:$PATH"

USER 1000:1000

ENTRYPOINT ["hermes", "gateway", "run"]
