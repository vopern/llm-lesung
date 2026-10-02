#!/bin/bash
# cloud-init bootstrap for the LLM-Lesung web instance (Amazon Linux 2023, x86_64).
# Installs Docker + the Compose v2 plugin and creates /app. The compose file,
# the image and the DB all arrive from local machine (make deploy / make push-db).
set -euxo pipefail

# --- Docker engine --------------------------------------------------------
dnf update -y
dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user

# --- Docker Compose v2 plugin (not packaged on AL2023) --------------------
COMPOSE_VERSION="v2.29.7"
ARCH="$(uname -m)"   # x86_64 on t3
install -d /usr/local/lib/docker/cli-plugins
curl -fsSL \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${ARCH}" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# --- App directory --------------------------------------------------------
# `make deploy` copies compose.prod.yaml to /app/compose.yaml, `make push-db`
# rsyncs the SQLite file into /app/data.
install -d -o ec2-user -g ec2-user /app /app/data
