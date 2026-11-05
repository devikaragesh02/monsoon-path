import os
import math
import sqlite3
from functools import wraps
from pathlib import Path

import requests
import networkx as nx
import osmnx as ox

try:
    import rasterio
    from pyproj import Transformer
except ImportError:
    rasterio = None
    Transformer = None
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from geopy.geocoders import Nominatim

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "monsoon_path.db"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-development-secret")
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "monsoon-admin")

# OSMnx v2 uses a tuple bbox: (north, south, east, west).
ox.settings.log_console = False
ox.settings.use_cache = True


def db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS flood_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                depth TEXT NOT NULL,
                description TEXT,
                photo TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)


init_db()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 6:
            flash("Enter all details. Password must contain at least 6 characters.", "error")
            return render_template("register.html")
        try:
            with db() as conn:
                conn.execute(
                    "INSERT INTO users(name,email,password_hash) VALUES(?,?,?)",
                    (name, email, generate_password_hash(password))
                )
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("An account with that email already exists.", "error")
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    with db() as conn:
        reports = conn.execute("""
            SELECT latitude, longitude, depth, description, photo, created_at
            FROM flood_reports WHERE status='approved'
        """).fetchall()
    return render_template("dashboard.html", reports=[dict(r) for r in reports])


@app.route("/report", methods=["POST"])
@login_required
def report():
    lat = request.form.get("latitude", type=float)
    lon = request.form.get("longitude", type=float)
    depth = request.form.get("depth", "Unknown")
    description = request.form.get("description", "").strip()
    photo = request.files.get("photo")
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        flash("Please capture or enter a valid GPS location.", "error")
        return redirect(url_for("dashboard"))

    filename = None
    if photo and photo.filename:
        if not allowed_file(photo.filename):
            flash("Upload a JPG, PNG or WEBP image.", "error")
            return redirect(url_for("dashboard"))
        filename = secure_filename(photo.filename)
        # Prefix with user id and a timestamp-like unique value to avoid collisions.
        filename = f"{session['user_id']}_{os.urandom(5).hex()}_{filename}"
        photo.save(UPLOAD_DIR / filename)

    with db() as conn:
        conn.execute("""
            INSERT INTO flood_reports(user_id,latitude,longitude,depth,description,photo,status)
            VALUES(?,?,?,?,?,?, 'pending')
        """, (session["user_id"], lat, lon, depth, description, filename))
    flash("Flood report submitted. It will affect routing after admin approval.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("is_admin"):
        if request.method == "POST" and request.form.get("admin_password") == ADMIN_PASSWORD:
            session["is_admin"] = True
        else:
            return render_template("admin_login.html")
    with db() as conn:
        reports = conn.execute("""
            SELECT r.*, u.name AS reporter FROM flood_reports r
            JOIN users u ON u.id=r.user_id ORDER BY r.created_at DESC
        """).fetchall()
    return render_template("admin.html", reports=reports)


@app.route("/admin/report/<int:report_id>/<action>", methods=["POST"])
def moderate_report(report_id, action):
    if not session.get("is_admin") or action not in {"approve", "reject"}:
        return redirect(url_for("admin"))
    status = "approved" if action == "approve" else "rejected"
    with db() as conn:
        conn.execute("UPDATE flood_reports SET status=? WHERE id=?", (status, report_id))
    flash(f"Report {status}.", "success")
    return redirect(url_for("admin"))


def geocode(place):
    geolocator = Nominatim(user_agent="monsoon_path_student_project")
    result = geolocator.geocode(place, timeout=15)
    if not result:
        raise ValueError(f"Could not find location: {place}")
    return float(result.latitude), float(result.longitude)


def get_rainfall(lat, lon, user_value):
    """Use the user's rainfall value when supplied; otherwise request current Open-Meteo data."""
    if user_value is not None:
        return max(0.0, min(float(user_value), 200.0)), "User supplied"
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lat, "longitude": lon, "current": "precipitation"},
            timeout=12
        )
        response.raise_for_status()
        value = float(response.json().get("current", {}).get("precipitation", 0) or 0)
        return value, "Open-Meteo current precipitation"
    except Exception:
        return 0.0, "Rainfall unavailable; using 0 mm/h"


def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))



def attach_dem_elevations(graph):
    """
    Attach elevations (metres) to OSMnx graph nodes from a local DEM GeoTIFF.
    Set DEM_PATH to a projected/georeferenced GeoTIFF path.
    The raster may use any CRS; node coordinates are transformed as needed.
    """
    dem_path = os.environ.get("DEM_PATH", "").strip()
    if not dem_path:
        return 0, "DEM not configured"
    if rasterio is None or Transformer is None:
        return 0, "Install rasterio and pyproj to read a DEM"
    if not Path(dem_path).is_file():
        return 0, f"DEM file not found: {dem_path}"

    attached = 0
    try:
        with rasterio.open(dem_path) as src:
            if src.crs is None:
                return 0, "DEM has no coordinate reference system"
            transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            node_ids = list(graph.nodes)
            xs = [graph.nodes[n]["x"] for n in node_ids]
            ys = [graph.nodes[n]["y"] for n in node_ids]
            raster_points = [transformer.transform(x, y) for x, y in zip(xs, ys)]
            samples = src.sample(raster_points, indexes=1, masked=True)
            for node_id, sample in zip(node_ids, samples):
                value = sample[0]
                if getattr(value, "mask", False):
                    continue
                try:
                    elevation = float(value)
                    if math.isfinite(elevation) and elevation > -500:
                        graph.nodes[node_id]["elevation"] = elevation
                        attached += 1
                except (TypeError, ValueError):
                    continue
        return attached, f"Local DEM: {attached}/{graph.number_of_nodes()} nodes have elevation"
    except Exception as exc:
        app.logger.exception("DEM loading failed")
        return 0, f"DEM read failed: {exc}"

def edge_risk(u, v, data, graph, reports, rainfall, min_elev, max_elev):
    """
    Demonstration risk heuristic, not a validated flood model:
    rainfall contributes up to 0.45; low relative elevation up to 0.30;
    an approved crowd report within 100 m contributes 0.45.
    """
    rain_score = min(rainfall / 50.0, 1.0) * 0.45
    elev_score = 0.0
    try:
        eu = float(graph.nodes[u].get("elevation"))
        ev = float(graph.nodes[v].get("elevation"))
        mean_elev = (eu + ev) / 2
        span = max(max_elev - min_elev, 1.0)
        low_factor = max(0.0, min(1.0, (max_elev - mean_elev) / span))
        elev_score = low_factor * 0.30
    except (TypeError, ValueError):
        pass  # No DEM elevations available: terrain contribution remains zero.

    midpoint_lat = (graph.nodes[u]["y"] + graph.nodes[v]["y"]) / 2
    midpoint_lon = (graph.nodes[u]["x"] + graph.nodes[v]["x"]) / 2
    report_score = 0.0
    for report in reports:
        if haversine_m(midpoint_lat, midpoint_lon, report["latitude"], report["longitude"]) <= 100:
            report_score = 0.45
            break
    score = min(1.0, rain_score + elev_score + report_score)
    level = "high" if score >= 0.67 else ("medium" if score >= 0.30 else "low")
    return score, level


@app.route("/api/route", methods=["POST"])
@login_required
def calculate_route():
    payload = request.get_json(silent=True) or {}
    start_text = (payload.get("start") or "").strip()
    end_text = (payload.get("end") or "").strip()
    rainfall_input = payload.get("rainfall")
    if not start_text or not end_text:
        return jsonify(error="Enter both a starting point and destination."), 400

    try:
        start = geocode(start_text)
        end = geocode(end_text)
        center_lat = (start[0] + end[0]) / 2
        center_lon = (start[1] + end[1]) / 2
        distance_between = haversine_m(start[0], start[1], end[0], end[1])
        if distance_between > 15000:
            return jsonify(error="For this demo, choose locations within 15 km of each other."), 400

        rainfall, rainfall_source = get_rainfall(center_lat, center_lon, rainfall_input)
        pad = max(0.008, distance_between / 111000 * 0.45)
        north = max(start[0], end[0]) + pad
        south = min(start[0], end[0]) - pad
        east = max(start[1], end[1]) + pad
        west = min(start[1], end[1]) - pad

        graph = ox.graph_from_bbox((north, south, east, west), network_type="walk", simplify=True)
        if graph.number_of_nodes() == 0:
            return jsonify(error="No walkable road network was found for this area."), 400

        dem_nodes, dem_status = attach_dem_elevations(graph)

        start_node = ox.distance.nearest_nodes(graph, X=start[1], Y=start[0])
        end_node = ox.distance.nearest_nodes(graph, X=end[1], Y=end[0])

        with db() as conn:
            report_rows = conn.execute("""
                SELECT latitude,longitude,depth,description FROM flood_reports
                WHERE status='approved'
            """).fetchall()
        reports = [dict(r) for r in report_rows]

        elevations = []
        for node in graph.nodes:
            value = graph.nodes[node].get("elevation")
            if value is not None:
                try:
                    elevations.append(float(value))
                except (TypeError, ValueError):
                    pass
        min_elev = min(elevations) if elevations else 0.0
        max_elev = max(elevations) if elevations else 1.0

        # Score each road edge and block high-risk edges from the safe-route search.
        edge_lookup = {}
        for u, v, key, data in graph.edges(keys=True, data=True):
            score, level = edge_risk(u, v, data, graph, reports, rainfall, min_elev, max_elev)
            data["risk_score"] = score
            data["risk_level"] = level
            length = float(data.get("length", 1.0))
            data["safe_weight"] = length * (1 + score * 4)
            edge_lookup[(u, v)] = data

        safe_graph = graph.copy()
        remove_edges = [
            (u, v, key) for u, v, key, data in safe_graph.edges(keys=True, data=True)
            if data.get("risk_level") == "high"
        ]
        safe_graph.remove_edges_from(remove_edges)

        try:
            path = nx.shortest_path(safe_graph, start_node, end_node, weight="safe_weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return jsonify(
                no_safe_route=True,
                error="No safe route is currently available. Please wait for conditions to improve or choose another destination.",
                rainfall=round(rainfall, 1),
                rainfall_source=rainfall_source
            ), 200

        coordinates = []
        segments = []
        total_distance = 0.0
        for index, node in enumerate(path):
            coordinates.append([graph.nodes[node]["y"], graph.nodes[node]["x"]])
            if index == len(path) - 1:
                continue
            next_node = path[index + 1]
            edge_data = graph.get_edge_data(node, next_node)
            chosen = min(edge_data.values(), key=lambda d: d.get("safe_weight", d.get("length", 1)))
            length = float(chosen.get("length", 0))
            total_distance += length
            segments.append({
                "from": [graph.nodes[node]["y"], graph.nodes[node]["x"]],
                "to": [graph.nodes[next_node]["y"], graph.nodes[next_node]["x"]],
                "risk": chosen.get("risk_level", "low"),
                "risk_score": round(float(chosen.get("risk_score", 0)), 2)
            })

        minutes = max(1, round((total_distance / 1000) / 4.5 * 60))
        avoided = sum(1 for r in reports if any(
            haversine_m(r["latitude"], r["longitude"], c[0], c[1]) < 120 for c in coordinates
        ))
        return jsonify(
            coordinates=coordinates,
            segments=segments,
            distance_km=round(total_distance / 1000, 2),
            walking_minutes=minutes,
            rainfall=round(rainfall, 1),
            rainfall_source=rainfall_source,
            dem_status=dem_status,
            dem_nodes_with_elevation=dem_nodes,
            avoided_flood_reports=avoided,
            message="Route calculated using the Monsoon Path demonstration risk model."
        )
    except Exception as exc:
        app.logger.exception("Route calculation failed")
        return jsonify(error=f"Could not calculate route: {str(exc)}. Check the place names and internet connection."), 400


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Only report photos are served from the upload directory.
    from flask import send_from_directory
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


if __name__ == "__main__":
    app.run(debug=True)
