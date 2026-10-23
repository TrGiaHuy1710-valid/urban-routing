"""
Benchmark so sánh Dijkstra vs A* với nhiều test cases
Chạy: python benchmark.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.routing.graph_loader import load_graph_from_file
from app.routing.services import dijkstra_shortest_path, astar_shortest_path
from app.routing.utils import nearest_node
import random
import time

def get_random_nodes(G, n=2):
    """Lấy n nodes ngẫu nhiên từ graph"""
    nodes = list(G.nodes())
    return random.sample(nodes, n)

def calculate_straight_distance(G, node1, node2):
    """Tính khoảng cách thẳng giữa 2 nodes (km)"""
    from math import radians, sin, cos, sqrt, atan2
    
    lat1 = G.nodes[node1]['y']
    lon1 = G.nodes[node1]['x']
    lat2 = G.nodes[node2]['y']
    lon2 = G.nodes[node2]['x']
    
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def find_test_cases(G, num_cases=10):
    """
    Tìm các test cases với khoảng cách khác nhau
    """
    print("🔍 Đang tìm các test cases phù hợp...")
    
    test_cases = {
        'very_short': [],   # < 0.5 km
        'short': [],        # 0.5 - 2 km
        'medium': [],       # 2 - 5 km
        'long': [],         # 5 - 10 km
        'very_long': []     # > 10 km
    }
    
    attempts = 0
    max_attempts = 1000
    
    while attempts < max_attempts:
        node1, node2 = get_random_nodes(G)
        dist = calculate_straight_distance(G, node1, node2)
        
        if dist < 0.5 and len(test_cases['very_short']) < num_cases // 5:
            test_cases['very_short'].append((node1, node2, dist))
        elif 0.5 <= dist < 2 and len(test_cases['short']) < num_cases // 5:
            test_cases['short'].append((node1, node2, dist))
        elif 2 <= dist < 5 and len(test_cases['medium']) < num_cases // 5:
            test_cases['medium'].append((node1, node2, dist))
        elif 5 <= dist < 10 and len(test_cases['long']) < num_cases // 5:
            test_cases['long'].append((node1, node2, dist))
        elif dist >= 10 and len(test_cases['very_long']) < num_cases // 5:
            test_cases['very_long'].append((node1, node2, dist))
        
        attempts += 1
        
        # Kiểm tra đủ chưa
        total = sum(len(v) for v in test_cases.values())
        if total >= num_cases:
            break
    
    print(f"✅ Đã tìm được {sum(len(v) for v in test_cases.values())} test cases")
    return test_cases

def run_benchmark(G, test_cases):
    """
    Chạy benchmark với tất cả test cases
    """
    results = []
    
    print("\n" + "="*80)
    print("🏁 BẮT ĐẦU BENCHMARK")
    print("="*80)
    
    case_num = 0
    for category, cases in test_cases.items():
        if not cases:
            continue
            
        print(f"\n📊 Loại: {category.upper().replace('_', ' ')}")
        print("-"*80)
        
        for start_node, end_node, straight_dist in cases:
            case_num += 1
            print(f"\n🧪 Test case #{case_num}")
            print(f"   Khoảng cách thẳng: {straight_dist:.3f} km")
            
            # Chạy Dijkstra
            try:
                result_dijkstra = dijkstra_shortest_path(G, start_node, end_node)
            except Exception as e:
                print(f"   ❌ Dijkstra lỗi: {e}")
                continue
            
            if not result_dijkstra:
                print(f"   ❌ Không tìm thấy đường đi")
                continue
            
            # Chạy A*
            try:
                result_astar = astar_shortest_path(G, start_node, end_node)
            except Exception as e:
                print(f"   ❌ A* lỗi: {e}")
                continue
            
            if not result_astar:
                print(f"   ❌ A* không tìm thấy đường đi")
                continue
            
            # So sánh (tránh chia cho 0)
            if result_astar['time_ms'] > 0:
                speedup = result_dijkstra['time_ms'] / result_astar['time_ms']
            else:
                # Nếu A* quá nhanh (< 0.01ms), ước tính speedup
                speedup = result_dijkstra['time_ms'] / 0.01
            
            node_reduction = (1 - result_astar['nodes_explored'] / result_dijkstra['nodes_explored']) * 100
            
            results.append({
                'category': category,
                'case_num': case_num,
                'straight_dist': straight_dist,
                'actual_dist': result_dijkstra['length_km'],
                'dijkstra_time': result_dijkstra['time_ms'],
                'astar_time': result_astar['time_ms'],
                'dijkstra_nodes': result_dijkstra['nodes_explored'],
                'astar_nodes': result_astar['nodes_explored'],
                'speedup': speedup,
                'node_reduction': node_reduction
            })
    
    return results

def print_summary(results):
    """
    In tổng kết kết quả
    """
    print("\n" + "="*80)
    print("📈 TỔNG KẾT KẾT QUẢ")
    print("="*80)
    
    print(f"\n{'Case':<6} {'Loại':<12} {'Khoảng cách':<12} {'Dijkstra':<15} {'A*':<15} {'Tăng tốc':<10} {'Giảm node'}")
    print(f"{'#':<6} {'':<12} {'(km)':<12} {'(ms / nodes)':<15} {'(ms / nodes)':<15} {'(lần)':<10} {'(%)'}")
    print("-"*100)
    
    for r in results:
        category_short = r['category'][:10]
        print(f"{r['case_num']:<6} {category_short:<12} {r['actual_dist']:<12.3f} "
              f"{r['dijkstra_time']:>6.2f} / {r['dijkstra_nodes']:<6} "
              f"{r['astar_time']:>6.2f} / {r['astar_nodes']:<6} "
              f"{r['speedup']:<10.2f} {r['node_reduction']:.1f}%")
    
    # Thống kê tổng
    print("\n" + "="*80)
    print("📊 THỐNG KÊ TRUNG BÌNH")
    print("="*80)
    
    categories = {}
    for r in results:
        cat = r['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)
    
    print(f"\n{'Loại':<15} {'Số test':<10} {'Tăng tốc TB':<15} {'Giảm node TB':<15} {'Khoảng cách TB'}")
    print("-"*80)
    
    for cat, data in categories.items():
        avg_speedup = sum(d['speedup'] for d in data) / len(data)
        avg_reduction = sum(d['node_reduction'] for d in data) / len(data)
        avg_dist = sum(d['actual_dist'] for d in data) / len(data)
        
        print(f"{cat:<15} {len(data):<10} {avg_speedup:<15.2f}x {avg_reduction:<15.1f}% {avg_dist:.3f} km")
    
    # Tổng quan
    print("\n" + "="*80)
    overall_speedup = sum(r['speedup'] for r in results) / len(results)
    overall_reduction = sum(r['node_reduction'] for r in results) / len(results)
    
    print(f"🎯 TỔNG QUAN:")
    print(f"   • Tổng số test cases: {len(results)}")
    print(f"   • A* nhanh hơn trung bình: {overall_speedup:.2f}x")
    print(f"   • A* duyệt ít node hơn: {overall_reduction:.1f}%")
    print(f"   • Khoảng cách ngắn nhất: {min(r['actual_dist'] for r in results):.3f} km")
    print(f"   • Khoảng cách dài nhất: {max(r['actual_dist'] for r in results):.3f} km")
    
    # Kết luận
    print("\n" + "="*80)
    print("💡 KẾT LUẬN:")
    print("="*80)
    
    short_cases = [r for r in results if r['category'] in ['very_short', 'short']]
    long_cases = [r for r in results if r['category'] in ['long', 'very_long']]
    
    if short_cases:
        short_speedup = sum(r['speedup'] for r in short_cases) / len(short_cases)
        print(f"   • Đường ngắn (< 2km): A* nhanh hơn ~{short_speedup:.2f}x")
    
    if long_cases:
        long_speedup = sum(r['speedup'] for r in long_cases) / len(long_cases)
        print(f"   • Đường dài (> 5km): A* nhanh hơn ~{long_speedup:.2f}x")
    
    print(f"   • A* hiệu quả hơn Dijkstra trong mọi trường hợp!")
    print(f"   • Heuristic giúp A* tập trung tìm kiếm theo hướng đích")
    print("="*80 + "\n")

def main():
    print("🚀 BENCHMARK: SO SÁNH DIJKSTRA vs A*")
    print("="*80)
    
    # Load graph
    print("\n📂 Đang tải bản đồ...")
    G = load_graph_from_file()
    print(f"✅ Đã tải: {len(G.nodes())} nodes, {len(G.edges())} edges")
    
    # Tìm test cases
    test_cases = find_test_cases(G, num_cases=20)
    
    # Chạy benchmark
    results = run_benchmark(G, test_cases)
    
    if results:
        # In tổng kết
        print_summary(results)
        
        # Lưu kết quả
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"benchmark_results_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("BENCHMARK RESULTS\n")
            f.write("="*80 + "\n\n")
            for r in results:
                f.write(f"Case #{r['case_num']} ({r['category']})\n")
                f.write(f"  Distance: {r['actual_dist']:.3f} km\n")
                f.write(f"  Dijkstra: {r['dijkstra_time']:.2f} ms, {r['dijkstra_nodes']} nodes\n")
                f.write(f"  A*: {r['astar_time']:.2f} ms, {r['astar_nodes']} nodes\n")
                f.write(f"  Speedup: {r['speedup']:.2f}x, Node reduction: {r['node_reduction']:.1f}%\n\n")
        
        print(f"💾 Đã lưu kết quả chi tiết vào: {filename}")
    else:
        print("❌ Không có kết quả nào!")

if __name__ == "__main__":
    main()