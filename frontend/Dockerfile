# Виви — фронтенд: сборка Vite, раздача через nginx
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Конфиг nginx монтируется из ./deploy/nginx.conf через docker-compose
EXPOSE 80
