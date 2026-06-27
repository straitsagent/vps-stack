FROM node:22-slim

# Postgres client for DB queries from the agent (verify §5 + oracle)
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install OpenClaw globally
RUN npm install -g openclaw@latest

# Sandbox workspace (P4 — named volumes are root-owned; create+chown here)
# The node user already exists (uid 1000, gid 1000 — satisfies oracle O1)
RUN mkdir -p /workspace && chown 1000:1000 /workspace

# HOME points to /workspace (named volume, chowned, writable)
# so OpenClaw state (~/.openclaw/) lands on persistent writable storage,
# not on a tmpfs that hides the Dockerfile's permission setup.
ENV HOME=/workspace

USER 1000:1000

ENTRYPOINT ["openclaw", "gateway"]
