FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_FREIGHT_MAP_TILE_URL
ARG NEXT_PUBLIC_FREIGHT_MAP_TILE_ATTRIBUTION
ENV NEXT_PUBLIC_FREIGHT_MAP_TILE_URL=$NEXT_PUBLIC_FREIGHT_MAP_TILE_URL
ENV NEXT_PUBLIC_FREIGHT_MAP_TILE_ATTRIBUTION=$NEXT_PUBLIC_FREIGHT_MAP_TILE_ATTRIBUTION
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM deps AS test
COPY . .
CMD ["npm", "test"]

FROM deps AS production-deps
RUN npm prune --omit=dev --ignore-scripts

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=production-deps /app/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "run", "start"]
