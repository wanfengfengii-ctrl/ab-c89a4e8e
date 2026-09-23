# One-shot verification image: ships both Node (frontend build check) and
# Python 3 (pytest + API smoke). The repository is bind-mounted at /workspace
# by docker-compose; this container runs every check once and exits.
FROM node:20-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
