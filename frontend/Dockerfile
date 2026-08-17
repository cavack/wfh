FROM node:26-alpine
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
ENV HOSTNAME="0.0.0.0"

COPY package*.json ./
RUN npm ci

COPY . .
RUN sed -i 's/127.0.0.1/waterfall-backend/g' next.config.js
RUN npm run build

RUN mkdir -p /app/.next/cache && chown -R node:node /app

USER node
EXPOSE 3000
CMD ["npm", "start"]
