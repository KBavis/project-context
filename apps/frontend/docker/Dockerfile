# stage 1: build stage
FROM node:20-alpine AS builder

WORKDIR /app

# copy relevant corporate certs so npm can fetch dependencies over TLS-intercepting corporate networks
# NOTE: Alpine doesn't ship with `update-ca-certificates`, so we directly append the certs 
COPY docker/certs/ /usr/local/share/ca-certificates/
RUN cat /usr/local/share/ca-certificates/*.crt >> /etc/ssl/certs/ca-certificates.crt || true

# node uses NODE_EXTRA_CA_CERTS; npm has its own resolver — wire both to point at certs
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
RUN npm config set cafile /etc/ssl/certs/ca-certificates.crt

# install deps using the lockfile inside app/ (the real one — the stub
# package-lock.json at apps/frontend/ is intentionally NOT copied).
COPY app/package.json app/package-lock.json ./
RUN npm ci

# bring in the rest of the React source. .dockerignore (in app/) keeps
# host node_modules/dist out so the freshly-installed node_modules isn't
# overlaid.
COPY app/ ./
RUN npm run build

# stage 2: production stage
FROM node:20-alpine AS runtime

WORKDIR /app

# copy relevant corporate certs & configure for npm & Node.js
COPY docker/certs/ /usr/local/share/ca-certificates/
RUN cat /usr/local/share/ca-certificates/*.crt >> /etc/ssl/certs/ca-certificates.crt || true
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
RUN npm config set cafile /etc/ssl/certs/ca-certificates.crt

# `serve` is a tiny static server; pinned for reproducibility.
RUN npm install -g serve@14

COPY --from=builder /app/dist ./dist

EXPOSE 3000

CMD ["serve", "-s", "dist", "-l", "3000"]
