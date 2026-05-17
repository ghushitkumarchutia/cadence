FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev --ignore-scripts && \
    cp -r node_modules /tmp/prod_modules && \
    npm install --ignore-scripts

COPY tsconfig.json drizzle.config.ts ./
COPY src/ src/

RUN npx tsc

FROM node:22-alpine

WORKDIR /app

RUN addgroup -g 1000 cadence && \
    adduser -u 1000 -G cadence -s /bin/sh -D cadence

COPY --from=builder /tmp/prod_modules node_modules/
COPY --from=builder /app/dist dist/
COPY --from=builder /app/package.json package.json

ENV NODE_ENV=production
ENV PORT=3001

USER cadence

EXPOSE 3001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:3001/health || exit 1

CMD ["node", "dist/server.js"]
