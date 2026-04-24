# NOVARCHIVE - QR Mesai Takip Demo Modülü

Bu proje, mevcut Novarchive yapısını bozmadan ayrı route'larda çalışan QR mesai takip demo modülüdür.

## Özellikler

- Mobil uygulama yok, tamamen web tabanlı.
- QR akışı: `/time?vehicle=vehicle-01`
- Cihaz kayıtlı değilse otomatik yönlendirme:
  - `https://novarchive.org/ui/index.html`
- Cihaz kayıtlıysa:
  - **Mesai Başlat**
  - **Mesai Bitir**
- Kurallar:
  - Aynı çalışan aktif mesai varken tekrar başlatamaz.
  - Aktif mesai yoksa bitirilemez.
  - Günlük 8 saat (480 dk) üzeri fazla mesaiye yazılır.
  - Zaman damgaları Europe/Berlin timezone ile işlenir.
- Basit admin-time panel:
  - Çalışan listesi
  - Aktif mesailer
  - Tamamlanan mesailer
  - Toplam dakika ve fazla mesai
  - Tarih/çalışan/araç filtreleri
  - CSV ve Excel export
- Araç QR sayfası:
  - `/admin/vehicles`
  - Her araç için `/time?vehicle=...` QR görseli
- Import ve dashboard:
  - `/admin-time/import` (Excel yükleme)
  - `/admin-time/dashboard` (KPI + araç/çalışan/aylık özet)
  - `/admin-time/reports` (detay filtre + rapor export)
- Rapor export türleri:
  - günlük
  - haftalık
  - aylık
  - çalışan bazlı fazla mesai
  - araç/şantiye bazlı
- Cihaz kayıt akışı:
  - `/admin/register-device` ile token link üretilir
  - `/register-device?token=...` cihazda açılınca cookie yazılır

## Demo Veri

İlk açılışta otomatik eklenir:

- Employees:
  - Mehmet Yilmaz
  - Ali Demir
- Vehicles:
  - vehicle-01
  - vehicle-02

## Kurulum

```bash
cd sanli_time_tracker
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
```

## Çalıştırma

```bash
uvicorn app.main:app --reload
```

Tarayıcı:

- Ana sayfa: `http://127.0.0.1:8000/`
- Mesai ekranı: `http://127.0.0.1:8000/time?vehicle=vehicle-01`
- Admin: `http://127.0.0.1:8000/admin-time`
- Cihaz kayıt link oluşturma: `http://127.0.0.1:8000/admin/register-device`
- Araç QR yönetimi: `http://127.0.0.1:8000/admin/vehicles`
- Import: `http://127.0.0.1:8000/admin-time/import`
- Dashboard: `http://127.0.0.1:8000/admin-time/dashboard`
- Reports: `http://127.0.0.1:8000/admin-time/reports`

## Veritabanı

SQLite dosyası uygulama dizininde oluşur:

- `sanli_time_tracker.db`

Ek tablolar:
- `monthly_summaries`
- `payroll_exports`
- `imported_files`

## Test Adımları (Demo)

1) Kayıtsız cihaz testi:
- Tarayıcıda cookie temizleyin.
- `http://127.0.0.1:8000/time?vehicle=vehicle-01` açın.
- `https://novarchive.org/ui/index.html` yönlendirmesi beklenir.

2) Cihaz kayıt testi:
- `http://127.0.0.1:8000/admin-time/register-device` üzerinden Mehmet Yilmaz seçip link üretin.
- Aynı cihazda linki açın.
- Sonra `http://127.0.0.1:8000/time?vehicle=vehicle-01` açın.
- Mesai ekranı görünmelidir.

3) QR test linkleri:
- `http://127.0.0.1:8000/time?vehicle=vehicle-01`
- `http://127.0.0.1:8000/time?vehicle=vehicle-02`

## Not

- İlk sürüm bilinçli olarak basit tutulmuştur.
- İleride PostgreSQL geçişi için `DATABASE_URL` kolayca değiştirilebilir.
- Cookie güvenliği:
  - `httponly=True`
  - `samesite=lax`
  - `secure`: üretimde `COOKIE_SECURE=true` env değişkeni ile aktif edin.

## Production Deployment Notları

### 1) Uvicorn ile çalıştırma

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2) Nginx Reverse Proxy (örnek)

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3) systemd ile servis (Linux)

`/etc/systemd/system/sanli-time-tracker.service`:

```ini
[Unit]
Description=Sanli Time Tracker
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/sanli_time_tracker
Environment=COOKIE_SECURE=true
ExecStart=/opt/sanli_time_tracker/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Komutlar:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sanli-time-tracker
sudo systemctl start sanli-time-tracker
```

### 4) PM2 ile çalıştırma (alternatif)

```bash
pm2 start \"uvicorn app.main:app --host 127.0.0.1 --port 8000\" --name sanli-time-tracker
pm2 save
```
