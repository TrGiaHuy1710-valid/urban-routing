import heapq
import time
from math import radians, sin, cos, sqrt, atan2

def haversine_distance(lat1, lon1, lat2, lon2):
    """Tính khoảng cách Haversine giữa 2 điểm (mét)"""
    R = 6371000  # Bán kính Trái Đất (mét)
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    
    return R * c


def dijkstra_shortest_path(G, start_node, end_node):
    """
    Thuật toán Dijkstra tự thiết kế
    """
    start_time = time.time()
    
    # Khởi tạo
    distances = {node: float('inf') for node in G.nodes()} #lưu khoảng cách ngắn nhất hiện tại đến mỗi node.
    distances[start_node] = 0
    previous = {node: None for node in G.nodes()} #lưu node trước đó trên đường đi ngắn nhất.
    visited = set() #tập các node đã được xử lý.
    
    # Priority queue: (distance, node)
    pq = [(0, start_node)]
    
    print(f"\n🔵 DIJKSTRA: Bắt đầu từ {start_node} đến {end_node}")
    nodes_explored = 0
    
    while pq:
        current_dist, current_node = heapq.heappop(pq) #lấy node có khoảng cách nhỏ nhất hiện tại.
        
        if current_node in visited: 
            continue
        
        visited.add(current_node)
        nodes_explored += 1
        
        # Tìm thấy đích!
        if current_node == end_node:
            break
        
        # Duyệt các node kề
        for neighbor in G.neighbors(current_node): #Duyệt từng đỉnh kề neighbor của node hiện tại.
            if neighbor in visited:
                continue
            
            # Lấy trọng số cạnh
            edge_data = G.get_edge_data(current_node, neighbor)
            if isinstance(edge_data, dict) and 0 in edge_data:
                weight = edge_data[0].get('length', 1)
            else:
                weight = edge_data.get('length', 1)
            
            new_dist = current_dist + weight
            
            if new_dist < distances[neighbor]: #Nếu tổng khoảng cách mới new_dist nhỏ hơn khoảng cách cũ → cập nhật:
                distances[neighbor] = new_dist
                previous[neighbor] = current_node
                heapq.heappush(pq, (new_dist, neighbor))
    
    elapsed_time = time.time() - start_time
    
    # Kiểm tra có tìm thấy không
    if distances[end_node] == float('inf'):
        print(f"❌ Không tìm thấy đường đi")
        return None
    
    # Truy vết đường đi
    path = []
    current = end_node
    while current is not None:
        path.append(current)
        current = previous[current]
    path.reverse()
    
    # Lấy tọa độ
    coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in path]
    total_length = distances[end_node]
    
    print(f"✅ Tìm thấy sau {nodes_explored} nodes")
    print(f"📏 Chiều dài: {total_length/1000:.3f} km")
    print(f"⏱️  Thời gian: {elapsed_time*1000:.2f} ms")
    
    return {
        "nodes": path,
        "length_m": total_length,
        "length_km": total_length / 1000.0,
        "edges_latlon": coords,
        "algorithm": "Dijkstra",
        "time_ms": elapsed_time * 1000,
        "nodes_explored": nodes_explored
    }


def astar_shortest_path(G, start_node, end_node):
    """
    Thuật toán A* tự thiết kế
    Heuristic: khoảng cách Haversine đến đích
    """
    start_time = time.time()
    
    # Lấy tọa độ node đích để tính heuristic
    end_lat = G.nodes[end_node]['y']
    end_lon = G.nodes[end_node]['x']
    
    # Khởi tạo
    g_scores = {node: float('inf') for node in G.nodes()}
    g_scores[start_node] = 0
    
    previous = {node: None for node in G.nodes()}
    visited = set()
    
    # Priority queue: (f_score, node)
    # f_score = g_score + heuristic
    start_lat = G.nodes[start_node]['y']
    start_lon = G.nodes[start_node]['x']
    h_start = haversine_distance(start_lat, start_lon, end_lat, end_lon)
    
    pq = [(h_start, start_node)]
    
    print(f"\n🟢 A*: Bắt đầu từ {start_node} đến {end_node}")
    nodes_explored = 0
    
    while pq:
        _, current_node = heapq.heappop(pq)
        
        if current_node in visited:
            continue
        
        visited.add(current_node)
        nodes_explored += 1
        
        # Tìm thấy đích!
        if current_node == end_node:
            break
        
        current_g = g_scores[current_node]
        
        # Duyệt các node kề
        for neighbor in G.neighbors(current_node):
            if neighbor in visited:
                continue
            
            # Lấy trọng số cạnh
            edge_data = G.get_edge_data(current_node, neighbor)
            if isinstance(edge_data, dict) and 0 in edge_data:
                weight = edge_data[0].get('length', 1)
            else:
                weight = edge_data.get('length', 1)
            
            new_g = current_g + weight
            
            if new_g < g_scores[neighbor]:
                g_scores[neighbor] = new_g
                previous[neighbor] = current_node
                
                # Tính heuristic (khoảng cách thẳng đến đích)
                neighbor_lat = G.nodes[neighbor]['y']
                neighbor_lon = G.nodes[neighbor]['x']
                h = haversine_distance(neighbor_lat, neighbor_lon, end_lat, end_lon)
                
                f_score = new_g + h
                heapq.heappush(pq, (f_score, neighbor))
    
    elapsed_time = time.time() - start_time
    
    # Kiểm tra
    if g_scores[end_node] == float('inf'):
        print(f"❌ Không tìm thấy đường đi")
        return None
    
    # Truy vết
    path = []
    current = end_node
    while current is not None:
        path.append(current)
        current = previous[current]
    path.reverse()
    
    coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in path]
    total_length = g_scores[end_node]
    
    print(f"✅ Tìm thấy sau {nodes_explored} nodes")
    print(f"📏 Chiều dài: {total_length/1000:.3f} km")
    print(f"⏱️  Thời gian: {elapsed_time*1000:.2f} ms")
    
    return {
        "nodes": path,
        "length_m": total_length,
        "length_km": total_length / 1000.0,
        "edges_latlon": coords,
        "algorithm": "A*",
        "time_ms": elapsed_time * 1000,
        "nodes_explored": nodes_explored
    }


def compare_algorithms(G, start_node, end_node):
    """
    So sánh Dijkstra vs A*
    """
    print("\n" + "="*60)
    print("🏁 SO SÁNH THUẬT TOÁN")
    print("="*60)
    
    # Chạy Dijkstra
    result_dijkstra = dijkstra_shortest_path(G, start_node, end_node)
    
    # Chạy A*
    result_astar = astar_shortest_path(G, start_node, end_node)
    
    if result_dijkstra and result_astar:
        print("\n" + "="*60)
        print("📊 KẾT QUẢ SO SÁNH:")
        print("="*60)
        print(f"{'Thuật toán':<15} {'Thời gian (ms)':<15} {'Nodes':<10} {'Khoảng cách (km)'}")
        print("-"*60)
        print(f"{'Dijkstra':<15} {result_dijkstra['time_ms']:<15.2f} {result_dijkstra['nodes_explored']:<10} {result_dijkstra['length_km']:.3f}")
        print(f"{'A*':<15} {result_astar['time_ms']:<15.2f} {result_astar['nodes_explored']:<10} {result_astar['length_km']:.3f}")
        print("-"*60)
        
        speedup = result_dijkstra['time_ms'] / result_astar['time_ms']
        node_reduction = (1 - result_astar['nodes_explored'] / result_dijkstra['nodes_explored']) * 100
        
        print(f"\n🚀 A* nhanh hơn: {speedup:.2f}x")
        print(f"🔍 A* duyệt ít hơn: {node_reduction:.1f}%")
        print("="*60 + "\n")
    
    # Mặc định trả về kết quả A* (thường nhanh hơn)
    return result_astar if result_astar else result_dijkstra


def shortest_path_by_length(G, s_node, e_node):
    """
    Wrapper function - giờ so sánh cả 2 thuật toán
    """
    return compare_algorithms(G, s_node, e_node)