FROM python:3.11-slim-bookworm

LABEL io.hass.version="0.1.1" io.hass.type="app" io.hass.arch="amd64|aarch64"

# System dependencies for Step 03/04 (v6 shape)
RUN apt-get update && apt-get install -y jq bash && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# TODO: Step 03: Install Python requirements
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# TODO: Step 03: Copy application source code
# COPY . .

COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

ENTRYPOINT ["/app/run.sh"]
