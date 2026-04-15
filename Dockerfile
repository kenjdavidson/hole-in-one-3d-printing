# syntax=docker/dockerfile:1
# ──────────────────────────────────────────────────────────────────────────────
# Golf Plaque GaaS – Dockerised headless Blender 5.0 API
# ──────────────────────────────────────────────────────────────────────────────
# Build:
#   docker build -t plaque-api .
#
# Run (standalone):
#   docker run -p 8000:8000 plaque-api
#
# Run (with compose):
#   docker compose up --build
# ──────────────────────────────────────────────────────────────────────────────

FROM python:3.10-slim

# ---------------------------------------------------------------------------
# System dependencies required for headless Blender (software rendering)
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        # X11 / OpenGL stubs needed even in --background mode
        libx11-6 \
        libxi6 \
        libxrender1 \
        libxfixes3 \
        libxxf86vm1 \
        # Mesa software renderer (replaces deprecated libgl1-mesa-glx)
        libgl1 \
        libglu1-mesa \
        # Compression utility for unpacking the Blender archive
        xz-utils \
        # Download utility
        wget \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Download and install Blender 5.0 (Linux x64 binary)
# ---------------------------------------------------------------------------
ARG BLENDER_VERSION=5.0.0
ARG BLENDER_ARCHIVE=blender-${BLENDER_VERSION}-linux-x64.tar.xz
ARG BLENDER_URL=https://download.blender.org/release/Blender5.0/${BLENDER_ARCHIVE}

RUN wget -q "${BLENDER_URL}" -O /tmp/blender.tar.xz \
    && tar -xJf /tmp/blender.tar.xz -C /opt \
    && mv /opt/blender-${BLENDER_VERSION}-linux-x64 /opt/blender \
    && ln -s /opt/blender/blender /usr/local/bin/blender \
    && rm /tmp/blender.tar.xz

# ---------------------------------------------------------------------------
# Python API dependencies (installed into the system Python used by uvicorn)
# ---------------------------------------------------------------------------
WORKDIR /app

COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# ---------------------------------------------------------------------------
# Application source
# ---------------------------------------------------------------------------
COPY api/     /app/api/
COPY scripts/ /app/scripts/

# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------
ENV BLENDER_BIN=/usr/local/bin/blender
# Make the top-level /app directory importable so that
# `from golf.xxx import yyy` works inside the system Python (not Blender's).
ENV PYTHONPATH=/app/scripts

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
