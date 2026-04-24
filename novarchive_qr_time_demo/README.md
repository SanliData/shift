# NOVARCHIVE QR Mesai Takip Demo (Local)

Bu modül sadece **local development** için hazırlanmıştır ve mevcut Novarchive arşiv fonksiyonlarını bozmaz.

## Klasör Yapısı

- `app/main.py`
- `app/database.py`
- `app/models.py`
- `app/routes/time.py`
- `app/routes/admin_time.py`
- `app/templates/`
- `app/static/`
- `data/app.db`
- `requirements.txt`
- `README.md`

## Local URL'ler

- `http://localhost:8000/time?vehicle=vehicle-01`
- `http://localhost:8000/admin-time`
- `http://localhost:8000/register-device?token=...`
- `http://localhost:8000/ui/index.html` (kayıtsız cihaz fallback)

## Özellikler

- Cihaz token cookie kontrolü
- Kayıtsız cihaz -> `http://localhost:8000/ui/index.html` redirect
- Mesai Başlat / Mesai Bitir
- 8 saat üstü overtime
- Europe/Berlin timezone
- Admin-time paneli
- Register link üretimi
- Excel import/export temel altyapı

## Kurulum

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Çalıştırma

```bash
uvicorn app.main:app --reload
```

## Demo Seed Verileri

- Employees:
  - Mehmet Yilmaz
  - Ali Demir
- Vehicles:
  - vehicle-01
  - vehicle-02

## Test Akışı

1. Kayıtsız cihazla `/time?vehicle=vehicle-01` aç -> `/ui/index.html` redirect.
2. `/admin-time` sayfasından çalışan seçip kayıt linki oluştur.
3. Aynı cihazda `/register-device?token=...` aç.
4. Tekrar `/time?vehicle=vehicle-01` aç -> mesai ekranı görünür.
5. Mesai Başlat / Mesai Bitir test et.
