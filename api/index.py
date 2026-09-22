"""
NEXUS VPS PANEL - VERCEL EDITION (FIXED)
HTML Hosting + Shareable Links + User Management
Owner: PR4MOD_H4X
"""
import os
import json
import time
import secrets
import base64
from functools import wraps
from pathlib import Path
from flask import (
    Flask, request, redirect, url_for, session,
    render_template, jsonify, Response
)
from werkzeug.utils import secure_filename
import requests

# ============================================
#  INITIALIZATION
# ============================================
BASE_DIR = Path(__file__).parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"

OWNER_USER = "PRAMOD"
OWNER_PASS = "7722"

# Vercel KV (Upstash Redis) config
KV_URL = os.environ.get("KV_REST_API_URL", "")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")
USE_KV = bool(KV_URL and KV_TOKEN)

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR)
)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB Vercel limit

# ============================================
#  ✅ FILTERS (YE PEHLE MISSING THA - AB ADDED)
# ============================================
@app.template_filter('timestamp_to_date')
def timestamp_to_date(ts):
    if not ts:
        return "LIFETIME"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except:
        return "INVALID"

# ============================================
#  KV STORAGE (Upstash Redis REST)
# ============================================
def kv_get(key):
    if not USE_KV:
        return None
    try:
        r = requests.get(
            f"{KV_URL}/get/{key}",
            headers={"Authorization": f"Bearer {KV_TOKEN}"},
            timeout=5
        )
        data = r.json()
        if data.get("result"):
            return json.loads(base64.b64decode(data["result"]).decode())
        return None
    except Exception:
        return None

def kv_set(key, value):
    if not USE_KV:
        return False
    try:
        encoded = base64.b64encode(json.dumps(value).encode()).decode()
        requests.post(
            f"{KV_URL}/set/{key}",
            headers={"Authorization": f"Bearer {KV_TOKEN}"},
            data=encoded,
            timeout=5
        )
        return True
    except Exception:
        return False

# ============================================
#  IN-MEMORY FALLBACK (for local testing)
# ============================================
_MEM = {"users": {}, "files": {}}

def load_users():
    if USE_KV:
        return kv_get("nexus_users") or {}
    return _MEM["users"]

def save_users(users):
    if USE_KV:
        kv_set("nexus_users", users)
    else:
        _MEM["users"] = users

def load_files(username):
    if USE_KV:
        return kv_get(f"nexus_files_{username}") or {}
    return _MEM["files"].get(username, {})

def save_files(username, files):
    if USE_KV:
        kv_set(f"nexus_files_{username}", files)
    else:
        _MEM["files"][username] = files

# ============================================
#  AUTH DECORATORS
# ============================================
def is_owner():
    return session.get("role") == "owner"

def current_user():
    return session.get("username")

def require_owner(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_owner():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def require_user(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        username = current_user()
        if not username or session.get("role") != "user":
            return redirect(url_for("login"))
        users = load_users()
        if username not in users:
            session.clear()
            return redirect(url_for("login"))
        if users[username].get("expires_at") and time.time() > users[username]["expires_at"]:
            del users[username]
            save_users(users)
            session.clear()
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# ============================================
#  ROUTES
# ============================================
@app.route("/")
def home():
    if is_owner():
        return redirect(url_for("owner_dashboard"))
    if current_user():
        return redirect(url_for("user_dashboard"))
    return render_template("landing.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip().upper()
        password = request.form.get("password", "")

        if username == OWNER_USER and password == OWNER_PASS:
            session.clear()
            session["role"] = "owner"
            session["username"] = username
            return redirect(url_for("owner_dashboard"))

        users = load_users()
        if username in users and users[username]["password"] == password:
            if users[username].get("expires_at") and time.time() > users[username]["expires_at"]:
                error = "ACCOUNT EXPIRED"
            else:
                session.clear()
                session["role"] = "user"
                session["username"] = username
                return redirect(url_for("user_dashboard"))
        else:
            error = "INVALID CREDENTIALS"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/auto/<token>")
def auto_login(token):
    users = load_users()
    for username, info in users.items():
        if info.get("token") == token:
            if info.get("expires_at") and time.time() > info["expires_at"]:
                return "ACCOUNT EXPIRED", 403
            session.clear()
            session["role"] = "user"
            session["username"] = username
            return redirect(url_for("user_dashboard"))
    return "INVALID LINK", 404

# ============================================
#  OWNER ROUTES
# ============================================
@app.route("/owner")
@require_owner
def owner_dashboard():
    users = load_users()
    now = time.time()
    changed = False
    for username in list(users.keys()):
        if users[username].get("expires_at") and now > users[username]["expires_at"]:
            del users[username]
            changed = True
    if changed:
        save_users(users)
    return render_template(
        "owner.html",
        users=users,
        now=now,
        base_url=request.host_url.rstrip("/"),
        time=time
    )

@app.route("/owner/create", methods=["POST"])
@require_owner
def owner_create():
    username = request.form.get("username", "").strip().upper()
    password = request.form.get("password", "").strip()
    try:
        days = float(request.form.get("days", "7"))
    except:
        days = 7

    if not username or not password or username == OWNER_USER:
        return redirect(url_for("owner_dashboard"))

    users = load_users()
    users[username] = {
        "password": password,
        "created_at": time.time(),
        "expires_at": time.time() + days * 86400 if days > 0 else 0,
        "token": secrets.token_urlsafe(16)
    }
    save_users(users)
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/delete/<username>", methods=["POST"])
@require_owner
def owner_delete(username):
    users = load_users()
    if username in users:
        del users[username]
        save_users(users)
        save_files(username, {})
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/extend/<username>", methods=["POST"])
@require_owner
def owner_extend(username):
    try:
        days = float(request.form.get("days", "7"))
    except:
        days = 7

    users = load_users()
    if username in users:
        base = max(users[username].get("expires_at") or time.time(), time.time())
        users[username]["expires_at"] = base + days * 86400
        save_users(users)
    return redirect(url_for("owner_dashboard"))

# ============================================
#  USER ROUTES
# ============================================
@app.route("/dashboard")
@require_user
def user_dashboard():
    username = current_user()
    users = load_users()
    info = users.get(username, {})
    files_data = load_files(username)

    html_files = [f for f in files_data.keys() if f.lower().endswith(('.html', '.htm'))]
    other_files = [f for f in files_data.keys() if f not in html_files]

    return render_template(
        "user.html",
        username=username,
        info=info,
        files=other_files,
        html_files=html_files,
        expires_at=info.get("expires_at", 0),
        now=time.time(),
        base_url=request.host_url.rstrip("/")
    )

@app.route("/upload", methods=["POST"])
@require_user
def upload():
    username = current_user()
    files_data = load_files(username)
    files = request.files.getlist("files")

    for f in files:
        if f and f.filename:
            name = secure_filename(f.filename)
            if name:
                content = f.read()
                if len(content) > 5 * 1024 * 1024:
                    continue
                files_data[name] = base64.b64encode(content).decode()

    save_files(username, files_data)
    return redirect(url_for("user_dashboard"))

@app.route("/file/delete/<name>", methods=["POST"])
@require_user
def file_delete(name):
    username = current_user()
    name = secure_filename(name)
    files_data = load_files(username)
    if name in files_data:
        del files_data[name]
        save_files(username, files_data)
    return redirect(url_for("user_dashboard"))

@app.route("/file/view/<name>")
@require_user
def file_view(name):
    username = current_user()
    name = secure_filename(name)
    files_data = load_files(username)
    if name in files_data:
        content = base64.b64decode(files_data[name])
        mime = "text/html" if name.endswith(('.html', '.htm')) else "text/plain"
        return Response(content, mimetype=mime)
    return "FILE NOT FOUND", 404

@app.route("/download/<name>")
@require_user
def download_file(name):
    username = current_user()
    name = secure_filename(name)
    files_data = load_files(username)
    if name in files_data:
        content = base64.b64decode(files_data[name])
        return Response(
            content,
            mimetype="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={name}"}
        )
    return "FILE NOT FOUND", 404

# ============================================
#  PUBLIC SHARE ROUTE
# ============================================
@app.route("/share/<username>/<path:filename>")
def share_file(username, filename):
    username = secure_filename(username)
    filename = secure_filename(filename)
    files_data = load_files(username)
    if filename in files_data:
        content = base64.b64decode(files_data[filename])
        mime = "text/html" if filename.endswith(('.html', '.htm')) else "text/plain"
        return Response(content, mimetype=mime)
    return "FILE NOT FOUND", 404

@app.route("/healthz")
def health():
    return jsonify({
        "status": "OK",
        "kv": USE_KV,
        "time": time.time()
    })

# ============================================
#  VERCEL HANDLER
# ============================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
