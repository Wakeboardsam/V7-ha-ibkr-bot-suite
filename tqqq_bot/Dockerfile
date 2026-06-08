FROM python:3.11-slim-bookworm

LABEL io.hass.version="0.1.2" io.hass.type="app" io.hass.arch="amd64|aarch64"

RUN apt-get update && apt-get install -y jq bash && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/

COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

ENTRYPOINT ["/app/run.sh"]
