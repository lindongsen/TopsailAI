# 1. Use an official Python base image
FROM python:3.13

# 2. Install git for cloning the repository
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

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

# 8. Copy pause for pid 1
COPY pause /pause

# 9. Set the default command to start the example application
CMD ["/pause"]
