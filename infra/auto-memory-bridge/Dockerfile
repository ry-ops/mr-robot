FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py ./

# Run as a non-root, unprivileged uid; the compose file overrides this
# with the host's UID/GID so the mounted aiana DB stays writable by both.
RUN useradd -m -u 1000 bridge
USER bridge

CMD ["python3", "/app/bridge.py"]
