FROM python:3.11-slim-bookworm

LABEL io.hass.version="0.1.5" io.hass.type="app" io.hass.arch="amd64|aarch64"

# Install system dependencies (merged from ibkr_gateway and bot)
RUN apt-get update && apt-get install -y \
    default-jre \
    wget \
    unzip \
    jq \
    procps \
    libxtst6 \
    libxrender1 \
    libxi6 \
    gettext-base \
    x11vnc \
    xvfb \
    xdotool \
    bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install IB Gateway
RUN wget -q https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh \
    && chmod +x ibgateway-stable-standalone-linux-x64.sh \
    && ./ibgateway-stable-standalone-linux-x64.sh -q -dir /root/Jts/ibgateway \
    && rm ibgateway-stable-standalone-linux-x64.sh

RUN mkdir -p /root/Jts/ibgateway \
    && JARS_PARENT=$(dirname $(find /root/Jts -name jars -type d | head -n 1)) \
    && ln -sfn $JARS_PARENT /root/Jts/ibgateway/1019 \
    && ln -sfn $JARS_PARENT /root/Jts/1019

# Configure IB Gateway memory limit
RUN find /root/Jts/ibgateway -name "*.vmoptions" -exec sh -c 'echo "-Xmx512m" >> "{}"' \;

# Install IBC
RUN wget -q https://github.com/IbcAlpha/IBC/releases/download/3.23.0/IBCLinux-3.23.0.zip \
    && mkdir -p /opt/ibc \
    && unzip IBCLinux-3.23.0.zip -d /opt/ibc \
    && (chmod +x /opt/ibc/scripts/*.sh /opt/ibc/*.sh 2>/dev/null || true) \
    && rm IBCLinux-3.23.0.zip

RUN sed -i 's/xterm.*-e //' /opt/ibc/gatewaystart.sh
RUN ! grep -q "xterm" /opt/ibc/gatewaystart.sh

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY app/ /app/

# Copy scripts
COPY run.sh /app/run.sh
COPY wait_for_gateway.py /app/wait_for_gateway.py

RUN chmod +x /app/run.sh

ENTRYPOINT ["/app/run.sh"]
