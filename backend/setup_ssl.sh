#!/bin/bash
# Update nginx config to serve on port 443 with SSL + HTTP→HTTPS redirect
NGINX_CONF=$(ls /etc/nginx/sites-enabled/*)
echo "Updating: $NGINX_CONF"

cat > "$NGINX_CONF" << 'CONF'
server {
    listen 80;
    server_name portfolio.srv1211053.hstgr.cloud;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name portfolio.srv1211053.hstgr.cloud;

    ssl_certificate /etc/letsencrypt/live/portfolio.srv1211053.hstgr.cloud/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/portfolio.srv1211053.hstgr.cloud/privkey.pem;

    root /root/IBKR_investment_tracker/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
CONF

nginx -t && nginx -s reload
echo "Done! Visit https://portfolio.srv1211053.hstgr.cloud"
