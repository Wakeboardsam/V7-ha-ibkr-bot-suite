FROM python:3.11-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    default-jre \
    supervisor \
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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install IB Gateway
# We use the x64 installer. For aarch64, it's expected to run via emulation in the target environment if native is unavailable.
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
    && chmod +x /opt/ibc/scripts/*.sh /opt/ibc/*.sh 2>/dev/null || true \
    && rm IBCLinux-3.23.0.zip

RUN sed -i 's/xterm.*-e //' /opt/ibc/gatewaystart.sh
RUN ! grep -q "xterm" /opt/ibc/gatewaystart.sh

# Configure IBC
# Note: config is rendered at runtime by run.sh

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY . .

EXPOSE 5900

# Set entrypoint
RUN chmod +x run.sh
ENTRYPOINT ["/app/run.sh"]
