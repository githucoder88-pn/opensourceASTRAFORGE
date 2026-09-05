# AstraForge in a container.
#
# Running AstraForge in a container is the recommended way to execute goals that
# involve `shell.run`, because v0.1 confines commands to the workspace but does
# not otherwise sandbox them. See SECURITY.md.
#
#   docker build -t astraforge .
#   docker run --rm -it --network=none -v "$PWD/out:/work" astraforge \
#     run "Write a design note" -y

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/astraforge

# Install dependencies first so they stay cached across source changes.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# Run as a non-root user: generated code should never execute as root.
RUN useradd --create-home --uid 1000 astra && \
    mkdir -p /work && chown -R astra:astra /work
USER astra
WORKDIR /work

ENTRYPOINT ["astraforge"]
CMD ["--help"]
