# Minos Studio — static build served by nginx, which also proxies /v1 to the API.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# The demo page imports the example rule sets from ../examples.
COPY --from=examples . /examples
RUN npx vite build --outDir dist

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
