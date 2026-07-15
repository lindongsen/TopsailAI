# Docker Deployment Guide

This guide explains how to deploy the project using Docker.

# Prerequisites

- Docker installed on your system
  - Visit https://www.docker.com/ to download and install Docker if needed
  - Verify your installation by running `docker --version`

# Build Docker Image

```bash
docker build -t ai-essence .
```

# Configure the Environment

1. Create a configuration file by copying the template:

```bash
cp env_template .env
```

2. Configure the variables in `.env`.

# Run

Replace /path/to/your/.env with the actual path to your .env file, then run:

```bash
docker run -d \
    -v "/path/to/your/.env:/TopsailAI/.env" \
    ai-essence
```
