# syntax=docker/dockerfile:1
# SuperPlanner frontend image (PHASE2B 5.5): static build served by unprivileged nginx on :8080, which also
# proxies /api/ to the API service. Build context: frontend/.

FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS run
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=0755 docker/40-sp-real-ip.sh /docker-entrypoint.d/40-sp-real-ip.sh
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
USER 101
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
