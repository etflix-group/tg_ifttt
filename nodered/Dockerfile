FROM nodered/node-red:latest

USER root
WORKDIR /opt/tg-ifttt-nodered
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY settings.js ./
COPY nodes ./nodes
RUN chown -R node-red:root /opt/tg-ifttt-nodered

USER node-red
WORKDIR /usr/src/node-red
ENV FLOWS="--settings /opt/tg-ifttt-nodered/settings.js"
CMD []
