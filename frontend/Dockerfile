# syntax=docker/dockerfile:1
# JustTheTwoOfUs web app (Next.js standalone server). Built and run by
# deploy/compose.yaml. Built WITHOUT the development-only demo UI; the bundle
# check fails the build if any of it, or a server-only value, slips in.

FROM node:24-trixie-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG APP_BUILD_ID=""
ENV NEXT_OUTPUT=standalone \
    TWOOFUS_DEMO_UI=0 \
    APP_BUILD_ID=${APP_BUILD_ID} \
    BACKEND_INTERNAL_URL=http://api:8000
RUN rm -rf public/demo \
 && npm run build \
 && node scripts/check-bundle.mjs .next

FROM node:24-trixie-slim
# The server needs only `node`: drop npm, npx and corepack (and everything
# they bundle) from the runtime image.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
      /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
COPY docker-entrypoint.sh /usr/local/bin/twoofus-web
# The image's "node" user; compose adds group 10001 to read secrets.
USER 1000:1000
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/offline.html').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
ENTRYPOINT ["/usr/local/bin/twoofus-web"]
