import osmnx as ox

G = ox.load_graphml("data/hadong_drive.graphml")

# Lấy cạnh đầu tiên
u, v, k, data = list(G.edges(keys=True, data=True))[0]

print(f"Cạnh: {u} → {v}")
for key, value in data.items():
    print(f"  {key}: {value}")

# In riêng độ dài cạnh
print(f"\nTrọng số (weight) = độ dài cạnh: {data['length']:.2f} mét")
