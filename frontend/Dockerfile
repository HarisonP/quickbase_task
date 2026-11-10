# The Vite dev server. It serves the UI and forwards /api to the backend (API_PROXY_TARGET).
FROM node:24-slim

WORKDIR /app

# Dependencies first: this layer is cached until package.json or package-lock.json change.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
