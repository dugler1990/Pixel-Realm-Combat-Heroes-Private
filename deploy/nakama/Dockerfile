# Compile the TypeScript module, then bake it into the pinned Nakama image.
FROM node:22-alpine AS build
WORKDIR /backend
COPY package.json ./
RUN npm install
COPY tsconfig.json ./
COPY src ./src
RUN npx tsc

FROM registry.heroiclabs.com/heroiclabs/nakama:3.42.0
COPY --from=build /backend/build/index.js /nakama/data/modules/build/index.js
