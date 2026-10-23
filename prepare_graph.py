import os
import osmnx as ox

# --- Định nghĩa trực tiếp config ---
PLACE = "Ha Dong District, Hanoi, Vietnam"
NETWORK_TYPE = "all_private" #Số nút: 11155, số cạnh: 28044
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MAP_FILE = os.path.join(DATA_DIR, "hadong_drive.graphml")
# ---------------------------------------------------------------

ox.settings.use_cache = True
ox.settings.log_console = True

os.makedirs(DATA_DIR, exist_ok=True)

print(f"Đang tải bản đồ: {PLACE}")
G = ox.graph_from_place(PLACE, network_type=NETWORK_TYPE, simplify=True)  #Gọi API OSM để lấy dữ liệu bản đồ
ox.io.save_graphml(G, MAP_FILE)

print(f"Đã lưu bản đồ vào: {MAP_FILE}")
print(f"→ Số nút: {len(G.nodes)}, số cạnh: {len(G.edges)}")
print("Hoàn tất.")
