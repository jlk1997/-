FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
COPY apps/client/package.json ./apps/client/
COPY apps/studio/package.json ./apps/studio/
COPY packages ./packages
COPY apps/client ./apps/client
COPY apps/studio ./apps/studio
COPY apps/creator-connector ./apps/creator-connector
ARG TARO_APP_API_URL=/api/v1
ENV TARO_APP_API_URL=$TARO_APP_API_URL
RUN npm install --legacy-peer-deps
RUN apk add --no-cache zip \
 && mkdir -p /connector-out \
 && cd /app/apps/creator-connector \
 && zip -r /connector-out/bityin-connector.zip . -x 'node_modules/*' -x '*.git*'
WORKDIR /app/apps/client
RUN npm run build:h5
WORKDIR /app/apps/studio
RUN npm run build

FROM nginx:alpine
COPY apps/client/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/apps/client/dist-h5 /usr/share/nginx/html
COPY --from=builder /app/apps/studio/dist /usr/share/nginx/html/studio
COPY --from=builder /connector-out/bityin-connector.zip /usr/share/nginx/html/connector/bityin-connector.zip
COPY apps/ops-console/index.html /usr/share/nginx/html/ops/index.html
EXPOSE 80
