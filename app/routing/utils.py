import re
import requests
import osmnx as ox
from osmnx import distance as oxdist
from app.config import Config

PHOTON_URL = "https://photon.komoot.io/api/"
# "20.959, 105.77"    # hoặc "  21.0 ,105.8"
LATLON_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$")

#chuyển chuỗi "lat, lon" thành tuple (lat, lon)
def parse_latlon(text):
    m = LATLON_RE.match(text.strip())
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))

#chuyển địa chỉ thành tọa độ lat, lon
def geocode_any(s):
    latlon = parse_latlon(s)
    if latlon:
        return latlon
    try:
        lat, lon = ox.geocode(s)
        return lat, lon
    except (requests.exceptions.RequestException, ox._errors.InsufficientResponseError) as e:
        # Nominatim (openstreetmap.org) bị chặn/ngắt kết nối hoặc không tìm thấy -> dùng Photon thay thế
        print(f"⚠️ Nominatim lỗi ({e}), chuyển sang Photon...")
        return geocode_photon(s)

#geocode bằng Photon (komoot), ưu tiên kết quả gần khu vực mặc định
def geocode_photon(s):
    lat0, lon0 = Config.DEFAULT_CENTER
    r = requests.get(
        PHOTON_URL,
        params={"q": s, "limit": 1, "lat": lat0, "lon": lon0},
        headers={"User-Agent": "urban-routing-flask"},
        timeout=15,
    )
    r.raise_for_status()
    features = r.json().get("features", [])
    if not features:
        raise ValueError(f"Không tìm thấy địa chỉ: {s}")
    lon, lat = features[0]["geometry"]["coordinates"]
    return lat, lon
# Tìm node gần nhất trong đồ thị G với tọa độ lat, lon
def nearest_node(G, lat, lon):
    return oxdist.nearest_nodes(G, X=lon, Y=lat)
