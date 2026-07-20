FROM node:22-alpine AS build

WORKDIR /web

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM caddy:2.10-alpine

COPY service/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv

