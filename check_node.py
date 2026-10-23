import osmnx as ox

# --- Đọc lại bản đồ đã lưu ---
G = ox.load_graphml("data/hadong_drive.graphml")

# Lấy danh sách tất cả các node trong đồ thị
nodes = list(G.nodes)

# In số lượng node
print(f"Tổng số node: {len(nodes)}")

# Lấy ngẫu nhiên một node đầu tiên
node_id = nodes[5]
print(f"\n🔹 Kiểm tra node ID: {node_id}")

# Lấy toàn bộ thuộc tính của node đó
attrs = G.nodes[node_id]

# In ra toàn bộ thông tin thuộc tính
print("Thuộc tính của node :")
for key, value in attrs.items():
    print(f"  {key}: {value}")
print("\nHoàn tất kiểm tra node.")