# QR Time Tracking - Production Deploy (deluxfences.com)

Bu dokuman, QR Time Tracking / Cloudia modulunu **mevcut ana siteyi bozmadan** `deluxfences.com` altinda path bazli yayina almak icindir.

## Hedef

- Ana site: `https://deluxfences.com/` (dokunulmaz)
- FastAPI module pathleri:
  - `/shift`
  - `/time`
  - `/admin-time`
  - `/register-device`
  - `/static` (guvenli fallback ile)
- Uygulama klasoru: `/var/www/shift`
- FastAPI bind: `127.0.0.1:8010`

## 1) Sunucu Hazirlik

```bash
sudo mkdir -p /var/www/shift
cd /var/www/shift
git clone https://github.com/SanliData/shift.git .
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-prod.txt
mkdir -p data
```

## 2) Production .env

`/var/www/shift/.env`:

```env
BASE_URL=https://deluxfences.com
TIMEZONE=Europe/Berlin
ENV=production
DATABASE_URL=sqlite:///./data/app.db
```

QR formati bu durumda:
`https://deluxfences.com/time?vehicle=vehicle-01`

Kayitsiz cihaz `/time` acarsa production modunda:
`https://deluxfences.com/` adresine yonlenir.

## 3) Uvicorn test

```bash
cd /var/www/shift
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

## 4) Nginx config (ana siteyi bozmadan)

Asagidaki location bloklarini mevcut `server {}` icine ekleyin.

```nginx
# Main site stays default.

location /shift {
    proxy_pass http://127.0.0.1:8010/shift;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /time {
    proxy_pass http://127.0.0.1:8010/time;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /admin-time {
    proxy_pass http://127.0.0.1:8010/admin-time;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Yönetici oturumu: /admin/login, /admin/logout; zorunlu şifre değişimi: /admin-change-password
location /admin {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /admin-change-password {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /admin-forgot-password {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /admin-reset-password {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /register-device {
    proxy_pass http://127.0.0.1:8010/register-device;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Personel ön kayıt: /register-self → 302 ile güncel token URL’sine; asıl form /worker-register/{token}
location /register-self {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /worker-register {
    proxy_pass http://127.0.0.1:8010;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /register-self-vehicle {
    proxy_pass http://127.0.0.1:8010/register-self-vehicle;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Safe static handling:
# 1) existing site static file varsa onu kullan
# 2) yoksa shift module static'e proxy et
location /static/ {
    try_files $uri @shift_static;
}

location @shift_static {
    proxy_pass http://127.0.0.1:8010/static/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Nginx kontrol:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 5) Systemd service (onerilen)

`/etc/systemd/system/shift.service`:

```ini
[Unit]
Description=Shift FastAPI Service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/shift
Environment="PYTHONUNBUFFERED=1"
ExecStart=/var/www/shift/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable shift
sudo systemctl start shift
sudo systemctl status shift
```

## 6) PM2 alternatifi

```bash
cd /var/www/shift
pm2 start ".venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010" --name shift
pm2 save
pm2 startup
```

## 7) SSL (Certbot)

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d deluxfences.com -d www.deluxfences.com
```

## 8) Post-deploy kontrol

- `https://deluxfences.com/` (ana site calisiyor)
- `https://deluxfences.com/shift`
- `https://deluxfences.com/admin-time`
- `https://deluxfences.com/time?vehicle=vehicle-01`
- `https://deluxfences.com/register-device?token=...`
- `https://deluxfences.com/register-self-vehicle` (araç / iş makinesi ön kayıt formu)

## Notlar

- Database sqlite oldugu icin `data/` dizinine yazma izni gereklidir.
- Production icin ileride PostgreSQL'e gecis onerilir.
- `.env` ve `data/app.db` dosyalari repoya commit edilmemelidir.
