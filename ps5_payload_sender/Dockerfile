ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

# HA Supervisor uses ghcr.io/home-assistant/amd64-base:latest (Alpine).
# Python is NOT included – install it first.
RUN apk add --no-cache python3 py3-pip

# Alpine's Python 3.12 is marked "externally managed" (PEP 668),
# so we create a venv – pip installs into it without system restrictions.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY app/ /app/
COPY rootfs/ /
COPY payloads/ /defaults/payloads/

EXPOSE 8765
