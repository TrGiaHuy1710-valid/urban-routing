from flask import render_template, request, flash
from . import bp
from .graph_loader import load_graph_from_file
from .services import dijkstra_shortest_path , astar_shortest_path
from .utils import geocode_any, nearest_node
from .visualizer import draw_route_map

_G = None

@bp.route('/', methods=['GET', 'POST'])
def index():
    if request.method == "POST":
        try:
            # Lấy địa chỉ/tọa độ từ form
            start_input = request.form.get("start_place", "").strip()
            end_input = request.form.get("end_place", "").strip()

            if not start_input or not end_input:
                flash("Vui lòng nhập đầy đủ điểm đầu và điểm cuối!")
                return render_template("index.html")

            # Load graph (chỉ 1 lần)
            global _G
            if _G is None:
                print(" Đang tải bản đồ...")
                _G = load_graph_from_file()
                print(" Đã tải xong!")

            #  TỰ ĐỘNG CHUYỂN ĐỊA CHỈ -> TỌA ĐỘ
            print(f"📍 Đang tìm: {start_input}")
            start_lat, start_lon = geocode_any(start_input)
            print(f"   → Tọa độ: {start_lat:.6f}, {start_lon:.6f}")
            
            print(f"🏁 Đang tìm: {end_input}")
            end_lat, end_lon = geocode_any(end_input)
            print(f"   → Tọa độ: {end_lat:.6f}, {end_lon:.6f}")

            #  TÌM NODE GẦN NHẤT
            print(" Đang tìm node gần nhất trên bản đồ...")
            start_node = nearest_node(_G, start_lat, start_lon)
            end_node = nearest_node(_G, end_lat, end_lon)
            print(f"   → Start node: {start_node}")
            print(f"   → End node: {end_node}")

            if start_node == end_node:
                flash("Hai điểm quá gần nhau! Vui lòng chọn điểm xa hơn.")
                return render_template("index.html")

            #  DÙNG DIJKSTRA TỰ THIẾT KẾ
            print(" Đang chạy thuật toán Dijkstra...")
            result = dijkstra_shortest_path(_G, start_node, end_node)
            
            # #  DÙNG A* TỰ THIẾT KẾ
            # print(" Đang chạy thuật toán A*...")
            # result = astar_shortest_path(_G, start_node, end_node)
            
            if result is None:
                flash("Không tìm thấy đường đi giữa 2 điểm!")
                return render_template("index.html")
            
            print(f" Tìm thấy đường đi: {result['length_km']:.3f} km")

            #  VẼ BẢN ĐỒ
            fmap = draw_route_map(
                polyline_latlon=result["edges_latlon"],
                start_latlon=(start_lat, start_lon),
                end_latlon=(end_lat, end_lon),
                length_km=result["length_km"],
                node_list=result["nodes"],
                graph=_G
            )

            return render_template(
                "route_result.html",
                start=start_input,
                end=end_input,
                map_html=fmap._repr_html_(),
                length_km=result["length_km"],
                algorithm=result.get("algorithm", "Unknown"),
                time_ms=result.get("time_ms", 0),
                nodes_explored=result.get("nodes_explored", 0)
            )

        except ValueError as e:
            flash(f"Lỗi nhập liệu: {str(e)}")
            return render_template("index.html")
        except Exception as e:
            flash(f"Lỗi: {str(e)}")
            print(f"❌ Chi tiết lỗi: {e}")
            import traceback
            traceback.print_exc()
            return render_template("index.html")

    return render_template("index.html")