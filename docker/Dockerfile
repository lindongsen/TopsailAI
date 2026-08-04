# 1. Use an official Python base image
FROM python:3.13

# 2. Install repository and terminal utilities
RUN apt-get update \
    && apt-get install -y --no-install-recommends git less expect wget curl tmux dtach \
    && rm -rf /var/lib/apt/lists/*

# 3. Set the working directory to the repository root
WORKDIR /TopsailAI

# 4. Clone the repository directly into the working directory
RUN git clone https://github.com/lindongsen/TopsailAI.git .

# 5. Install the 'uv' build tool globally
RUN pip install uv

# 6. Synchronize the Python environment and dependencies
# RUN uv sync

# 7. Add the virtual environment's bin directory to PATH
ENV PATH="/TopsailAI/.venv/bin:/TopsailAI/src/topsailai/bin:$PATH"

ENV LANG=C.UTF-8

# 8. Link the code-owned base template into the default agent home.
# External configuration is supplied only as /root/.topsailai/.env.local.
RUN mkdir -p /root/.topsailai \
    && ln -sfn /TopsailAI/src/topsailai/env_template /root/.topsailai/.env

# 9. Copy pause for pid 1
COPY pause /pause

# 10. Set the default command to start the example application
CMD ["/pause"]
