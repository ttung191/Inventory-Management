# Inventory Management

Bản nâng cấp này được dựng lại từ ý tưởng của repo gốc `ttung191/Inventory-Management`, nhưng được tái cấu trúc theo hướng ổn định hơn, dễ mở rộng hơn và sẵn sàng để dùng như một bản demo gần production.

## Điểm nổi bật
~
- Dashboard quản lý kho bằng **Streamlit**
- **SQLite** với schema rõ ràng, có ràng buộc dữ liệu và ghi giao dịch theo kiểu transaction
- Chặn **âm kho** ngay ở tầng nghiệp vụ
- Quản lý **danh mục hàng hóa**: thêm, cập nhật, tạm ngưng kinh doanh
- Gợi ý **reorder / nhập thêm hàng** dựa trên nhu cầu bình quân và lead time
- KPI vận hành: tổng giá trị tồn, số SKU rủi ro, dòng tiền nhập/xuất, top mặt hàng bán chạy
- Lọc giao dịch theo ngày, loại giao dịch, mặt hàng
- **Xuất CSV**
- **AI Copilot**:
  - dùng Gemini nếu bạn cấu hình API key
  - tự động fallback sang chế độ phân tích rule-based nếu không có API
- Bộ **test tự động** cho các luồng nghiệp vụ quan trọng
- Có sẵn **Dockerfile** để triển khai nhanh
- Có script tạo **dữ liệu demo** ngay lập tức

## Cấu trúc thư mục

```text
inventory_management_flawless/
├── app.py
├── Dockerfile
├── IMPROVEMENTS.md
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── .streamlit/
│   └── config.toml
├── data/
│   └── inventory.db
├── inventory/
│   ├── __init__.py
│   ├── ai_agent.py
│   ├── analytics.py
│   ├── config.py
│   ├── database.py
│   ├── demo_seed.py
│   └── exceptions.py
├── scripts/
│   └── init_demo.py
└── tests/
    ├── test_analytics.py
    └── test_repository.py
```

## Cài đặt nhanh

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/init_demo.py --reset --days 240
streamlit run app.py
```

## Cấu hình AI

Tạo file `.env` từ `.env.example`:

```bash
cp .env.example .env
```

Điền một trong hai biến sau:

```env
GEMINI_API_KEY=your_key_here
# hoặc
GOOGLE_API_KEY=your_key_here
```

Nếu không có API key, app vẫn chạy bình thường ở chế độ fallback.

## Chạy test

```bash
python -m unittest discover -s tests -v
```

## Docker

```bash
docker build -t inventory-flawless .
docker run -p 8501:8501 inventory-flawless
```

## Luồng dữ liệu

1. `scripts/init_demo.py` khởi tạo schema và dữ liệu mẫu
2. `inventory/database.py` chịu trách nhiệm toàn bộ CRUD + transaction + validate
3. `inventory/analytics.py` sinh KPI, xu hướng, reorder suggestion
4. `inventory/ai_agent.py` tổng hợp ngữ cảnh và trả lời AI / fallback
5. `app.py` dựng UI Streamlit

## Gợi ý mở rộng tiếp theo

- phân quyền người dùng
- nhiều kho / nhiều chi nhánh
- phiếu nhập / xuất PDF
- cảnh báo qua email / Telegram / Zalo
- API backend riêng bằng FastAPI
- dự báo nhu cầu nâng cao bằng ML
