# ValoreaX frontend image.
# Builds the Vite app and serves the static bundle via `vite preview`.
FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_* vars are read at build time; Compose passes VITE_API_BASE_URL.
ARG VITE_API_BASE_URL=http://localhost:5001/api/v1
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY
RUN npm run build

EXPOSE 5173
CMD ["npm", "run", "preview"]
