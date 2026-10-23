import folium
from app.config import Config

def draw_route_map(polyline_latlon, start_latlon, end_latlon, length_km, node_list=None, graph=None):
    """
    Vẽ bản đồ với TẤT CẢ nodes và edges của graph
    
    Args:
        polyline_latlon: List các tọa độ [(lat, lon), ...] của đường đi
        start_latlon: Tọa độ điểm bắt đầu
        end_latlon: Tọa độ điểm kết thúc
        length_km: Chiều dài đường đi (km)
        node_list: List các node ID đi qua (optional)
        graph: NetworkX graph để hiển thị tất cả nodes và edges
    """
    fmap = folium.Map(
        location=Config.DEFAULT_CENTER, 
        zoom_start=Config.DEFAULT_ZOOM, 
        control_scale=True
    )

    # ✅ VẼ TẤT CẢ CÁC EDGE (cạnh) TRÊN BẢN ĐỒ
    if graph:
        print("🔷 Đang vẽ tất cả các cạnh...")
        edge_count = 0
        
        for u, v, data in graph.edges(data=True):
            # Lấy tọa độ 2 đầu của cạnh
            if 'geometry' in data:
                # Nếu edge có geometry (đường cong)
                coords = [(point[1], point[0]) for point in data['geometry'].coords]
            else:
                # Nếu không có geometry thì nối thẳng 2 node
                u_lat = graph.nodes[u].get('y')
                u_lon = graph.nodes[u].get('x')
                v_lat = graph.nodes[v].get('y')
                v_lon = graph.nodes[v].get('x')
                
                if u_lat and u_lon and v_lat and v_lon:
                    coords = [(u_lat, u_lon), (v_lat, v_lon)]
                else:
                    continue
            
            # Kiểm tra xem edge có nằm trên đường đi không
            is_on_path = False
            if node_list:
                for i in range(len(node_list) - 1):
                    if (node_list[i] == u and node_list[i+1] == v) or \
                       (node_list[i] == v and node_list[i+1] == u):
                        is_on_path = True
                        break
            
            # Vẽ edge với màu khác nhau
            folium.PolyLine(
                coords,
                color='blue' if is_on_path else '#cccccc',
                weight=5 if is_on_path else 2,
                opacity=0.9 if is_on_path else 0.5,
                tooltip=f"Edge: {u} → {v}" if is_on_path else None
            ).add_to(fmap)
            
            edge_count += 1
        
        print(f"   → Đã vẽ {edge_count} cạnh")

    # ✅ VẼ TẤT CẢ CÁC NODE TRÊN BẢN ĐỒ
    if graph:
        print("📍 Đang vẽ tất cả các node...")
        node_count = 0
        
        for node_id, data in graph.nodes(data=True):
            lat = data.get('y')
            lon = data.get('x')
            
            if lat and lon:
                # Kiểm tra xem node có nằm trên đường đi không
                is_on_path = node_list and node_id in node_list
                
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=6 if is_on_path else 3,
                    color='white' if is_on_path else '#ff8800',
                    fill=True,
                    fillColor='#0066ff' if is_on_path else '#ff8800',
                    fillOpacity=1 if is_on_path else 0.7,
                    weight=2 if is_on_path else 1,
                    popup=f"<b>Node ID:</b> {node_id}<br><b>Tọa độ:</b> {lat:.6f}, {lon:.6f}",
                    tooltip=f"Node: {node_id}" if is_on_path else None
                ).add_to(fmap)
                
                node_count += 1
        
        print(f"   → Đã vẽ {node_count} nodes")

    # Marker điểm bắt đầu (nổi bật nhất)
    folium.Marker(
        start_latlon, 
        icon=folium.Icon(color="green", icon="play", prefix='fa'),
        popup="<b>🟢 Điểm bắt đầu</b>",
        tooltip="Bắt đầu"
    ).add_to(fmap)

    # Marker điểm kết thúc (nổi bật nhất)
    folium.Marker(
        end_latlon, 
        icon=folium.Icon(color="red", icon="flag", prefix='fa'),
        popup="<b>🔴 Điểm kết thúc</b>",
        tooltip="Kết thúc"
    ).add_to(fmap)

    # Label khoảng cách
    if polyline_latlon and len(polyline_latlon) > 0:
        mid_point = polyline_latlon[len(polyline_latlon)//2]
        folium.Marker(
            mid_point,
            icon=folium.DivIcon(
                html=f'''
                <div style="
                    font-size: 14px;
                    font-weight: bold;
                    background: white;
                    padding: 8px 12px;
                    border-radius: 8px;
                    border: 2px solid #0066ff;
                    box-shadow: 0 3px 10px rgba(0,0,0,0.3);
                    white-space: nowrap;
                ">
                    📏 {length_km:.3f} km<br>
                    🔢 {len(polyline_latlon)} nodes
                </div>
                '''
            )
        ).add_to(fmap)

    # Tự động zoom
    if polyline_latlon:
        fmap.fit_bounds(polyline_latlon, padding=(30, 30))

    return fmap