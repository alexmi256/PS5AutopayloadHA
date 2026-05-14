ARG BUILD_FROM=ghcr.io/home-assistant/base-python:latest
FROM ${BUILD_FROM}

# Alpine's Python 3 is marked "externally managed" (PEP 668),
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
