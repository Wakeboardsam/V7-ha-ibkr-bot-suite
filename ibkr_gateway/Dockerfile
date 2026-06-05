FROM debian:bookworm-slim

LABEL io.hass.version="0.1.0" io.hass.type="app" io.hass.arch="amd64|aarch64"

# System dependencies for Step 03/04 (v6 shape)
# RUN apt-get update && apt-get install -y \
#     default-jre \
#     supervisor \
#     wget \
#     unzip \
#     jq \
#     procps \
#     libxtst6 \
#     libxrender1 \
#     libxi6 \
#     gettext-base \
#     x11vnc \
#     xvfb \
#     && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y jq bash && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# TODO: Step 03/04: Install IB Gateway
# TODO: Step 03/04: Configure IB Gateway memory limit
# TODO: Step 03/04: Install IBC
# TODO: Step 03/04: Configure IBC

COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

ENTRYPOINT ["/app/run.sh"]
