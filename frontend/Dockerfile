# syntax=docker/dockerfile:1
FROM node:22-slim AS build
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
WORKDIR /app
# Corepack activates the pnpm version pinned in package.json "packageManager".
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && corepack install
RUN --mount=type=cache,target=/pnpm/store \
    pnpm install --frozen-lockfile --store-dir /pnpm/store
COPY . .
RUN pnpm build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget -qO /dev/null http://127.0.0.1/ || exit 1
