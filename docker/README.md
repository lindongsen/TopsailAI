# Docker Deployment Guide

This guide explains how to deploy the project using Docker.

# Prerequisites

- Docker installed on your system
  - Visit https://www.docker.com/ to download and install Docker if needed
  - Verify your installation by running `docker --version`

# Build Docker Image

```bash
docker build -t topsailai .
```

# Configure the Environment

The image links the code-owned base template at `/root/.topsailai/.env` to `/TopsailAI/src/topsailai/env_template`.

Provide deployment-specific configuration only through `/root/.topsailai/.env.local`. `topsailai` loads `.env.local` after `.env`, so local values override the base template.

## Setup Steps

1. Copy the example local override file:

```bash
cp .env.local.example .env.local
```

2. Edit `.env.local` and set at least your API key:

```bash
OPENAI_API_KEY="your-api-key-here"
```

3. Optionally add deployment-specific overrides such as `OPENAI_MODEL`, `OPENAI_API_BASE`, or `TOPSAILAI_PROJECT_WORKSPACE`.

# Run

Replace `/path/to/your/.env.local` with the actual path to your local override file, then run:

```bash
docker run -d \
    -v "/path/to/your/.env.local:/root/.topsailai/.env.local" \
    topsailai
```

# Notes

- Do not commit `.env.local` to version control; it contains deployment-specific secrets and overrides.
- Keep `.env.local.example` up to date when new required overrides are introduced.
