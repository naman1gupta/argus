FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.d/05-argus-resolver.envsh /docker-entrypoint.d/
# Only substitute ARGUS_* so nginx's own $host / $uri variables survive envsubst.
ENV NGINX_ENVSUBST_FILTER=^ARGUS_
EXPOSE 80
