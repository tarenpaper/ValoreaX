# ValoreaX frontend image.
# Builds the Vite app and serves the static bundle via `vite preview`.
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
# Use install (not ci) since this MVP ships without a committed lockfile.
RUN npm install

COPY . .

# VITE_* vars are read at build time; Compose passes VITE_API_BASE_URL.
ARG VITE_API_BASE_URL=http://localhost:5001/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

EXPOSE 5173
CMD ["npm", "run", "preview"]
