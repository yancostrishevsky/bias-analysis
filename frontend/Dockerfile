FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build -- --configuration production

FROM nginx:1.27-alpine

ENV PORT=8080 \
    API_BASE_URL=/api

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.d/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
COPY --from=build /app/dist/bias-analysis-frontend/browser/ /usr/share/nginx/html/
RUN chmod +x /docker-entrypoint.d/40-runtime-config.sh

EXPOSE 8080
