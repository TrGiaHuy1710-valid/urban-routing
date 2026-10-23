import os
import osmnx as ox
from app.config import Config

ox.settings.use_cache = True
ox.settings.log_console = False

def ensure_data_dir():
    os.makedirs(Config.DATA_DIR, exist_ok=True)

def load_graph_from_file():
    """
    Chỉ đọc file graphml đã tải sẵn.
    Nếu chưa có thì thông báo hướng dẫn chạy prepare_graph.py.
    """
    ensure_data_dir()
    path = Config.MAP_FILE

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"❌ Không tìm thấy file bản đồ '{path}'. "
            f"Hãy chạy trước lệnh: python prepare_graph.py"
        )

    print(f"✅ Đang tải đồ thị từ file: {path}")
    G = ox.io.load_graphml(path)

    # Kiểm tra sơ bộ
    n, m = len(G.nodes), len(G.edges)
    print(f"→ Đồ thị có {n} nút và {m} cạnh.")
    return G

