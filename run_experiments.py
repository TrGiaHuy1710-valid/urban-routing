#!/usr/bin/env python3
"""
run_experiments.py
==================
Bộ thực nghiệm cho đề tài "Tìm đường đi ngắn nhất trên bản đồ giao thông bằng các thuật toán
tìm kiếm trên đồ thị".  Mỗi thí nghiệm ghi CSV + biểu đồ PNG vào thư mục --out và in bảng tóm tắt.

Ví dụ:
    python run_experiments.py --graph data/hadong_drive.graphml --exp all
    python run_experiments.py --graph data/hadong_drive.graphml --exp benchmark frontier
    python run_experiments.py --synthetic --exp all --per-bin 5          # thử nhanh, không cần dữ liệu

Thí nghiệm:
    graphstats  Thống kê cấu trúc đồ thị (bậc, đường một chiều, loại đường, SCC...)
    validate    Kiểm tra tính đúng đắn (so với networkx) + độ chặt của heuristic
    benchmark   So sánh toàn bộ thuật toán trên các cặp điểm phân tầng theo khoảng cách
    frontier    Vẽ vùng tìm kiếm của từng thuật toán (length vs time)
    oneway      Tác động của đường một chiều (có hướng vs vô hướng)
    fastest     Đường ngắn nhất (mét) khác đường nhanh nhất (giây) đến mức nào
    vuln        Độ dễ tổn thương: chặn các cạnh bị dùng nhiều nhất -> đường vòng tăng bao nhiêu
    scale       Thời gian chạy theo kích thước đồ thị (độ phức tạp thực nghiệm)
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import random
import statistics
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection

from graphsearch import (ALGOS, ARTERIAL, OPTIMAL, RoadGraph, Router, dijkstra_dist,
                         make_haversine_h)

BINS = [(0, 0.5, "0-0.5km"), (0.5, 1.5, "0.5-1.5km"), (1.5, 3, "1.5-3km"), (3, 6, "3-6km"), (6, 1e9, ">6km")]
BIN_ORDER = [b[2] for b in BINS]
PLOT_ALGOS = ["dijkstra", "bidijkstra", "astar", "alt", "greedy", "wastar_2.0"]


# --------------------------------------------------------------------------- #
# Nạp dữ liệu
# --------------------------------------------------------------------------- #
def load_graph(path):
    import networkx as nx
    try:
        import osmnx as ox
        G = ox.load_graphml(path)
    except ImportError:                                  # không có osmnx -> đọc bằng networkx
        G = nx.read_graphml(path)
        for _, d in G.nodes(data=True):
            d["x"], d["y"] = float(d["x"]), float(d["y"])
        for _, _, d in G.edges(data=True):
            d["length"] = float(d.get("length", 0) or 0)
    n0, m0 = G.number_of_nodes(), G.number_of_edges()
    comp = max(nx.strongly_connected_components(G), key=len)   # chỉ giữ thành phần liên thông mạnh
    G = G.subgraph(comp).copy()
    return G, {"nodes_raw": n0, "edges_raw": m0, "nodes_scc": G.number_of_nodes(), "edges_scc": G.number_of_edges()}


def make_synthetic(side=60, seed=0):
    """Lưới đường giả lập (có sông chắn + 3 cầu, trục chính, đường một chiều) để thử script."""
    import networkx as nx
    rng = random.Random(seed)
    G = nx.MultiDiGraph()
    lat0, lon0, step = 20.96, 105.77, 0.0009
    for i in range(side):
        for j in range(side):
            G.add_node(i * side + j, y=lat0 + i * step + rng.uniform(-2e-4, 2e-4),
                       x=lon0 + j * step + rng.uniform(-2e-4, 2e-4), street_count=4)

    def hav(a, b):
        la1, la2 = math.radians(G.nodes[a]["y"]), math.radians(G.nodes[b]["y"])
        dl = math.radians(G.nodes[b]["x"] - G.nodes[a]["x"])
        h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dl / 2) ** 2
        return 2 * 6371009 * math.asin(math.sqrt(h))

    def add(a, b, hw, name):
        G.add_edge(a, b, length=hav(a, b) * (1 + rng.random() * 0.15), highway=hw, name=name)

    for i in range(side):
        for j in range(side):
            u = i * side + j
            for di, dj in ((0, 1), (1, 0)):
                ii, jj = i + di, j + dj
                if ii >= side or jj >= side: continue
                if dj == 1 and j == side // 2 - 1 and i not in (5, side // 2, side - 6): continue  # sông
                v = ii * side + jj
                main = (i % 10 == 0 and dj == 1) or (j % 10 == 0 and di == 1)
                hw = "primary" if main else rng.choice(["residential", "residential", "tertiary", "service"])
                name = f"Duong {'A' if dj else 'B'}{i if dj else j}" if main else ""
                oneway = (not main) and rng.random() < 0.25
                if oneway and rng.random() < 0.5: u2, v2 = v, u
                else: u2, v2 = u, v
                add(u2, v2, hw, name)
                if not oneway: add(v2, u2, hw, name)
    return G


# --------------------------------------------------------------------------- #
# Tiện ích
# --------------------------------------------------------------------------- #
def sample_pairs(g, per_bin, seed=42, bins=BINS):
    rng = np.random.default_rng(seed)
    m = 400_000
    a, b = rng.integers(0, g.n, m), rng.integers(0, g.n, m)
    d = g.hav_vec(a, b) / 1000.0
    out = []
    for lo, hi, name in bins:
        idx = np.where((d >= lo) & (d < hi) & (a != b))[0][:per_bin]
        out += [(int(a[i]), int(b[i]), float(d[i]), name) for i in idx]
    return out


def timed(router, algo, s, t, weight, repeats, **kw):
    times, res = [], None
    for _ in range(repeats):
        gc.disable()
        res = router.run(algo, s, t, weight, **kw)
        gc.enable()
        times.append(res.time_ms)
    res.time_ms = statistics.median(times)
    return res


def save(df, out, name):
    p = os.path.join(out, name)
    df.to_csv(p, index=False)
    print(f"   -> {p}")


def fig_path(out, name):
    return os.path.join(out, name)


def show(title, df):
    print(f"\n=== {title} ===")
    print(df.to_string())


def edge_set(path):
    return set(zip(path, path[1:]))


# --------------------------------------------------------------------------- #
# 0. Thống kê đồ thị
# --------------------------------------------------------------------------- #
def exp_graphstats(g, info, out, **_):
    L = np.array(list(g.w["length"].values()))
    nbr = [len({v for v, _ in g.adj["length"][i]} | {v for v, _ in g.radj["length"][i]}) for i in range(g.n)]
    deg = Counter(min(x, 5) for x in nbr)
    no_rev = sum(1 for (a, b) in g.w["length"] if (b, a) not in g.w["length"])
    hw_len = Counter()
    for k, w in g.w["length"].items():
        hw_len[g.edge_hw.get(k, "?")] += w
    tot = sum(hw_len.values())
    stats = {
        **info,
        "nodes": g.n, "edges": g.n_edges, "avg_out_degree": round(g.n_edges / g.n, 2),
        "degree_dist(1..5+)": {str(k): deg.get(k, 0) for k in range(1, 6)},
        "dead_end_pct": round(100 * deg.get(1, 0) / g.n, 1),
        "intersection_pct(deg>=3)": round(100 * sum(v for k, v in deg.items() if k >= 3) / g.n, 1),
        "oneway_edge_pct": round(100 * no_rev / g.n_edges, 1),
        "edge_len_m": {q: round(float(np.quantile(L, p)), 1) for q, p in
                       (("p10", .1), ("median", .5), ("mean", None), ("p90", .9), ("max", 1.0)) if p is not None}
                      | {"mean": round(float(L.mean()), 1)},
        "total_km": round(float(L.sum()) / 1000, 1),
        "length_share_by_highway_pct": {k: round(100 * v / tot, 1) for k, v in hw_len.most_common()},
        "vmax_assumed_kph": round(g.vmax_ms * 3.6, 1),
    }
    print("\n=== GRAPH STATS ===")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    with open(os.path.join(out, "graph_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    plt.figure(figsize=(9, 3.2))
    plt.subplot(1, 2, 1); plt.hist(np.clip(L, 0, 300), bins=60, color="#4C78A8")
    plt.xlabel("Chiều dài cạnh (m, cắt ở 300)"); plt.ylabel("Số cạnh")
    plt.subplot(1, 2, 2); ks = sorted(deg); plt.bar([str(k) if k < 5 else "5+" for k in ks], [deg[k] for k in ks], color="#F58518")
    plt.xlabel("Số node lân cận"); plt.tight_layout(); plt.savefig(fig_path(out, "fig_graph_stats.png"), dpi=150); plt.close()


# --------------------------------------------------------------------------- #
# 1. Validate
# --------------------------------------------------------------------------- #
def exp_validate(g, router, args, out, **_):
    import networkx as nx
    pairs = sample_pairs(g, max(4, args.per_bin // 2), seed=args.seed + 1)
    rows, bad = [], 0
    for pid, (s, t, sk, bn) in enumerate(pairs):
        ref = nx.dijkstra_path_length(g.G, g.ids[s], g.ids[t], weight="length")
        for weight in ("length", "time"):
            res = {a: router.run(a, s, t, weight) for a in OPTIMAL}
            opt = min(r.cost for r in res.values())
            for a, r in res.items():
                ok_opt = math.isclose(r.cost, opt, rel_tol=1e-9, abs_tol=1e-6)
                ok_self = math.isclose(r.cost, r.search_cost, rel_tol=1e-9, abs_tol=1e-6)
                ok_nx = True if weight == "time" else math.isclose(r.cost, ref, rel_tol=1e-9, abs_tol=1e-6)
                if not (ok_opt and ok_self and ok_nx):
                    bad += 1
                    rows.append(dict(pair=pid, weight=weight, algo=a, cost=r.cost, search_cost=r.search_cost, nx_ref=ref))
            # độ chặt heuristic tại điểm xuất phát: h(s)/d*(s,t)  (<=1 mới admissible)
            d_opt = res["dijkstra"].cost
            if d_opt > 0:
                hs = make_haversine_h(g, t, weight)(s) / d_opt
                ha = router.landmarks(weight).heuristic(t)(s) / d_opt
                rows.append(dict(pair=pid, weight=weight, algo="_tightness", h_haversine=hs, h_alt=ha, bin=bn))
    df = pd.DataFrame(rows)
    tight = df[df.algo == "_tightness"] if len(df) else df
    total = len(pairs) * 2 * len(OPTIMAL)
    print(f"\n=== VALIDATE: {total - bad}/{total} kiểm tra đạt (chi phí trùng nhau, khớp networkx, đường đi hợp lệ) ===")
    if bad:
        print(df[df.algo != "_tightness"].head(20).to_string())
    if len(tight):
        t2 = tight.groupby("weight")[["h_haversine", "h_alt"]].agg(["mean", "max"]).round(3)
        show("Độ chặt heuristic h(s)/d*(s,t)  (càng gần 1 càng tốt, >1 là vi phạm admissible)", t2)
        save(tight.drop(columns=["algo", "cost", "search_cost", "nx_ref"], errors="ignore"), out, "validate_heuristic_tightness.csv")


# --------------------------------------------------------------------------- #
# 2. Benchmark
# --------------------------------------------------------------------------- #
def exp_benchmark(g, router, args, out, **_):
    pairs = sample_pairs(g, args.per_bin, seed=args.seed)
    print(f"\n[benchmark] {len(pairs)} cặp điểm, {args.repeats} lần lặp/thuật toán, 2 loại trọng số")
    rows = []
    for pid, (s, t, sk, bn) in enumerate(pairs):
        short_km = router.run("dijkstra", s, t, "length").cost / 1000.0
        for weight in ("length", "time"):
            res = {}
            for algo in ALGOS:
                if algo == "spfa" and pid % max(1, len(pairs) // max(1, args.spfa_pairs)) != 0:
                    continue
                res[algo] = timed(router, algo, s, t, weight, args.repeats)
            opt = res["dijkstra"].cost
            for algo, r in res.items():
                rows.append(dict(pair=pid, bin=bn, straight_km=sk, short_km=short_km, circuity=short_km / sk,
                                 weight=weight, algo=algo, time_ms=r.time_ms, popped=r.popped, relaxed=r.relaxed,
                                 pushed=r.pushed, hops=len(r.path) - 1, cost=r.cost, opt_cost=opt,
                                 subopt_pct=100 * (r.cost / opt - 1) if opt > 0 else 0.0))
        if (pid + 1) % 20 == 0: print(f"   {pid + 1}/{len(pairs)}")
    df = pd.DataFrame(rows)
    df["bin"] = pd.Categorical(df["bin"], BIN_ORDER, ordered=True)
    save(df, out, "benchmark_raw.csv")
    summarize(df, g.n, out)


def summarize(df, n, out):
    order = {a: i for i, a in enumerate(ALGOS)}
    A = df.groupby(["weight", "algo"], observed=True).agg(
        n=("pair", "count"), time_ms_median=("time_ms", "median"), time_ms_p90=("time_ms", lambda x: x.quantile(.9)),
        popped_median=("popped", "median"), relaxed_median=("relaxed", "median"),
        optimal_pct=("subopt_pct", lambda x: 100 * (x < 1e-6).mean()),
        subopt_mean_pct=("subopt_pct", "mean"), subopt_max_pct=("subopt_pct", "max")).round(2)
    A = A.reset_index(); A["o"] = A.algo.map(order); A = A.sort_values(["weight", "o"]).drop(columns="o").set_index(["weight", "algo"])
    show("TỔNG QUAN THEO THUẬT TOÁN", A); A.to_csv(os.path.join(out, "summary_by_algo.csv"))

    base = df[df.algo == "dijkstra"][["pair", "weight", "time_ms", "popped"]].rename(columns={"time_ms": "t0", "popped": "p0"})
    m = df.merge(base, on=["pair", "weight"])
    m["speedup"] = m.t0 / m.time_ms
    m["node_ratio"] = m.popped / m.p0
    m["us_per_node"] = m.time_ms * 1000 / m.popped.clip(lower=1)
    m["frac_graph"] = m.popped / n

    for w in ("length", "time"):
        sub = m[(m.weight == w) & (m.algo.isin(OPTIMAL + ["greedy", "wastar_1.5", "wastar_2.0"])) & (m.algo != "spfa")]
        for col, label in (("node_ratio", "node mở rộng / Dijkstra  (nhỏ hơn = tốt)"), ("speedup", "tăng tốc về thời gian so với Dijkstra (>1 = nhanh hơn)")):
            pv = sub[sub.algo != "dijkstra"].pivot_table(index="algo", columns="bin", values=col, aggfunc="median", observed=True).round(2)
            show(f"[{w}] median {label} theo nhóm khoảng cách", pv); pv.to_csv(os.path.join(out, f"pivot_{col}_{w}.csv"))
        us = m[(m.weight == w) & m.algo.isin(["dijkstra", "astar", "alt", "bidijkstra"])].groupby("algo").us_per_node.median().round(2)
        show(f"[{w}] chi phí trung bình mỗi node mở rộng (µs)", us.to_frame())
        d_frac = m[(m.weight == w) & (m.algo == "dijkstra")].groupby("bin", observed=True).frac_graph.median().round(3)
        show(f"[{w}] Dijkstra đã duyệt bao nhiêu phần của toàn đồ thị (median)", d_frac.to_frame())
        win = m[(m.weight == w) & (m.algo == "astar")]
        print(f"[{w}] A* nhanh hơn Dijkstra ở {100 * (win.speedup > 1).mean():.0f}% cặp điểm; "
              f"median speedup {win.speedup.median():.2f}; median node_ratio {win.node_ratio.median():.2f}")
        try:
            from scipy.stats import wilcoxon
            stat = wilcoxon(win.t0, win.time_ms)
            print(f"[{w}] Wilcoxon signed-rank (Dijkstra vs A* time): p = {stat.pvalue:.3g}")
        except Exception:
            pass
        cor = win[["node_ratio", "circuity", "straight_km"]].corr(method="spearman").node_ratio.round(2)
        print(f"[{w}] Spearman(node_ratio A*, circuity) = {cor['circuity']},  (node_ratio, straight_km) = {cor['straight_km']}")

    # ---- Hình 1: số node mở rộng theo độ dài đường (log-log) ----
    fig, ax = plt.subplots(figsize=(6.4, 4.6)); slopes = {}
    L = df[df.weight == "length"]
    dmask = L[(L.algo == "dijkstra") & (L.popped < 0.6 * n)].pair
    for algo, c in (("dijkstra", "#E45756"), ("bidijkstra", "#B279A2"), ("astar", "#4C78A8"), ("alt", "#54A24B")):
        d = L[L.algo == algo]
        ax.scatter(d.short_km, d.popped, s=10, alpha=.5, c=c, label=algo)
        dd = d[d.pair.isin(dmask)]
        if len(dd) > 5:
            k, b = np.polyfit(np.log(dd.short_km), np.log(dd.popped.clip(lower=1)), 1); slopes[algo] = round(float(k), 2)
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("Chiều dài đường ngắn nhất (km)"); ax.set_ylabel("Số node mở rộng")
    ax.axhline(n, ls="--", c="gray", lw=.8); ax.text(ax.get_xlim()[0], n * 1.05, "toàn bộ đồ thị", fontsize=8, color="gray")
    ax.set_title("Không gian tìm kiếm theo độ dài tuyến (log-log)"); ax.legend(); fig.tight_layout()
    fig.savefig(fig_path(out, "fig_nodes_vs_distance.png"), dpi=150); plt.close(fig)
    print(f"\nĐộ dốc log-log (popped ~ km^k, chỉ tính cặp Dijkstra chưa chạm biên đồ thị): {slopes}   (k≈2 nghĩa là không gian tìm kiếm ~ diện tích hình tròn)")

    # ---- Hình 2: thời gian theo nhóm khoảng cách ----
    fig, axs = plt.subplots(1, 2, figsize=(11, 4), sharey=False)
    for ax, w in zip(axs, ("length", "time")):
        for algo in PLOT_ALGOS:
            d = df[(df.weight == w) & (df.algo == algo)].groupby("bin", observed=True).time_ms
            med, q1, q3 = d.median(), d.quantile(.25), d.quantile(.75)
            x = [BIN_ORDER.index(b) for b in med.index]
            ax.plot(x, med.values, marker="o", label=algo); ax.fill_between(x, q1.values, q3.values, alpha=.12)
        ax.set_xticks(range(len(BIN_ORDER))); ax.set_xticklabels(BIN_ORDER, fontsize=8)
        ax.set_title(f"Thời gian chạy (median, vùng IQR) – trọng số: {w}"); ax.set_ylabel("ms"); ax.grid(alpha=.3)
    axs[0].legend(fontsize=8); fig.tight_layout(); fig.savefig(fig_path(out, "fig_time_by_bin.png"), dpi=150); plt.close(fig)

    # ---- Hình 3: hiệu quả của A* phụ thuộc độ vòng của đường (circuity) ----
    fig, ax = plt.subplots(figsize=(6, 4.4))
    for w, c in (("length", "#4C78A8"), ("time", "#F58518")):
        d = m[(m.weight == w) & (m.algo == "astar")]
        ax.scatter(d.circuity, d.node_ratio, s=14, alpha=.6, c=c, label=f"A* ({w})")
    ax.set_xlabel("Circuity = đường thực / đường chim bay"); ax.set_ylabel("Node A* / node Dijkstra")
    ax.set_title("Heuristic càng chặt (circuity thấp) thì A* càng tiết kiệm"); ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(fig_path(out, "fig_astar_vs_circuity.png"), dpi=150); plt.close(fig)

    # ---- Hình 4: đánh đổi chất lượng–tốc độ (Weighted A*, Greedy) ----
    fig, ax = plt.subplots(figsize=(6, 4.4))
    for algo in ("dijkstra", "astar", "wastar_1.5", "wastar_2.0", "greedy", "alt", "bidijkstra", "dfs", "bfs"):
        d = m[(m.weight == "length") & (m.algo == algo)]
        ax.scatter(d.node_ratio.median(), d.subopt_pct.mean(), s=70); ax.annotate(algo, (d.node_ratio.median(), d.subopt_pct.mean()), fontsize=8, xytext=(4, 4), textcoords="offset points")
    ax.set_xscale("log"); ax.set_xlabel("Không gian tìm kiếm so với Dijkstra (median, log)"); ax.set_ylabel("Đường đi dài hơn tối ưu (% trung bình)")
    ax.set_yscale("symlog", linthresh=1); ax.set_title("Đánh đổi: tốc độ tìm kiếm vs chất lượng đường"); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(fig_path(out, "fig_tradeoff.png"), dpi=150); plt.close(fig)
    with open(os.path.join(out, "loglog_slopes.json"), "w") as f: json.dump(slopes, f)


# --------------------------------------------------------------------------- #
# 3. Frontier
# --------------------------------------------------------------------------- #
def exp_frontier(g, router, args, out, **_):
    cand = sample_pairs(g, 1, seed=args.seed + 7, bins=[b for b in BINS if b[2] in ("3-6km", ">6km", "1.5-3km")])
    s, t, sk, bn = cand[-1] if cand else sample_pairs(g, 1, seed=1)[0]
    algos = ["dijkstra", "bidijkstra", "astar", "alt", "greedy"]
    fig, axs = plt.subplots(2, len(algos), figsize=(3.3 * len(algos), 6.6))
    for r, weight in enumerate(("length", "time")):
        for c, algo in enumerate(algos):
            ax = axs[r][c]; res = router.run(algo, s, t, weight, trace=True)
            ax.scatter(g.lon_deg, g.lat_deg, s=.6, c="#DDDDDD")
            ex = res.explored or []
            ax.scatter(g.lon_deg[ex], g.lat_deg[ex], s=1.5, c=np.arange(len(ex)), cmap="viridis")
            p = res.path; ax.plot(g.lon_deg[p], g.lat_deg[p], c="red", lw=1.4)
            ax.scatter(*[[g.lon_deg[s]], [g.lat_deg[s]]], c="lime", s=40, edgecolor="k", zorder=5)
            ax.scatter(*[[g.lon_deg[t]], [g.lat_deg[t]]], c="red", marker="*", s=90, edgecolor="k", zorder=5)
            ax.set_title(f"{algo} [{weight}]\nmở rộng {res.popped} node ({100 * res.popped / g.n:.0f}%)", fontsize=9)
            ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect(1 / math.cos(math.radians(g.lat_deg.mean())))
    fig.suptitle(f"Vùng tìm kiếm (màu = thứ tự mở rộng) – tuyến {sk:.1f} km chim bay", y=1.0)
    fig.tight_layout(); p = fig_path(out, "fig_frontier.png"); fig.savefig(p, dpi=150); plt.close(fig)
    print(f"\n[frontier] -> {p}")


# --------------------------------------------------------------------------- #
# 4. One-way
# --------------------------------------------------------------------------- #
def exp_oneway(g, args, out, **_):
    pairs = sample_pairs(g, args.per_bin * 2, seed=args.seed + 3, bins=BINS[1:])
    ad, au = g.adj["length"], g.undirected("length")
    rows = []
    for s, t, sk, bn in pairs:
        d_dir, d_rev, d_und = dijkstra_dist(ad, s, t), dijkstra_dist(ad, t, s), dijkstra_dist(au, s, t)
        rows.append(dict(bin=bn, straight_km=sk, d_directed_m=d_dir, d_undirected_m=d_und, d_reverse_m=d_rev,
                         oneway_penalty=d_dir / d_und, asymmetry=abs(d_dir - d_rev) / min(d_dir, d_rev)))
    df = pd.DataFrame(rows); df["bin"] = pd.Categorical(df["bin"], BIN_ORDER, ordered=True)
    save(df, out, "oneway.csv")
    q = df.oneway_penalty.quantile([.5, .9, .99]).round(3).to_dict()
    show("Phạt do đường một chiều (d_có_hướng / d_vô_hướng) theo nhóm", df.groupby("bin", observed=True)[["oneway_penalty", "asymmetry"]].agg(["mean", "median", "max"]).round(3))
    print(f"[oneway] {100 * (df.oneway_penalty > 1.0001).mean():.0f}% cặp bị đi vòng vì đường một chiều; phân vị {q}; "
          f"chiều đi ≠ chiều về trung bình {100 * df.asymmetry.mean():.1f}%")
    plt.figure(figsize=(6, 3.6)); plt.hist((df.oneway_penalty - 1) * 100, bins=40, color="#72B7B2")
    plt.xlabel("Quãng đường tăng thêm do đường một chiều (%)"); plt.ylabel("Số cặp"); plt.tight_layout()
    plt.savefig(fig_path(out, "fig_oneway.png"), dpi=150); plt.close()


# --------------------------------------------------------------------------- #
# 5. Shortest vs fastest
# --------------------------------------------------------------------------- #
def exp_fastest(g, router, args, out, **_):
    pairs = sample_pairs(g, args.per_bin, seed=args.seed + 5, bins=BINS[1:])
    hw = g.edge_hw
    def arterial_share(path):
        tot = sum(g.w["length"][e] for e in zip(path, path[1:]))
        art = sum(g.w["length"][e] for e in zip(path, path[1:]) if hw.get(e) in ARTERIAL)
        return art / tot if tot else 0.0
    rows = []
    for s, t, sk, bn in pairs:
        a = router.run("dijkstra", s, t, "length"); b = router.run("dijkstra", s, t, "time")
        ea, eb = edge_set(a.path), edge_set(b.path)
        rows.append(dict(bin=bn, straight_km=sk, short_km=a.cost / 1000, fast_km=g.path_cost(b.path, "length") / 1000,
                         short_min=g.path_cost(a.path, "time") / 60, fast_min=b.cost / 60,
                         jaccard=len(ea & eb) / len(ea | eb) if ea | eb else 1.0,
                         arterial_short=arterial_share(a.path), arterial_fast=arterial_share(b.path)))
    df = pd.DataFrame(rows)
    df["extra_km_pct"] = 100 * (df.fast_km / df.short_km - 1); df["time_saving_pct"] = 100 * (1 - df.fast_min / df.short_min)
    df["different"] = df.jaccard < 0.999; df["bin"] = pd.Categorical(df["bin"], BIN_ORDER, ordered=True)
    save(df, out, "shortest_vs_fastest.csv")
    gb = df.groupby("bin", observed=True).agg(n=("jaccard", "count"), different_pct=("different", lambda x: 100 * x.mean()),
                                              jaccard=("jaccard", "mean"), extra_km_pct=("extra_km_pct", "mean"),
                                              time_saving_pct=("time_saving_pct", "mean"),
                                              arterial_short=("arterial_short", "mean"), arterial_fast=("arterial_fast", "mean")).round(3)
    show("Đường ngắn nhất (mét) vs nhanh nhất (giây – tốc độ ước lượng)", gb)
    print("[fastest] LƯU Ý: tốc độ theo loại đường là giả định (HIGHWAY_SPEED_KPH) – kết luận về HƯỚNG xu hướng đáng tin hơn con số tuyệt đối.")


# --------------------------------------------------------------------------- #
# 6. Vulnerability
# --------------------------------------------------------------------------- #
def exp_vuln(g, router, args, out, **_):
    bins = [(1, 3, "1-3km"), (3, 6, "3-6km"), (6, 1e9, ">6km")]
    pairs = sample_pairs(g, max(5, args.vuln_pairs // 3), seed=args.seed + 11, bins=bins)
    base = [router.run("dijkstra", s, t, "length") for s, t, _, _ in pairs]
    usage = Counter()
    for r in base:
        for a, b in {(min(x, y), max(x, y)) for x, y in zip(r.path, r.path[1:])}:
            usage[(a, b)] += 1
    top = usage.most_common(60)
    rows = []
    for (a, b), c in top[:15]:
        k = (a, b) if (a, b) in g.edge_name else (b, a)
        rows.append(dict(u=g.ids[a], v=g.ids[b], lat=g.lat_deg[a], lon=g.lon_deg[a], used_by_pct=100 * c / len(pairs),
                         highway=g.edge_hw.get(k, "?"), name=g.edge_name.get(k, "") or "(không tên)"))
    topdf = pd.DataFrame(rows).round(3); show("Cạnh bị dùng nhiều nhất trong các tuyến mẫu", topdf); save(topdf, out, "vuln_top_edges.csv")
    tot_e = len(usage); k1 = max(1, tot_e // 100)
    print(f"[vuln] {len(pairs)} tuyến mẫu dùng tổng cộng {tot_e} cạnh phân biệt; "
          f"top-1 cạnh nằm trên {100 * top[0][1] / len(pairs):.0f}% tuyến; top 1% cạnh phủ "
          f"{100 * sum(c for _, c in usage.most_common(k1)) / sum(usage.values()):.0f}% lượt dùng cạnh")
    res = []
    for k in (1, 3, 5, 10, 20):
        blocked = set()
        for (a, b), _ in top[:k]: blocked |= {(a, b), (b, a)}
        det, disc, aff = [], 0, 0
        for (s, t, _, _), r0 in zip(pairs, base):
            if not (edge_set(r0.path) & blocked): continue
            aff += 1; r1 = router.run("dijkstra", s, t, "length", blocked=blocked)
            if not r1.found: disc += 1
            else: det.append(r1.cost / r0.cost - 1)
        res.append(dict(blocked_top_k=k, affected_pct=100 * aff / len(pairs), disconnected_pct=100 * disc / len(pairs),
                        mean_detour_pct_of_affected=100 * np.mean(det) if det else 0.0,
                        p90_detour_pct=100 * np.quantile(det, .9) if det else 0.0,
                        max_detour_pct=100 * max(det) if det else 0.0))
    rdf = pd.DataFrame(res).round(2); show("Chặn top-k cạnh (cả hai chiều): đường vòng tăng bao nhiêu", rdf); save(rdf, out, "vuln_blocking.csv")
    # bản đồ cường độ sử dụng cạnh
    segs, cols = [], []
    for (a, b), w in g.w["length"].items():
        segs.append([(g.lon_deg[a], g.lat_deg[a]), (g.lon_deg[b], g.lat_deg[b])])
        cols.append(usage.get((min(a, b), max(a, b)), 0))
    cols = np.array(cols); fig, ax = plt.subplots(figsize=(7.5, 7.5))
    ax.add_collection(LineCollection([s for s, c in zip(segs, cols) if c == 0], colors="#DDDDDD", linewidths=.4))
    used = [(s, c) for s, c in zip(segs, cols) if c > 0]
    if used:
        lc = LineCollection([s for s, _ in used], array=np.array([c for _, c in used]), cmap="inferno_r",
                            linewidths=0.6 + 2.4 * np.array([c for _, c in used]) / max(c for _, c in used))
        ax.add_collection(lc); fig.colorbar(lc, ax=ax, shrink=.6, label="Số tuyến mẫu đi qua")
    ax.autoscale(); ax.set_aspect(1 / math.cos(math.radians(g.lat_deg.mean()))); ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Cường độ sử dụng cạnh trong các tuyến ngắn nhất (proxy 'betweenness')")
    fig.tight_layout(); fig.savefig(fig_path(out, "fig_edge_usage.png"), dpi=150); plt.close(fig)


# --------------------------------------------------------------------------- #
# 7. Scalability
# --------------------------------------------------------------------------- #
def exp_scale(g, args, out, **_):
    import networkx as nx
    clat, clon = g.lat_deg.mean(), g.lon_deg.mean(); dist = g.hav_to_point(clat, clon)
    rows, seen = [], set()
    for rad in (1, 2, 3, 5, 8, None):
        nodes = np.where(dist <= rad * 1000)[0] if rad else np.arange(g.n)
        if len(nodes) < 300 or len(nodes) in seen: continue
        seen.add(len(nodes))
        sub = g.G.subgraph([g.ids[i] for i in nodes])
        sub = sub.subgraph(max(nx.strongly_connected_components(sub), key=len)).copy()
        gs = RoadGraph(sub); rt = Router(gs, args.landmarks, args.seed)
        rng = random.Random(args.seed); pairs = [(rng.randrange(gs.n), rng.randrange(gs.n)) for _ in range(40)]
        pairs = [(s, t) for s, t in pairs if s != t and gs.hav(s, t) > 300]
        for algo in ("dijkstra", "bidijkstra", "astar", "alt"):
            rs = [timed(rt, algo, s, t, "length", 3) for s, t in pairs]
            rows.append(dict(V=gs.n, E=gs.n_edges, algo=algo, time_ms=statistics.median(r.time_ms for r in rs),
                             popped=statistics.median(r.popped for r in rs),
                             alt_prep_ms=rt.landmarks("length").prep_ms if algo == "alt" else np.nan))
    df = pd.DataFrame(rows); save(df, out, "scalability.csv")
    show("Thời gian theo kích thước đồ thị (median/40 cặp ngẫu nhiên)", df.pivot_table(index="V", columns="algo", values="time_ms").round(2))
    fig, ax = plt.subplots(figsize=(5.6, 4.2)); slopes = {}
    for algo in ("dijkstra", "bidijkstra", "astar", "alt"):
        d = df[df.algo == algo]
        ax.plot(d.V, d.time_ms, marker="o", label=algo)
        if len(d) >= 3: slopes[algo] = round(float(np.polyfit(np.log(d.V), np.log(d.time_ms), 1)[0]), 2)
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("Số node V"); ax.set_ylabel("ms (median)"); ax.legend(); ax.grid(alpha=.3)
    ax.set_title("Độ phức tạp thực nghiệm (log-log)"); fig.tight_layout(); fig.savefig(fig_path(out, "fig_scalability.png"), dpi=150); plt.close(fig)
    print(f"[scale] Độ dốc log-log (time ~ V^k): {slopes}.  ALT tốn thêm tiền xử lý:")
    print(df[df.algo == 'alt'][['V', 'alt_prep_ms']].round(0).to_string(index=False))
    print("Đồ thị Hà Đông chỉ ~11k node nên dải V hẹp – nên thêm dữ liệu cả Hà Nội để thấy rõ tiệm cận.")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", default="data/hadong_drive.graphml")
    ap.add_argument("--out", default="results")
    ap.add_argument("--exp", nargs="+", default=["all"],
                    choices=["all", "graphstats", "validate", "benchmark", "frontier", "oneway", "fastest", "vuln", "scale"])
    ap.add_argument("--per-bin", type=int, default=30, help="số cặp điểm mỗi nhóm khoảng cách")
    ap.add_argument("--repeats", type=int, default=3, help="số lần lặp để lấy median thời gian")
    ap.add_argument("--landmarks", type=int, default=8)
    ap.add_argument("--spfa-pairs", type=int, default=12, help="SPFA/Bellman-Ford chậm nên chỉ chạy trên một tập con")
    ap.add_argument("--vuln-pairs", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--synthetic", action="store_true", help="dùng đồ thị lưới giả lập để thử script")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if args.synthetic:
        import networkx as nx
        G = make_synthetic(); comp = max(nx.strongly_connected_components(G), key=len); G = G.subgraph(comp).copy()
        info = {"source": "synthetic", "nodes_scc": G.number_of_nodes(), "edges_scc": G.number_of_edges()}
    else:
        G, info = load_graph(args.graph)
    g = RoadGraph(G); router = Router(g, args.landmarks, args.seed)
    print(f"Đồ thị: {g.n} node, {g.n_edges} cạnh (thành phần liên thông mạnh lớn nhất); {info}")
    pre = {w: router.landmarks(w).prep_ms for w in ("length", "time")}
    print(f"Tiền xử lý ALT ({args.landmarks} landmark): " + ", ".join(f"{w}={v:.0f} ms" for w, v in pre.items()))

    todo = ["graphstats", "validate", "benchmark", "frontier", "oneway", "fastest", "vuln", "scale"] if "all" in args.exp else args.exp
    for e in todo:
        print(f"\n########## {e} ##########")
        {"graphstats": lambda: exp_graphstats(g, info, args.out),
         "validate": lambda: exp_validate(g, router, args, args.out),
         "benchmark": lambda: exp_benchmark(g, router, args, args.out),
         "frontier": lambda: exp_frontier(g, router, args, args.out),
         "oneway": lambda: exp_oneway(g, args, args.out),
         "fastest": lambda: exp_fastest(g, router, args, args.out),
         "vuln": lambda: exp_vuln(g, router, args, args.out),
         "scale": lambda: exp_scale(g, args, args.out)}[e]()
    print(f"\nXong. Kết quả trong thư mục: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()