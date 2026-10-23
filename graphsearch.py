"""
graphsearch.py
==============
Tự cài đặt các thuật toán tìm đường trên đồ thị đường bộ (OSMnx MultiDiGraph).

Tất cả thuật toán trả về cùng một kiểu `Result` để so sánh công bằng:
    popped  : số node được lấy ra khỏi hàng đợi và mở rộng (= "nodes explored")
    relaxed : số cạnh được xét tới (chỉ tính cạnh trỏ tới node chưa đóng)
    pushed  : số lần đẩy vào hàng đợi
    cost    : chi phí THỰC của đường đi trả về (tính lại từ danh sách cạnh)
    search_cost : chi phí mà thuật toán "tự tin" báo cáo (dùng để kiểm tra chéo)

Thuật toán: bfs, dfs, dijkstra, bidijkstra, astar, wastar_<w>, greedy, alt, spfa
Trọng số  : "length" (mét) hoặc "time" (giây, suy ra từ tốc độ ước lượng theo loại đường)
"""
from __future__ import annotations

import heapq
import math
import random
import re
from collections import deque
from dataclasses import dataclass
from time import perf_counter

import numpy as np

INF = float("inf")
R_EARTH = 6_371_000.0  # nhỏ hơn bán kính OSMnx (6_371_009) -> heuristic luôn admissible

# Tốc độ giả định (km/h) theo loại đường – có thể sửa. Dùng khi OSM không có maxspeed.
HIGHWAY_SPEED_KPH = {
    "motorway": 60, "trunk": 50, "primary": 40, "secondary": 35, "tertiary": 30,
    "unclassified": 20, "residential": 20, "living_street": 10, "service": 10,
}
ARTERIAL = {"motorway", "trunk", "primary", "secondary"}  # nhóm "trục chính"


# --------------------------------------------------------------------------- #
# Đồ thị gọn
# --------------------------------------------------------------------------- #
def _first_word(x) -> str:
    m = re.search(r"[A-Za-z_]+", str(x))
    return m.group(0) if m else ""


def hw_class(d) -> str:
    return _first_word(d.get("highway", "")).replace("_link", "")


def edge_speed_kph(d, cap: float = 50.0) -> float:
    v = d.get("speed_kph")
    try:
        v = float(v) if v is not None else None
        if v is not None and math.isnan(v):
            v = None
    except (TypeError, ValueError):
        v = None
    if v is None:
        nums = re.findall(r"\d+(?:\.\d+)?", str(d.get("maxspeed", "")))
        v = float(nums[0]) if nums else None
    if v is None:
        v = HIGHWAY_SPEED_KPH.get(hw_class(d), 20.0)
    return max(5.0, min(float(v), cap))


class RoadGraph:
    """Đồ thị với node đánh số 0..n-1, danh sách kề riêng cho từng loại trọng số."""

    def __init__(self, G, speed_cap_kph: float = 50.0):
        self.G = G
        self.ids = list(G.nodes())
        self.idx = {u: i for i, u in enumerate(self.ids)}
        n = self.n = len(self.ids)

        lat = np.array([float(G.nodes[u]["y"]) for u in self.ids])
        lon = np.array([float(G.nodes[u]["x"]) for u in self.ids])
        self.lat_deg, self.lon_deg = lat, lon
        self.latr = np.radians(lat).tolist()
        self.lonr = np.radians(lon).tolist()
        self.coslat = np.cos(np.radians(lat)).tolist()

        best = {"length": {}, "time": {}}   # (u,v) -> trọng số nhỏ nhất trong các cạnh song song
        self.edge_hw, self.edge_name = {}, {}
        vmax = 0.0
        for u, v, d in G.edges(data=True):
            if u == v:
                continue
            a, b = self.idx[u], self.idx[v]
            L = float(d.get("length", 0.0) or 0.0)
            ms = edge_speed_kph(d, speed_cap_kph) / 3.6
            vmax = max(vmax, ms)
            T = L / ms
            key = (a, b)
            if key not in best["length"] or L < best["length"][key]:
                best["length"][key] = L
                self.edge_hw[key] = hw_class(d)
                self.edge_name[key] = re.sub(r"[\[\]']", "", str(d.get("name", "") or ""))
            if key not in best["time"] or T < best["time"][key]:
                best["time"][key] = T
        self.w = best
        self.vmax_ms = vmax
        self.adj = {k: [[] for _ in range(n)] for k in best}
        self.radj = {k: [[] for _ in range(n)] for k in best}
        for k, dct in best.items():
            for (a, b), w in dct.items():
                self.adj[k][a].append((b, w))
                self.radj[k][b].append((a, w))
        self.n_edges = len(best["length"])
        self._uadj = {}

    # ---- khoảng cách đường chim bay (Haversine), mét ----
    def hav(self, i: int, j: int) -> float:
        a = (math.sin((self.latr[j] - self.latr[i]) * 0.5) ** 2
             + self.coslat[i] * self.coslat[j] * math.sin((self.lonr[j] - self.lonr[i]) * 0.5) ** 2)
        return 2 * R_EARTH * math.asin(min(1.0, math.sqrt(a)))

    def hav_vec(self, a, b):
        la1, la2 = np.radians(self.lat_deg[a]), np.radians(self.lat_deg[b])
        dlon = np.radians(self.lon_deg[b] - self.lon_deg[a])
        h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(dlon / 2) ** 2
        return 2 * R_EARTH * np.arcsin(np.minimum(1.0, np.sqrt(h)))

    def hav_to_point(self, lat, lon):
        la1, la2 = np.radians(self.lat_deg), math.radians(lat)
        dlon = np.radians(lon - self.lon_deg)
        h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * math.cos(la2) * np.sin(dlon / 2) ** 2
        return 2 * R_EARTH * np.arcsin(np.minimum(1.0, np.sqrt(h)))

    def path_cost(self, path, weight="length") -> float:
        w = self.w[weight]
        return sum(w[(a, b)] for a, b in zip(path, path[1:]))   # KeyError nếu có cạnh không tồn tại

    def undirected(self, weight="length"):
        """Danh sách kề coi mọi đường là hai chiều (để đo ảnh hưởng của đường một chiều)."""
        if weight not in self._uadj:
            u = [dict() for _ in range(self.n)]
            for (a, b), w in self.w[weight].items():
                for x, y in ((a, b), (b, a)):
                    if y not in u[x] or w < u[x][y]:
                        u[x][y] = w
            self._uadj[weight] = [list(d.items()) for d in u]
        return self._uadj[weight]


@dataclass
class Result:
    algo: str
    weight: str
    found: bool
    path: list
    cost: float
    search_cost: float
    popped: int
    relaxed: int
    pushed: int
    time_ms: float
    explored: list | None = None


def _build(prev, s, t):
    path = [t]
    while path[-1] != s:
        path.append(prev[path[-1]])
    path.reverse()
    return path


def _finish(g, algo, weight, found, prev, s, t, search_cost, popped, relaxed, pushed, t0, order):
    elapsed = (perf_counter() - t0) * 1000.0
    if found:
        path = [s] if s == t else _build(prev, s, t)
        cost = g.path_cost(path, weight)
    else:
        path, cost, search_cost = [], INF, INF
    return Result(algo, weight, found, path, cost, search_cost, popped, relaxed, pushed, elapsed, order)


# --------------------------------------------------------------------------- #
# Tìm kiếm không có thông tin: BFS, DFS
# --------------------------------------------------------------------------- #
def bfs(g, s, t, weight="length", trace=False):
    """Ít cạnh nhất (bỏ qua trọng số) – baseline 'ngây thơ'."""
    t0 = perf_counter(); adj = g.adj[weight]
    prev = {s: None}; q = deque([s]); popped = relaxed = pushed = 0
    order = [] if trace else None; found = False
    while q:
        u = q.popleft(); popped += 1
        if trace: order.append(u)
        if u == t: found = True; break
        for v, _ in adj[u]:
            if v in prev: continue
            relaxed += 1; prev[v] = u; q.append(v); pushed += 1
    return _finish(g, "bfs", weight, found, prev, s, t, 0.0, popped, relaxed, pushed, t0, order)


def dfs(g, s, t, weight="length", trace=False):
    """DFS lặp (stack). Hoàn chỉnh nhưng KHÔNG tối ưu – thứ tự duyệt phụ thuộc thứ tự cạnh."""
    t0 = perf_counter(); adj = g.adj[weight]
    prev = {s: None}; stack = [s]; seen = set(); popped = relaxed = pushed = 0
    order = [] if trace else None; found = False
    while stack:
        u = stack.pop()
        if u in seen: continue
        seen.add(u); popped += 1
        if trace: order.append(u)
        if u == t: found = True; break
        for v, _ in adj[u]:
            if v in seen: continue
            relaxed += 1; prev[v] = u; stack.append(v); pushed += 1
    return _finish(g, "dfs", weight, found, prev, s, t, 0.0, popped, relaxed, pushed, t0, order)


# --------------------------------------------------------------------------- #
# Dijkstra (= Uniform-Cost Search)
# --------------------------------------------------------------------------- #
def dijkstra(g, s, t, weight="length", blocked=None, trace=False):
    t0 = perf_counter(); adj = g.adj[weight]
    dist = {s: 0.0}; prev = {}; done = set(); pq = [(0.0, s)]
    popped = relaxed = pushed = 0; order = [] if trace else None; found = False
    while pq:
        d, u = heapq.heappop(pq)
        if u in done: continue          # bỏ qua bản ghi "cũ" (lazy deletion)
        done.add(u); popped += 1
        if trace: order.append(u)
        if u == t: found = True; break
        for v, w in adj[u]:
            if v in done: continue
            if blocked is not None and (u, v) in blocked: continue
            relaxed += 1
            nd = d + w
            if nd < dist.get(v, INF):
                dist[v] = nd; prev[v] = u; heapq.heappush(pq, (nd, v)); pushed += 1
    return _finish(g, "dijkstra", weight, found, prev, s, t, dist.get(t, INF), popped, relaxed, pushed, t0, order)


def dijkstra_dist(adj, s, t):
    """Chỉ trả khoảng cách (dùng với danh sách kề tuỳ ý, vd. đồ thị vô hướng)."""
    dist = {s: 0.0}; done = set(); pq = [(0.0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in done: continue
        if u == t: return d
        done.add(u)
        for v, w in adj[u]:
            if v not in done and d + w < dist.get(v, INF):
                dist[v] = d + w; heapq.heappush(pq, (d + w, v))
    return INF


def sssp(adj, s, n):
    """Dijkstra toàn đồ thị từ s -> list khoảng cách."""
    dist = [INF] * n; dist[s] = 0.0; pq = [(0.0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]: continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd; heapq.heappush(pq, (nd, v))
    return dist


# --------------------------------------------------------------------------- #
# Heuristic search: A*, Weighted A*, Greedy, ALT
# --------------------------------------------------------------------------- #
def make_haversine_h(g, t, weight):
    """h(n) = Haversine(n, t)  [length]   hoặc   Haversine / v_max  [time]  (đều admissible)."""
    k = 2 * R_EARTH * (1.0 if weight == "length" else 1.0 / g.vmax_ms)
    lt, ln, ct = g.latr[t], g.lonr[t], g.coslat[t]
    latr, lonr, coslat = g.latr, g.lonr, g.coslat
    sin, asin, sqrt = math.sin, math.asin, math.sqrt

    def h(i):
        a = sin((lt - latr[i]) * 0.5) ** 2 + coslat[i] * ct * sin((ln - lonr[i]) * 0.5) ** 2
        return k * asin(sqrt(a if a < 1.0 else 1.0))
    return h


def astar(g, s, t, weight="length", h=None, hw=1.0, greedy=False, blocked=None, trace=False, name="astar"):
    """
    f = g + hw*h        (hw=1: A*,  hw>1: Weighted A*)
    greedy=True: f = h  (Greedy Best-First Search)
    Dùng closed-set -> cần heuristic nhất quán (consistent); Haversine & ALT đều thoả.
    """
    t0 = perf_counter(); adj = g.adj[weight]
    if h is None:
        h = make_haversine_h(g, t, weight)
    gs = {s: 0.0}; prev = {}; closed = set()
    pq = [(h(s) if greedy else hw * h(s), s)]
    popped = relaxed = pushed = 0; order = [] if trace else None; found = False
    while pq:
        _, u = heapq.heappop(pq)
        if u in closed: continue
        closed.add(u); popped += 1
        if trace: order.append(u)
        if u == t: found = True; break
        gu = gs[u]
        for v, w in adj[u]:
            if v in closed: continue
            if blocked is not None and (u, v) in blocked: continue
            relaxed += 1
            ng = gu + w
            if ng < gs.get(v, INF):
                gs[v] = ng; prev[v] = u
                heapq.heappush(pq, (h(v) if greedy else ng + hw * h(v), v)); pushed += 1
    return _finish(g, name, weight, found, prev, s, t, gs.get(t, INF), popped, relaxed, pushed, t0, order)


class Landmarks:
    """ALT (A*, Landmarks, Triangle inequality): tiền xử lý k landmark -> heuristic chặt hơn Haversine."""

    def __init__(self, g, weight="length", k=8, seed=0):
        t0 = perf_counter(); n = g.n
        rng = random.Random(seed)
        d0 = sssp(g.adj[weight], rng.randrange(n), n)
        first = max(range(n), key=lambda i: d0[i] if d0[i] < INF else -1.0)   # điểm xa nhất
        self.nodes, self.dist_from, self.dist_to = [], [], []
        mind = np.full(n, INF)
        cur = first
        for _ in range(k):
            df = sssp(g.adj[weight], cur, n); dt = sssp(g.radj[weight], cur, n)
            self.nodes.append(cur); self.dist_from.append(df); self.dist_to.append(dt)
            mind = np.minimum(mind, np.array(df))
            cur = int(np.argmax(np.where(np.isinf(mind), -1.0, mind)))   # farthest-point
        self.prep_ms = (perf_counter() - t0) * 1000.0

    def heuristic(self, t):
        items = [(df, dt, df[t], dt[t]) for df, dt in zip(self.dist_from, self.dist_to)]

        def h(i):
            best = 0.0
            for df, dt, dft, dtt in items:
                a = dft - df[i]      # d(L,t) - d(L,i) <= d(i,t)
                b = dt[i] - dtt      # d(i,L) - d(t,L) <= d(i,t)
                if a > best: best = a
                if b > best: best = b
            return best
        return h


# --------------------------------------------------------------------------- #
# Bidirectional Dijkstra
# --------------------------------------------------------------------------- #
def bidijkstra(g, s, t, weight="length", blocked=None, trace=False):
    t0 = perf_counter()
    if s == t:
        return _finish(g, "bidijkstra", weight, True, {}, s, t, 0.0, 0, 0, 0, t0, [] if trace else None)
    af, ab = g.adj[weight], g.radj[weight]
    df, db = {s: 0.0}, {t: 0.0}; pf, pb = {}, {}
    qf, qb = [(0.0, s)], [(0.0, t)]; cf, cb = set(), set()
    mu, meet = INF, None
    popped = relaxed = pushed = 0; order = [] if trace else None
    while qf and qb:
        if qf[0][0] + qb[0][0] >= mu: break
        if qf[0][0] <= qb[0][0]:
            d, u = heapq.heappop(qf)
            if u in cf: continue
            cf.add(u); popped += 1
            if trace: order.append(u)
            for v, w in af[u]:
                if v in cf: continue
                if blocked is not None and (u, v) in blocked: continue
                relaxed += 1; nd = d + w
                if nd < df.get(v, INF):
                    df[v] = nd; pf[v] = u; heapq.heappush(qf, (nd, v)); pushed += 1
                    if v in db and nd + db[v] < mu: mu = nd + db[v]; meet = v
        else:
            d, u = heapq.heappop(qb)
            if u in cb: continue
            cb.add(u); popped += 1
            if trace: order.append(u)
            for v, w in ab[u]:          # v -> u là cạnh thật
                if v in cb: continue
                if blocked is not None and (v, u) in blocked: continue
                relaxed += 1; nd = d + w
                if nd < db.get(v, INF):
                    db[v] = nd; pb[v] = u; heapq.heappush(qb, (nd, v)); pushed += 1
                    if v in df and nd + df[v] < mu: mu = nd + df[v]; meet = v
    elapsed = (perf_counter() - t0) * 1000.0
    if meet is None:
        return Result("bidijkstra", weight, False, [], INF, INF, popped, relaxed, pushed, elapsed, order)
    p1 = [meet]
    while p1[-1] != s: p1.append(pf[p1[-1]])
    p1.reverse(); x = meet
    while x != t:
        x = pb[x]; p1.append(x)
    return Result("bidijkstra", weight, True, p1, g.path_cost(p1, weight), mu, popped, relaxed, pushed, elapsed, order)


# --------------------------------------------------------------------------- #
# Bellman-Ford (hàng đợi / SPFA) – không dừng sớm được
# --------------------------------------------------------------------------- #
def spfa(g, s, t, weight="length", trace=False):
    t0 = perf_counter(); adj = g.adj[weight]; n = g.n
    dist = [INF] * n; dist[s] = 0.0; prev = [-1] * n; inq = [False] * n
    q = deque([s]); inq[s] = True; popped = relaxed = pushed = 0
    while q:
        u = q.popleft(); inq[u] = False; popped += 1; du = dist[u]
        for v, w in adj[u]:
            relaxed += 1; nd = du + w
            if nd < dist[v]:
                dist[v] = nd; prev[v] = u
                if not inq[v]: q.append(v); inq[v] = True; pushed += 1
    return _finish(g, "spfa", weight, dist[t] < INF, prev, s, t, dist[t], popped, relaxed, pushed, t0, None)


# --------------------------------------------------------------------------- #
# Router: một cổng chạy mọi thuật toán
# --------------------------------------------------------------------------- #
ALGOS = ["bfs", "dfs", "dijkstra", "bidijkstra", "astar", "wastar_1.5", "wastar_2.0", "greedy", "alt", "spfa"]
OPTIMAL = ["dijkstra", "bidijkstra", "astar", "alt", "spfa"]


class Router:
    def __init__(self, g: RoadGraph, n_landmarks: int = 8, seed: int = 0):
        self.g, self.k, self.seed, self._lm = g, n_landmarks, seed, {}

    def landmarks(self, weight) -> Landmarks:
        if weight not in self._lm:
            self._lm[weight] = Landmarks(self.g, weight, self.k, self.seed)
        return self._lm[weight]

    def run(self, algo, s, t, weight="length", blocked=None, trace=False) -> Result:
        g = self.g
        if algo == "bfs": return bfs(g, s, t, weight, trace)
        if algo == "dfs": return dfs(g, s, t, weight, trace)
        if algo == "dijkstra": return dijkstra(g, s, t, weight, blocked, trace)
        if algo == "bidijkstra": return bidijkstra(g, s, t, weight, blocked, trace)
        if algo == "astar": return astar(g, s, t, weight, blocked=blocked, trace=trace)
        if algo.startswith("wastar_"):
            return astar(g, s, t, weight, hw=float(algo.split("_")[1]), blocked=blocked, trace=trace, name=algo)
        if algo == "greedy": return astar(g, s, t, weight, greedy=True, blocked=blocked, trace=trace, name="greedy")
        if algo == "alt":
            h = self.landmarks(weight).heuristic(t)
            return astar(g, s, t, weight, h=h, blocked=blocked, trace=trace, name="alt")
        if algo == "spfa": return spfa(g, s, t, weight, trace)
        raise ValueError(algo)