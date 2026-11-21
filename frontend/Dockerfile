# Development image for the frontend (Phase 0): runs the Vite dev server.
# The production image (static build served by a tiny web server) comes in Phase 8.
FROM node:22-alpine

WORKDIR /app

# Install dependencies first so this layer is cached until package*.json changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]
