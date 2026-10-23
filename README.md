# Urban Routing Flask v2

Ứng dụng Flask tính **đường đi ngắn nhất** trong khu vực **Hà Đông – Hà Nội** bằng đồ thị OSMnx.

## Cấu trúc
- `app/routing/`: chứa toàn bộ logic tính đường đi
- `data/`: chứa file `.graphml` của Hà Đông (tải 1 lần)
- `templates/`: giao diện web
- `static/`: CSS

## Cách chạy
```bash
pip install -r requirements.txt
python run.py
