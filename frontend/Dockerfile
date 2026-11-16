FROM oven/bun:1 AS build
WORKDIR /app

RUN chown bun:bun /app
USER bun

COPY --chown=bun:bun frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile

COPY --chown=bun:bun frontend/. .
RUN bun run generate

FROM nginxinc/nginx-unprivileged:alpine
USER nginx

COPY --chown=nginx:nginx cmd/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /app/.output/public /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:8080/healthz || exit 1
