# 🏹 Thợ Săn Điểm Vào — Mobile App (PWA + FastAPI)

Phiên bản mobile của ứng dụng phân tích cổ phiếu, chạy trên điện thoại không cần cài từ Store.

## 📂 Cấu trúc thư mục

```
mobile-app/
├── api/
│   ├── main.py          ← FastAPI backend (REST API)
│   └── requirements.txt ← Thư viện Python cần cài
├── web/
│   ├── index.html       ← Giao diện PWA chính
│   ├── style.css        ← CSS dark theme
│   ├── app.js           ← Logic JavaScript
│   ├── manifest.json    ← Cấu hình PWA (cài app)
│   └── sw.js            ← Service Worker (offline)
├── start_server.bat     ← Script khởi động 1-click
└── README.md
```

## 🚀 Cách chạy

### Cách 1: 1-Click (Windows)
Chạy file `start_server.bat` — script sẽ tự cài thư viện và khởi động server.

### Cách 2: Thủ công

```bash
# Cài thư viện
pip install -r api/requirements.txt

# Chạy server (từ thư mục mobile-app/)
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

## 📱 Truy cập trên điện thoại

1. **Kết nối điện thoại và máy tính vào cùng mạng WiFi**
2. Tìm IP máy tính: mở CMD → gõ `ipconfig` → tìm dòng `IPv4 Address`
3. Mở trình duyệt (Safari/Chrome) trên điện thoại, vào:
   ```
   http://<IP-máy-tính>:8000/app/
   ```
4. Trong Settings của app → nhập API URL: `http://<IP-máy-tính>:8000`

## 📲 Cài thành App (không cần Store)

### iOS (Safari):
1. Mở URL trên trên Safari
2. Nhấn nút **Chia sẻ** (biểu tượng hộp có mũi tên lên)
3. Chọn **"Thêm vào Màn hình chính"**
4. App xuất hiện trên màn hình như ứng dụng thật!

### Android (Chrome):
1. Mở URL trên Chrome
2. Nhấn menu ⋮ → **"Thêm vào màn hình chính"** hoặc **"Cài đặt ứng dụng"**
3. Xác nhận → App được cài

## 🔌 API Endpoints

| Method | URL | Chức năng |
|--------|-----|-----------|
| GET | `/api/analyze/{ticker}` | Phân tích kỹ thuật đầy đủ |
| GET | `/api/chart/{ticker}` | Dữ liệu OHLCV cho biểu đồ |
| GET | `/api/portfolio` | Lấy danh mục |
| POST | `/api/portfolio` | Thêm vị thế |
| DELETE | `/api/portfolio/{index}` | Xóa vị thế |
| GET | `/api/portfolio/refresh` | Cập nhật giá danh mục |
| POST | `/api/telegram/{ticker}` | Gửi phân tích về Telegram |

## 📋 Yêu cầu

- Python 3.9+
- Cài đặt các thư viện trong `api/requirements.txt`
- Máy tính và điện thoại cùng mạng WiFi

## ⚠️ Lưu ý

- Server phải **đang chạy** thì điện thoại mới dùng được
- Nếu muốn dùng 24/7 từ bất kỳ đâu, cần deploy lên VPS (Render, Railway, v.v.)
- Dữ liệu cổ phiếu lấy từ Yahoo Finance (có thể delay ~15 phút)
