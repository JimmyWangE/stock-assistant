FROM node:24-alpine AS build

# 可选：国内构建时传入 npm 镜像地址
ARG NPM_REGISTRY=
WORKDIR /web
COPY package.json package-lock.json ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm ci
COPY . .
RUN npm run build

FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
