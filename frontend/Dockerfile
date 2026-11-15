# syntax=docker/dockerfile:1
# Stage 1 runs on the build machine's native platform (fast even when targeting arm64):
# the output is static HTML/JS, identical for every architecture.
FROM --platform=$BUILDPLATFORM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
RUN npx nuxt generate

# Stage 2: Caddy serves the SPA on $WEB_PORT (never 80) and reverse-proxies /api and /v1
# to the backend at $BACKEND_HOST:$BACKEND_PORT.
FROM caddy:2-alpine
COPY --from=build /app/.output/public /srv
COPY Caddyfile /etc/caddy/Caddyfile
ENV WEB_PORT=8090 BACKEND_HOST=backend BACKEND_PORT=8000
EXPOSE 8090
