# Shared BitTune proxy locations. Copied to /etc/nginx/snippets/bittune_locations.inc
# $bittune_hsts is set by the parent server (empty on HTTP, a max-age on HTTPS).

client_max_body_size 50m;

gzip on;
gzip_vary on;
gzip_min_length 256;
gzip_comp_level 5;
gzip_types text/plain text/css application/javascript application/json application/xml image/svg+xml;

location ~ ^/api/v1/workbench/sessions/[^/]+/bounce$ {
    client_max_body_size 200m;
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_request_buffering off;
}

location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 10s;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
    proxy_request_buffering off;
}

location = /health {
    proxy_pass http://127.0.0.1:8000/health;
    proxy_set_header Host $host;
}

location = /livez {
    proxy_pass http://127.0.0.1:8000/livez;
    proxy_set_header Host $host;
}

location /vibe-sorcery/ {
    proxy_pass http://127.0.0.1:19000;
    proxy_http_version 1.1;
    proxy_set_header Host minio:9000;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}

location ~* "\.[0-9a-f]{8,}\.(?:js|css)$" {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
    add_header Strict-Transport-Security $bittune_hsts always;
}

location ~* \.woff2$ {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
    add_header Strict-Transport-Security $bittune_hsts always;
}

location ~* \.(?:js|css)$ {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    expires -1;
    add_header Cache-Control "no-cache";
    add_header Strict-Transport-Security $bittune_hsts always;
}

location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    expires -1;
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Strict-Transport-Security $bittune_hsts always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
}
