"""
NEXUS VPS PANEL - ULTRA PREMIUM EDITION v3
PHP + HTML HOSTING PANEL
Owner: PR4MOD_H4X
"""
import os
import json
import time
import shutil
import threading
import secrets
import subprocess
from datetime import datetime
from pathlib import Path
from functools import wraps
from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, jsonify, send_from_directory, send_file
)
from werkzeug.utils import secure_filename

# ============================================
#  INITIALIZATION
# ============================================
APP_DIR = Path(__file__).parent.absolute()
DATA_DIR = APP_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
FILES_ROOT = APP_DIR / "user_files"

for d in [DATA_DIR, FILES_ROOT]:
    d.mkdir(exist_ok=True)

OWNER_USER = "PRAMOD"
OWNER_PASS = "9111"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024

# ============================================
#  FILTERS
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
#  STORAGE FUNCTIONS
# ============================================
_lock = threading.Lock()

def load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(users):
    with _lock:
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, indent=2)

def user_dir(username):
    d = FILES_ROOT / username
    d.mkdir(parents=True, exist_ok=True)
    return d

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
#  PHP RUNNER (via PHP CLI)
# ============================================
PHP_PROCS = {}

def check_php():
    try:
        subprocess.run(["php", "-v"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False

PHP_AVAILABLE = check_php()

def start_php(username, filename):
    if not PHP_AVAILABLE:
        return False, "PHP NOT INSTALLED ON SERVER"
    stop_php(username)
    udir = user_dir(username)
    fpath = udir / filename
    if not fpath.exists():
        return False, "FILE NOT FOUND"
    
    port = 8000 + (abs(hash(username)) % 1000)
    try:
        proc = subprocess.Popen(
            ["php", "-S", f"0.0.0.0:{port}", "-t", str(udir)],
            cwd=str(udir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1
        )
    except FileNotFoundError:
        return False, "PHP RUNTIME NOT FOUND"
    
    from collections import deque
    logs = deque(maxlen=2000)
    logs.append(f"[PHP] SERVER STARTED ON PORT {port}")
    PHP_PROCS[username] = {"proc": proc, "logs": logs, "file": filename, "port": port}
    
    def reader():
        try:
            for line in iter(proc.stdout.readline, b""):
                try:
                    txt = line.decode("utf-8", errors="replace").rstrip()
                except:
                    txt = str(line)
                logs.append(f"[{time.strftime('%H:%M:%S')}] {txt}")
        except Exception as e:
            logs.append(f"[ERROR] {e}")
        finally:
            logs.append(f"[EXIT] PHP SERVER STOPPED")
    
    threading.Thread(target=reader, daemon=True).start()
    return True, f"PHP RUNNING ON PORT {port}"

def stop_php(username):
    info = PHP_PROCS.get(username)
    if not info:
        return False
    proc = info["proc"]
    if proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        except:
            pass
        info["logs"].append("[STOP] PHP SERVER TERMINATED")
    return True

def is_php_running(username):
    info = PHP_PROCS.get(username)
    return bool(info and info["proc"].poll() is None)

def get_php_logs(username):
    info = PHP_PROCS.get(username)
    return list(info["logs"]) if info else []

def get_php_port(username):
    info = PHP_PROCS.get(username)
    return info["port"] if info else None

# ============================================
#  ROUTES
# ============================================
@app.route("/")
def home():
    if is_owner():
        return redirect(url_for("owner_dashboard"))
    if current_user():
        return redirect(url_for("user_dashboard"))
    return render_template_string(HTML_LANDING)

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
    
    return render_template_string(HTML_LOGIN, error=error)

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

@app.route("/download/<filename>")
@require_user
def download_file(filename):
    username = current_user()
    filename = secure_filename(filename)
    udir = user_dir(username)
    fpath = udir / filename
    if fpath.exists() and fpath.is_file():
        return send_file(fpath, as_attachment=True, download_name=filename)
    return "FILE NOT FOUND", 404

# ============================================
#  PUBLIC SHARE ROUTE (SECURE HTML VIEWER)
# ============================================
@app.route("/share/<username>/<path:filename>")
def share_file(username, filename):
    username = secure_filename(username)
    filename = secure_filename(filename)
    fpath = FILES_ROOT / username / filename
    if not fpath.exists() or not fpath.is_file():
        return "FILE NOT FOUND", 404
    
    # HTML files -> secure sandboxed viewer (source hidden)
    if filename.lower().endswith(('.html', '.htm')):
        return render_template_string(
            HTML_SECURE_VIEWER,
            file_url=url_for('share_raw', username=username, filename=filename),
            filename=filename
        )
    # Non-HTML files -> direct serve
    return send_from_directory(FILES_ROOT / username, filename)


@app.route("/share-raw/<username>/<path:filename>")
def share_raw(username, filename):
    """Raw file delivery — only used inside secure iframe."""
    username = secure_filename(username)
    filename = secure_filename(filename)
    fpath = FILES_ROOT / username / filename
    if fpath.exists() and fpath.is_file():
        resp = send_from_directory(FILES_ROOT / username, filename)
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        return resp
    return "FILE NOT FOUND", 404

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
            stop_php(username)
            changed = True
    if changed:
        save_users(users)
    
    return render_template_string(
        HTML_OWNER,
        users=users,
        now=now,
        base_url=request.host_url.rstrip("/"),
        time=time,
        php_available=PHP_AVAILABLE
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
    user_dir(username)
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/delete/<username>", methods=["POST"])
@require_owner
def owner_delete(username):
    users = load_users()
    if username in users:
        stop_php(username)
        del users[username]
        save_users(users)
        shutil.rmtree(FILES_ROOT / username, ignore_errors=True)
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
    udir = user_dir(username)
    files = sorted([f.name for f in udir.iterdir() if f.is_file()])
    html_files = [f for f in files if f.lower().endswith(('.html', '.htm'))]
    php_files = [f for f in files if f.lower().endswith('.php')]
    other_files = [f for f in files if f not in html_files and f not in php_files]
    
    return render_template_string(
        HTML_USER,
        username=username,
        info=info,
        files=other_files,
        html_files=html_files,
        php_files=php_files,
        php_running=is_php_running(username),
        php_file=PHP_PROCS.get(username, {}).get("file") if is_php_running(username) else None,
        php_port=get_php_port(username) if is_php_running(username) else None,
        php_available=PHP_AVAILABLE,
        expires_at=info.get("expires_at", 0),
        now=time.time(),
        base_url=request.host_url.rstrip("/")
    )

@app.route("/upload", methods=["POST"])
@require_user
def upload():
    username = current_user()
    udir = user_dir(username)
    files = request.files.getlist("files")
    
    for f in files:
        if f and f.filename:
            name = secure_filename(f.filename)
            if name:
                f.save(udir / name)
    
    return redirect(url_for("user_dashboard"))

@app.route("/file/delete/<name>", methods=["POST"])
@require_user
def file_delete(name):
    username = current_user()
    name = secure_filename(name)
    p = user_dir(username) / name
    if p.exists() and p.is_file():
        p.unlink()
    return redirect(url_for("user_dashboard"))

@app.route("/file/view/<name>")
@require_user
def file_view(name):
    username = current_user()
    name = secure_filename(name)
    fpath = user_dir(username) / name
    if not fpath.exists() or not fpath.is_file():
        return "FILE NOT FOUND", 404
    
    # HTML files -> secure sandboxed viewer
    if name.lower().endswith(('.html', '.htm')):
        return render_template_string(
            HTML_SECURE_VIEWER,
            file_url=url_for('file_raw', name=name),
            filename=name
        )
    return send_from_directory(user_dir(username), name, as_attachment=False)


@app.route("/file-raw/<name>")
@require_user
def file_raw(name):
    """Raw file delivery for logged-in user (used only inside iframe)."""
    username = current_user()
    name = secure_filename(name)
    fpath = user_dir(username) / name
    if fpath.exists() and fpath.is_file():
        resp = send_from_directory(user_dir(username), name, as_attachment=False)
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        return resp
    return "FILE NOT FOUND", 404

@app.route("/php/start", methods=["POST"])
@require_user
def php_start():
    username = current_user()
    filename = secure_filename(request.form.get("file", ""))
    ok, msg = start_php(username, filename)
    return jsonify({"ok": ok, "msg": msg})

@app.route("/php/stop", methods=["POST"])
@require_user
def php_stop():
    username = current_user()
    stop_php(username)
    return jsonify({"ok": True})

@app.route("/php/restart", methods=["POST"])
@require_user
def php_restart():
    username = current_user()
    info = PHP_PROCS.get(username)
    filename = info["file"] if info else secure_filename(request.form.get("file", ""))
    if not filename:
        return jsonify({"ok": False, "msg": "NO FILE"})
    stop_php(username)
    time.sleep(0.3)
    ok, msg = start_php(username, filename)
    return jsonify({"ok": ok, "msg": msg})

@app.route("/php/delete", methods=["POST"])
@require_user
def php_delete():
    username = current_user()
    stop_php(username)
    PHP_PROCS.pop(username, None)
    return jsonify({"ok": True})

@app.route("/logs")
@require_user
def logs_api():
    username = current_user()
    return jsonify({
        "running": is_php_running(username),
        "file": PHP_PROCS.get(username, {}).get("file"),
        "port": get_php_port(username),
        "logs": get_php_logs(username)
    })

# ============================================
#  HEALTH CHECK
# ============================================
@app.route("/healthz")
def health():
    return "OK"

@app.route("/health")
def health_check():
    return jsonify({
        "success": True,
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }), 200

# ============================================
#  HTML TEMPLATES - EL MESSIRI PREMIUM THEME
# ============================================

HTML_SECURE_VIEWER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive,nosnippet">
<title>NEXUS</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden;background:#000}
iframe{width:100vw;height:100vh;border:none;display:block;position:fixed;inset:0}
.blocker{position:fixed;inset:0;background:#000;display:none;align-items:center;justify-content:center;flex-direction:column;gap:14px;z-index:9999;text-align:center;padding:20px;font-family:monospace;color:#F15BB5}
.blocker h1{font-size:14px;letter-spacing:4px}
.blocker p{font-size:10px;color:#666;letter-spacing:3px}
</style>
</head>
<body>
<iframe id="viewer" src="{{ file_url }}" sandbox="allow-scripts allow-forms allow-modals allow-popups"></iframe>
<div class="blocker" id="blocker">
<h1>ACCESS DENIED</h1>
<p>CLOSE DEVTOOLS TO CONTINUE</p>
</div>

<script>
// Disable right-click
document.addEventListener('contextmenu',function(e){e.preventDefault();return false});
// Disable common shortcuts
document.addEventListener('keydown',function(e){
  var k=(e.key||'').toUpperCase();
  if(k==='F12'){e.preventDefault();return false}
  if(e.ctrlKey&&e.shiftKey&&['I','J','C','K'].indexOf(k)>-1){e.preventDefault();return false}
  if(e.ctrlKey&&['U','S','P'].indexOf(k)>-1){e.preventDefault();return false}
  if(e.metaKey&&e.altKey&&['I','J','C','U'].indexOf(k)>-1){e.preventDefault();return false}
});
// Disable selection & drag
document.addEventListener('selectstart',function(e){e.preventDefault()});
document.addEventListener('dragstart',function(e){e.preventDefault()});

// DevTools detection
var blocker=document.getElementById('blocker');
var lastState=false;
setInterval(function(){
  var wDiff=window.outerWidth-window.innerWidth;
  var hDiff=window.outerHeight-window.innerHeight;
  var open=(wDiff>160||hDiff>160);
  if(open&&!lastState){
    blocker.style.display='flex';
    lastState=true;
  } else if(!open&&lastState){
    blocker.style.display='none';
    lastState=false;
  }
},700);
</script>
</body>
</html>"""

HTML_LANDING = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS VPS — ULTRA PREMIUM</title>
<link href="https://fonts.googleapis.com/css2?family=El+Messiri:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --c1:#00F5D4;--c2:#00BBF9;--c3:#9B5DE5;--c4:#F15BB5;
  --bg:#050810;--card:rgba(10,18,30,0.75);
  --brd:rgba(0,245,212,0.15);--txt:#E8F4F8;--mt:rgba(232,244,248,0.45);
}
body{font-family:'El Messiri',sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;overflow-x:hidden;text-transform:uppercase;letter-spacing:1.5px;font-weight:600}
canvas#bg{position:fixed;inset:0;z-index:0;opacity:0.5;pointer-events:none}
.mesh{position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 60% 50% at 15% 10%,rgba(0,245,212,0.12),transparent 60%),
    radial-gradient(ellipse 55% 45% at 85% 20%,rgba(155,93,229,0.12),transparent 60%),
    radial-gradient(ellipse 50% 40% at 50% 100%,rgba(241,91,181,0.1),transparent 60%);
}
.glass-nav{position:sticky;top:0;z-index:50;backdrop-filter:blur(30px);background:rgba(5,8,16,0.7);border-bottom:1px solid var(--brd);padding:1rem 2rem;display:flex;align-items:center;justify-content:center}
.brand{display:flex;align-items:center;gap:14px}
.brand-icon{width:48px;height:48px;border-radius:14px;background:linear-gradient(135deg,var(--c1),var(--c3));display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;color:#050810;box-shadow:0 0 40px rgba(0,245,212,0.35)}
.brand-text{font-size:26px;font-weight:700;background:linear-gradient(135deg,var(--c1),var(--c2),var(--c4));background-size:300% 300%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:gradient 5s ease infinite;letter-spacing:5px}
.wrap{position:relative;z-index:1;max-width:1200px;margin:0 auto;padding:0 24px}
.hero{min-height:85vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:40px 20px}
.eyebrow{display:inline-flex;align-items:center;gap:10px;padding:10px 28px;background:rgba(0,245,212,0.06);border:1px solid rgba(0,245,212,0.2);border-radius:50px;margin-bottom:34px}
.eyebrow .dot{width:8px;height:8px;border-radius:50%;background:var(--c1);animation:pulse 2s infinite;box-shadow:0 0 12px var(--c1)}
.eyebrow span{font-size:11px;font-weight:700;letter-spacing:5px;color:var(--c1)}
h1{font-size:clamp(44px,9vw,90px);font-weight:700;line-height:1;letter-spacing:-2px;margin-bottom:20px}
h1 .highlight{background:linear-gradient(135deg,var(--c1),var(--c2),var(--c4),var(--c3));background-size:300% 300%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:gradient 4s ease infinite}
.sub{font-size:15px;color:var(--mt);max-width:580px;margin:0 auto 36px;line-height:1.9;font-weight:500;letter-spacing:3px}
.btn-main{padding:18px 48px;border-radius:14px;background:linear-gradient(135deg,var(--c1),var(--c2));color:#050810;text-decoration:none;font-weight:700;font-size:14px;letter-spacing:3px;transition:0.4s;box-shadow:0 8px 40px rgba(0,245,212,0.3);display:inline-flex;align-items:center;gap:10px}
.btn-main:hover{transform:translateY(-4px) scale(1.05);box-shadow:0 16px 60px rgba(0,245,212,0.5);color:#050810}
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:18px;width:100%;max-width:1000px;margin-top:40px}
.feature{background:var(--card);border:1px solid var(--brd);border-radius:18px;padding:28px 20px;text-align:center;backdrop-filter:blur(20px);transition:0.4s;position:relative;overflow:hidden}
.feature::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(0,245,212,0.05),transparent);opacity:0;transition:0.4s}
.feature:hover{border-color:var(--c1);transform:translateY(-6px);box-shadow:0 20px 50px rgba(0,245,212,0.1)}
.feature:hover::before{opacity:1}
.feature i{font-size:34px;background:linear-gradient(135deg,var(--c1),var(--c3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:12px;position:relative}
.feature h3{font-size:14px;font-weight:700;letter-spacing:3px;margin-bottom:6px;position:relative}
.feature p{font-size:11px;color:var(--mt);letter-spacing:2px;position:relative}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
@keyframes gradient{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
@media(max-width:768px){.glass-nav{padding:1rem}.wrap{padding:0 16px}h1{font-size:clamp(32px,8vw,54px)}.features{grid-template-columns:1fr 1fr}}
@media(max-width:480px){.features{grid-template-columns:1fr}}
</style>
</head>
<body>
<canvas id="bg"></canvas>
<div class="mesh"></div>
<nav class="glass-nav">
<div class="brand"><div class="brand-icon">NX</div><span class="brand-text">NEXUS</span></div>
</nav>
<div class="wrap">
<section class="hero">
<div class="eyebrow"><div class="dot"></div><span>PHP &amp; HTML HOSTING PLATFORM</span></div>
<h1>HOST &amp; SHARE<br><span class="highlight">YOUR WEB APPS</span></h1>
<p class="sub">UPLOAD PHP &amp; HTML FILES — GET INSTANT SHAREABLE LINKS &amp; LIVE PHP SERVERS</p>
<a href="/login" class="btn-main"><i class="fas fa-arrow-right"></i> LAUNCH PANEL</a>
<div class="features">
<div class="feature"><i class="fas fa-link"></i><h3>SHAREABLE LINKS</h3><p>INSTANT HTML HOSTING</p></div>
<div class="feature"><i class="fas fa-code"></i><h3>PHP RUNTIME</h3><p>LIVE PHP SERVERS</p></div>
<div class="feature"><i class="fas fa-upload"></i><h3>200MB UPLOAD</h3><p>LARGE FILES SUPPORTED</p></div>
<div class="feature"><i class="fas fa-bolt"></i><h3>INSTANT DEPLOY</h3><p>UNDER 1 SECOND</p></div>
</div>
</section>
</div>
<script>
const c=document.getElementById('bg'),ctx=c.getContext('2d');
let W,H,p=[];
function resize(){W=c.width=innerWidth;H=c.height=innerHeight}
class P{constructor(){this.reset()}reset(){this.x=Math.random()*W;this.y=Math.random()*H;this.vx=(Math.random()-.5)*0.3;this.vy=(Math.random()-.5)*0.3;this.r=Math.random()*1.6+0.4;this.a=Math.random()*0.3+0.08;const cols=['0,245,212','0,187,249','155,93,229','241,91,181'];this.col=cols[Math.floor(Math.random()*cols.length)]}update(){this.x+=this.vx;this.y+=this.vy;if(this.x<0||this.x>W||this.y<0||this.y>H)this.reset()}draw(){ctx.beginPath();ctx.arc(this.x,this.y,this.r,0,Math.PI*2);ctx.fillStyle=`rgba(${this.col},${this.a})`;ctx.fill()}}
function init(){p=[];for(let i=0;i<90;i++)p.push(new P())}
function loop(){ctx.clearRect(0,0,W,H);p.forEach(d=>{d.update();d.draw()});requestAnimationFrame(loop)}
window.addEventListener('resize',()=>{resize();init()});resize();init();loop();
</script>
</body>
</html>"""

HTML_LOGIN = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS VPS — SECURE ACCESS</title>
<link href="https://fonts.googleapis.com/css2?family=El+Messiri:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--c1:#00F5D4;--c2:#00BBF9;--c3:#9B5DE5;--c4:#F15BB5;--bg:#050810;--card:rgba(10,18,30,0.8);--brd:rgba(0,245,212,0.15);--mt:rgba(232,244,248,0.4);--txt:#E8F4F8}
body{font-family:'El Messiri',sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;display:flex;align-items:center;justify-content:center;overflow:hidden;text-transform:uppercase;letter-spacing:1.5px;font-weight:600}
canvas#bg{position:fixed;inset:0;z-index:0;opacity:0.5;pointer-events:none}
.orb{position:fixed;border-radius:50%;filter:blur(140px);pointer-events:none;z-index:0}
.o1{width:500px;height:500px;top:-200px;right:-150px;background:rgba(0,245,212,0.12)}
.o2{width:500px;height:500px;bottom:-200px;left:-150px;background:rgba(155,93,229,0.12)}
.o3{width:400px;height:400px;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(241,91,181,0.06)}
.box{position:relative;z-index:1;width:100%;max-width:440px;margin:0 20px;animation:rise 0.7s ease}
.box-inner{background:var(--card);backdrop-filter:blur(40px);border-radius:24px;padding:52px 40px 44px;border:1px solid var(--brd);box-shadow:0 40px 100px rgba(0,0,0,0.7),inset 0 0 80px rgba(0,245,212,0.03)}
.logo{text-align:center;margin-bottom:40px}
.logo-icon{width:68px;height:68px;border-radius:18px;background:linear-gradient(135deg,var(--c1),var(--c3));display:inline-flex;align-items:center;justify-content:center;font-size:28px;font-weight:700;color:#050810;box-shadow:0 0 50px rgba(0,245,212,0.35);margin-bottom:16px}
.logo-text{font-size:32px;font-weight:700;background:linear-gradient(135deg,var(--c1),var(--c2),var(--c4));background-size:300% 300%;-webkit-background-clip:text;-webkit-text-fill-color:transparent;animation:gradient 5s ease infinite;letter-spacing:5px}
.logo-sub{font-size:10px;color:var(--mt);letter-spacing:6px;margin-top:6px}
.error{background:rgba(241,91,181,0.08);border:1px solid rgba(241,91,181,0.25);border-radius:12px;padding:14px 18px;margin-bottom:26px;color:#F15BB5;font-size:11px;font-weight:700;text-align:center;letter-spacing:3px}
.field{margin-bottom:22px}
.field label{display:block;font-size:10px;font-weight:700;color:var(--mt);letter-spacing:4px;margin-bottom:10px}
.field input{width:100%;padding:16px 18px;border-radius:12px;background:rgba(255,255,255,0.03);border:1px solid var(--brd);color:var(--txt);font-size:14px;font-family:'El Messiri',sans-serif;outline:none;transition:0.3s;text-transform:uppercase;letter-spacing:2px;font-weight:600}
.field input:focus{border-color:var(--c1);background:rgba(0,245,212,0.03);box-shadow:0 0 0 4px rgba(0,245,212,0.06)}
.btn-submit{width:100%;padding:18px;border:none;border-radius:12px;background:linear-gradient(135deg,var(--c1),var(--c2));color:#050810;font-size:14px;font-weight:700;letter-spacing:4px;cursor:pointer;transition:0.3s;box-shadow:0 8px 32px rgba(0,245,212,0.3);font-family:'El Messiri',sans-serif}
.btn-submit:hover{transform:translateY(-3px);box-shadow:0 12px 48px rgba(0,245,212,0.5)}
.back{text-align:center;margin-top:24px}
.back a{color:var(--mt);text-decoration:none;font-size:11px;font-weight:600;letter-spacing:4px;transition:0.3s}
.back a:hover{color:var(--c1)}
@keyframes rise{from{opacity:0;transform:translateY(40px) scale(0.96)}to{opacity:1;transform:translateY(0) scale(1)}}
@keyframes gradient{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
</style>
</head>
<body>
<canvas id="bg"></canvas>
<div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>
<div class="box">
<div class="box-inner">
<div class="logo"><div class="logo-icon">NX</div><div class="logo-text">NEXUS VPS</div><div class="logo-sub">SECURE ACCESS PORTAL</div></div>
{% if error %}<div class="error"><i class="fas fa-exclamation-triangle"></i> {{ error }}</div>{% endif %}
<form method="POST">
<div class="field"><label><i class="fas fa-user"></i> USERNAME</label><input type="text" name="username" placeholder="ENTER USERNAME" required></div>
<div class="field"><label><i class="fas fa-lock"></i> PASSWORD</label><input type="password" name="password" placeholder="ENTER PASSWORD" required></div>
<button type="submit" class="btn-submit"><i class="fas fa-arrow-right-to-bracket"></i> ACCESS</button>
</form>
<div class="back"><a href="/"><i class="fas fa-arrow-left"></i> BACK TO HOME</a></div>
</div>
</div>
<script>
const c=document.getElementById('bg'),ctx=c.getContext('2d');
let W,H,p=[];
function resize(){W=c.width=innerWidth;H=c.height=innerHeight}
class P{constructor(){this.reset()}reset(){this.x=Math.random()*W;this.y=Math.random()*H;this.vx=(Math.random()-.5)*0.3;this.vy=(Math.random()-.5)*0.3;this.r=Math.random()*1.4+0.4;this.a=Math.random()*0.25+0.05;const cols=['0,245,212','0,187,249','155,93,229','241,91,181'];this.col=cols[Math.floor(Math.random()*cols.length)]}update(){this.x+=this.vx;this.y+=this.vy;if(this.x<0||this.x>W||this.y<0||this.y>H)this.reset()}draw(){ctx.beginPath();ctx.arc(this.x,this.y,this.r,0,Math.PI*2);ctx.fillStyle=`rgba(${this.col},${this.a})`;ctx.fill()}}
function init(){p=[];for(let i=0;i<60;i++)p.push(new P())}
function loop(){ctx.clearRect(0,0,W,H);p.forEach(d=>{d.update();d.draw()});requestAnimationFrame(loop)}
window.addEventListener('resize',()=>{resize();init()});resize();init();loop();
</script>
</body>
</html>"""

HTML_OWNER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS VPS — OWNER CONTROL</title>
<link href="https://fonts.googleapis.com/css2?family=El+Messiri:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --c1:#00F5D4;--c2:#00BBF9;--c3:#9B5DE5;--c4:#F15BB5;
  --bg:#050810;--card:rgba(10,18,30,0.75);
  --brd:rgba(0,245,212,0.15);--txt:#E8F4F8;--mt:rgba(232,244,248,0.45);
}
body{font-family:'El Messiri',sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;text-transform:uppercase;letter-spacing:1.5px;font-weight:600}
canvas#bg{position:fixed;inset:0;z-index:0;opacity:0.35;pointer-events:none}
.mesh{position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 60% 50% at 10% 5%,rgba(0,245,212,0.1),transparent 60%),
    radial-gradient(ellipse 55% 45% at 90% 15%,rgba(155,93,229,0.1),transparent 60%),
    radial-gradient(ellipse 50% 40% at 50% 100%,rgba(241,91,181,0.08),transparent 60%);
}
.layout{position:relative;z-index:1;display:grid;grid-template-columns:260px 1fr;min-height:100vh}
.sidebar{background:rgba(5,8,16,0.85);backdrop-filter:blur(30px);border-right:1px solid var(--brd);padding:28px 20px;position:sticky;top:0;height:100vh;display:flex;flex-direction:column}
.side-brand{display:flex;align-items:center;gap:12px;margin-bottom:36px;padding-bottom:24px;border-bottom:1px solid var(--brd)}
.side-icon{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,var(--c1),var(--c3));display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#050810;box-shadow:0 0 30px rgba(0,245,212,0.35)}
.side-title{font-size:18px;font-weight:700;background:linear-gradient(135deg,var(--c1),var(--c4));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:3px}
.side-sub{font-size:8px;color:var(--c4);letter-spacing:4px;margin-top:2px}
.side-nav{display:flex;flex-direction:column;gap:6px;flex:1}
.side-link{display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:10px;color:var(--mt);text-decoration:none;font-size:12px;font-weight:600;letter-spacing:2px;transition:0.3s;border:1px solid transparent}
.side-link:hover{background:rgba(0,245,212,0.05);color:var(--c1);border-color:rgba(0,245,212,0.15)}
.side-link.active{background:linear-gradient(135deg,rgba(0,245,212,0.1),rgba(155,93,229,0.1));color:var(--c1);border-color:rgba(0,245,212,0.25)}
.side-link i{font-size:14px;width:18px}
.side-status{padding:14px;background:rgba(0,245,212,0.04);border:1px solid rgba(0,245,212,0.1);border-radius:10px;margin-top:20px}
.side-status .lbl{font-size:9px;color:var(--mt);letter-spacing:3px;margin-bottom:6px}
.side-status .val{font-size:11px;font-weight:700;color:var(--c1);letter-spacing:2px;display:flex;align-items:center;gap:6px}
.dot-live{width:6px;height:6px;border-radius:50%;background:var(--c1);box-shadow:0 0 10px var(--c1);animation:pulse 2s infinite}
.main{padding:28px 32px;overflow-y:auto}
.page-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px;flex-wrap:wrap;gap:12px}
.page-title{font-size:26px;font-weight:700;letter-spacing:4px;background:linear-gradient(135deg,var(--c1),var(--c3));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.page-desc{font-size:10px;color:var(--mt);letter-spacing:3px;margin-top:4px}
.btn{padding:10px 20px;border-radius:10px;border:none;font-size:11px;font-weight:700;letter-spacing:3px;cursor:pointer;transition:0.3s;text-decoration:none;display:inline-flex;align-items:center;gap:8px;font-family:'El Messiri',sans-serif}
.btn-primary{background:linear-gradient(135deg,var(--c1),var(--c2));color:#050810;box-shadow:0 6px 24px rgba(0,245,212,0.3)}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 10px 36px rgba(0,245,212,0.5)}
.btn-danger{background:rgba(241,91,181,0.1);color:var(--c4);border:1px solid rgba(241,91,181,0.25)}
.btn-danger:hover{background:rgba(241,91,181,0.2)}
.btn-ghost{background:rgba(255,255,255,0.03);color:var(--txt);border:1px solid var(--brd)}
.btn-ghost:hover{border-color:var(--c1);color:var(--c1)}
.btn-sm{padding:6px 12px;font-size:9px;letter-spacing:2px;border-radius:8px}
.grid-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:24px}
.stat{background:var(--card);backdrop-filter:blur(20px);border:1px solid var(--brd);border-radius:16px;padding:20px 22px;transition:0.3s;position:relative;overflow:hidden}
.stat::after{content:'';position:absolute;top:0;right:0;width:80px;height:80px;background:radial-gradient(circle,rgba(0,245,212,0.15),transparent 70%);border-radius:50%}
.stat:hover{border-color:var(--c1);transform:translateY(-3px)}
.stat .lbl{font-size:9px;color:var(--mt);letter-spacing:4px;margin-bottom:8px}
.stat .val{font-size:28px;font-weight:700;background:linear-gradient(135deg,var(--c1),var(--c3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:2px}
.stat .sub{font-size:9px;color:var(--mt);letter-spacing:2px;margin-top:4px}
.panel{background:var(--card);backdrop-filter:blur(20px);border:1px solid var(--brd);border-radius:16px;padding:22px 24px;margin-bottom:18px;transition:0.3s}
.panel:hover{border-color:rgba(0,245,212,0.25)}
.panel-head{display:flex;align-items:center;gap:10px;margin-bottom:16px}
.panel-head i{font-size:16px;color:var(--c1)}
.panel-head h2{font-size:13px;font-weight:700;letter-spacing:4px;color:var(--txt)}
.form-grid{display:grid;grid-template-columns:1fr 1fr 100px auto;gap:10px;align-items:end}
.input-group{display:flex;flex-direction:column;gap:6px}
.input-group label{font-size:9px;color:var(--mt);letter-spacing:3px}
.input-group input{padding:12px 14px;border-radius:10px;background:rgba(255,255,255,0.03);border:1px solid var(--brd);color:var(--txt);font-size:12px;font-family:'El Messiri',sans-serif;outline:none;transition:0.3s;text-transform:uppercase;letter-spacing:1px;font-weight:600}
.input-group input:focus{border-color:var(--c1);background:rgba(0,245,212,0.03);box-shadow:0 0 0 3px rgba(0,245,212,0.05)}
.input-group input::placeholder{color:rgba(232,244,248,0.15);font-size:11px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{padding:12px 14px;text-align:left;font-size:9px;font-weight:700;letter-spacing:3px;color:var(--mt);border-bottom:1px solid var(--brd);background:rgba(5,8,16,0.6);position:sticky;top:0;z-index:2}
td{padding:12px 14px;border-bottom:1px solid rgba(255,255,255,0.03);font-size:11px;letter-spacing:1px}
tr:hover td{background:rgba(0,245,212,0.02)}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:50px;font-size:8px;font-weight:700;letter-spacing:2px}
.badge-active{background:rgba(0,245,212,0.1);color:var(--c1);border:1px solid rgba(0,245,212,0.2)}
.badge-expired{background:rgba(241,91,181,0.1);color:var(--c4);border:1px solid rgba(241,91,181,0.2)}
.badge-soon{background:rgba(255,193,7,0.1);color:#FFC107;border:1px solid rgba(255,193,7,0.2)}
.link-pill{font-size:9px;color:var(--c2);text-decoration:none;padding:4px 8px;border-radius:6px;background:rgba(0,187,249,0.08);border:1px solid rgba(0,187,249,0.15);transition:0.3s;letter-spacing:1px;word-break:break-all;display:inline-block;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:middle}
.link-pill:hover{background:rgba(0,187,249,0.15);color:var(--c1)}
.actions-cell{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.inline-form{display:inline-flex;align-items:center;gap:4px}
.inline-form input[type="number"]{width:52px;padding:6px 8px;border-radius:6px;background:rgba(255,255,255,0.03);border:1px solid var(--brd);color:var(--txt);font-size:10px;text-align:center;outline:none;font-family:'El Messiri',sans-serif}
.table-wrap{max-height:480px;overflow-y:auto;border-radius:12px}
.table-wrap::-webkit-scrollbar{width:6px}
.table-wrap::-webkit-scrollbar-track{background:transparent}
.table-wrap::-webkit-scrollbar-thumb{background:rgba(0,245,212,0.2);border-radius:10px}
.empty{text-align:center;padding:40px 20px;color:var(--mt);font-size:11px;letter-spacing:3px}
.empty i{font-size:36px;display:block;margin-bottom:12px;color:rgba(0,245,212,0.2)}
@media(max-width:900px){.layout{grid-template-columns:1fr}.sidebar{position:relative;height:auto;flex-direction:row;overflow-x:auto;padding:16px}.side-brand{margin-bottom:0;padding-bottom:0;border:none}.side-nav{flex-direction:row;flex:0}.side-status{display:none}.main{padding:20px 16px}.form-grid{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.form-grid{grid-template-columns:1fr}.page-title{font-size:20px}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
</style>
</head>
<body>
<canvas id="bg"></canvas><div class="mesh"></div>
<div class="layout">
<aside class="sidebar">
<div class="side-brand">
<div class="side-icon">NX</div>
<div><div class="side-title">NEXUS</div><div class="side-sub">OWNER CONTROL</div></div>
</div>
<nav class="side-nav">
<a href="/owner" class="side-link active"><i class="fas fa-users"></i> USERS</a>
<a href="/logout" class="side-link"><i class="fas fa-sign-out-alt"></i> LOGOUT</a>
</nav>
<div class="side-status">
<div class="lbl">PHP RUNTIME</div>
<div class="val">{% if php_available %}<span class="dot-live"></span> ONLINE{% else %}<span style="color:var(--c4)">OFFLINE</span>{% endif %}</div>
</div>
</aside>
<main class="main">
<div class="page-head">
<div>
<div class="page-title"><i class="fas fa-crown" style="font-size:18px;margin-right:8px"></i>OWNER DASHBOARD</div>
<div class="page-desc">MANAGE USERS · MONITOR SERVERS · CONTROL ACCESS</div>
</div>
<a href="/logout" class="btn btn-danger"><i class="fas fa-sign-out-alt"></i> LOGOUT</a>
</div>

<div class="grid-stats">
<div class="stat"><div class="lbl">TOTAL USERS</div><div class="val">{{ users|length }}</div><div class="sub">REGISTERED ACCOUNTS</div></div>
<div class="stat"><div class="lbl">SERVER STATUS</div><div class="val">{% if php_available %}READY{% else %}OFF{% endif %}</div><div class="sub">PHP RUNTIME</div></div>
<div class="stat"><div class="lbl">SHARE LINKS</div><div class="val">{{ users|length }}</div><div class="sub">ACTIVE AUTO-LOGINS</div></div>
</div>

<div class="panel">
<div class="panel-head"><i class="fas fa-user-plus"></i><h2>CREATE NEW USER</h2></div>
<form method="POST" action="/owner/create" class="form-grid">
<div class="input-group"><label>USERNAME</label><input type="text" name="username" placeholder="ENTER USERNAME" required></div>
<div class="input-group"><label>PASSWORD</label><input type="text" name="password" placeholder="ENTER PASSWORD" required></div>
<div class="input-group"><label>DAYS</label><input type="number" name="days" value="7" min="1"></div>
<button type="submit" class="btn btn-primary"><i class="fas fa-plus"></i> CREATE</button>
</form>
</div>

<div class="panel">
<div class="panel-head"><i class="fas fa-users"></i><h2>USER MANAGEMENT ({{ users|length }})</h2></div>
{% if users %}
<div class="table-wrap">
<table>
<thead><tr><th>USERNAME</th><th>PASSWORD</th><th>EXPIRES</th><th>STATUS</th><th>AUTO-LOGIN LINK</th><th>ACTIONS</th></tr></thead>
<tbody>
{% for username, info in users.items() %}
<tr>
<td><strong style="color:var(--c1);letter-spacing:2px">{{ username }}</strong></td>
<td><span style="font-family:monospace;color:var(--c3);font-size:11px">{{ info.password }}</span></td>
<td style="color:var(--mt);font-size:10px">{% if info.expires_at %}{{ time.strftime('%Y-%m-%d %H:%M', time.localtime(info.expires_at)) }}{% else %}NEVER{% endif %}</td>
<td>
{% if info.expires_at and info.expires_at < now %}<span class="badge badge-expired">EXPIRED</span>
{% elif info.expires_at and info.expires_at < now + 86400*3 %}<span class="badge badge-soon">SOON</span>
{% else %}<span class="badge badge-active">ACTIVE</span>{% endif %}
</td>
<td><a href="{{ base_url }}/auto/{{ info.token }}" target="_blank" class="link-pill"><i class="fas fa-link"></i> {{ info.token[:14] }}…</a></td>
<td>
<div class="actions-cell">
<form method="POST" action="/owner/extend/{{ username }}" class="inline-form">
<input type="number" name="days" value="7" min="1">
<button type="submit" class="btn btn-ghost btn-sm" title="EXTEND"><i class="fas fa-clock"></i></button>
</form>
<form method="POST" action="/owner/delete/{{ username }}" onsubmit="return confirm('DELETE {{ username }}?')">
<button type="submit" class="btn btn-danger btn-sm" title="DELETE"><i class="fas fa-trash"></i></button>
</form>
</div>
</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
{% else %}
<div class="empty"><i class="fas fa-user-slash"></i>NO USERS YET — CREATE ONE ABOVE</div>
{% endif %}
</div>
</main>
</div>
<script>
const c=document.getElementById('bg'),ctx=c.getContext('2d');
let W,H,p=[];
function resize(){W=c.width=innerWidth;H=c.height=innerHeight}
class P{constructor(){this.reset()}reset(){this.x=Math.random()*W;this.y=Math.random()*H;this.vx=(Math.random()-.5)*0.3;this.vy=(Math.random()-.5)*0.3;this.r=Math.random()*1.6+0.4;this.a=Math.random()*0.3+0.08;const cols=['0,245,212','0,187,249','155,93,229','241,91,181'];this.col=cols[Math.floor(Math.random()*cols.length)]}update(){this.x+=this.vx;this.y+=this.vy;if(this.x<0||this.x>W||this.y<0||this.y>H)this.reset()}draw(){ctx.beginPath();ctx.arc(this.x,this.y,this.r,0,Math.PI*2);ctx.fillStyle=`rgba(${this.col},${this.a})`;ctx.fill()}}
function init(){p=[];for(let i=0;i<70;i++)p.push(new P())}
function loop(){ctx.clearRect(0,0,W,H);p.forEach(d=>{d.update();d.draw()});requestAnimationFrame(loop)}
window.addEventListener('resize',()=>{resize();init()});resize();init();loop();
</script>
</body>
</html>"""

HTML_USER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS VPS — DASHBOARD</title>
<link href="https://fonts.googleapis.com/css2?family=El+Messiri:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--c1:#00F5D4;--c2:#00BBF9;--c3:#9B5DE5;--c4:#F15BB5;--bg:#050810;--card:rgba(10,18,30,0.75);--brd:rgba(0,245,212,0.15);--txt:#E8F4F8;--mt:rgba(232,244,248,0.45)}
body{font-family:'El Messiri',sans-serif;background:var(--bg);color:var(--txt);min-height:100vh;text-transform:uppercase;letter-spacing:1.5px;font-weight:600}
canvas#bg{position:fixed;inset:0;z-index:0;opacity:0.35;pointer-events:none}
.mesh{position:fixed;inset:0;z-index:0;pointer-events:none;background:radial-gradient(ellipse 60% 50% at 10% 5%,rgba(0,245,212,0.1),transparent 60%),radial-gradient(ellipse 55% 45% at 90% 15%,rgba(155,93,229,0.1),transparent 60%),radial-gradient(ellipse 50% 40% at 50% 100%,rgba(241,91,181,0.08),transparent 60%)}
.glass-nav{position:sticky;top:0;z-index:50;backdrop-filter:blur(30px);background:rgba(5,8,16,0.75);border-bottom:1px solid var(--brd);padding:0.8rem 2rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.brand{display:flex;align-items:center;gap:10px}
.brand-icon{width:40px;height:40px;border-radius:11px;background:linear-gradient(135deg,var(--c1),var(--c3));display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#050810;box-shadow:0 0 25px rgba(0,245,212,0.3)}
.brand-text{font-size:22px;font-weight:700;background:linear-gradient(135deg,var(--c1),var(--c4));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:4px}
.user-info{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.user-badge{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,0.03);padding:6px 16px;border-radius:50px;border:1px solid var(--brd)}
.user-badge i{color:var(--c1);font-size:12px}
.user-badge .uname{font-size:12px;font-weight:700;letter-spacing:2px}
.user-badge .expiry{font-size:9px;color:var(--mt);letter-spacing:2px}
.btn{padding:8px 18px;border-radius:10px;border:none;font-size:10px;font-weight:700;letter-spacing:3px;cursor:pointer;transition:0.3s;text-decoration:none;display:inline-flex;align-items:center;gap:6px;font-family:'El Messiri',sans-serif}
.btn-primary{background:linear-gradient(135deg,var(--c1),var(--c2));color:#050810;box-shadow:0 6px 24px rgba(0,245,212,0.3)}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 10px 36px rgba(0,245,212,0.5)}
.btn-danger{background:rgba(241,91,181,0.1);color:var(--c4);border:1px solid rgba(241,91,181,0.25)}
.btn-danger:hover{background:rgba(241,91,181,0.2)}
.btn-success{background:rgba(0,245,212,0.1);color:var(--c1);border:1px solid rgba(0,245,212,0.25)}
.btn-success:hover{background:rgba(0,245,212,0.2)}
.btn-ghost{background:rgba(255,255,255,0.03);color:var(--txt);border:1px solid var(--brd)}
.btn-ghost:hover{border-color:var(--c1);color:var(--c1)}
.btn-sm{padding:6px 12px;font-size:9px;letter-spacing:2px}
.wrap{position:relative;z-index:1;max-width:1260px;margin:0 auto;padding:18px 22px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}
.panel{background:var(--card);backdrop-filter:blur(20px);border:1px solid var(--brd);border-radius:16px;padding:20px 22px;transition:0.3s}
.panel:hover{border-color:rgba(0,245,212,0.25)}
.panel-head{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.panel-head i{font-size:15px;color:var(--c1)}
.panel-head h2{font-size:12px;font-weight:700;letter-spacing:4px}
.status-row{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.status-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.status-dot.running{background:var(--c1);box-shadow:0 0 18px var(--c1);animation:pulse 2s infinite}
.status-dot.stopped{background:var(--c4);box-shadow:0 0 18px rgba(241,91,181,0.5)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.status-label{font-size:12px;font-weight:700;letter-spacing:3px}
.status-label.running{color:var(--c1)}
.status-label.stopped{color:var(--c4)}
.running-file{font-size:10px;font-family:monospace;color:var(--mt);background:rgba(255,255,255,0.03);padding:5px 12px;border-radius:6px;border:1px solid var(--brd);display:inline-block;margin-bottom:12px;letter-spacing:1px}
.running-file span{color:var(--c1)}
.ctrl-group{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.file-select{flex:1;min-width:140px;padding:10px 14px;background:rgba(255,255,255,0.03);border:1px solid var(--brd);border-radius:10px;color:var(--txt);font-size:11px;font-family:'El Messiri',sans-serif;outline:none;cursor:pointer;transition:0.3s;text-transform:uppercase;letter-spacing:1px;font-weight:600}
.file-select:focus{border-color:var(--c1)}
.file-select option{background:#050810}
.upload-zone{border:2px dashed var(--brd);border-radius:14px;padding:26px;text-align:center;cursor:pointer;transition:0.3s}
.upload-zone:hover{border-color:var(--c1);background:rgba(0,245,212,0.02)}
.upload-zone.drag-over{border-color:var(--c1);background:rgba(0,245,212,0.05)}
.upload-zone i{font-size:32px;color:rgba(0,245,212,0.25);display:block;margin-bottom:8px}
.upload-zone p{font-size:11px;color:var(--mt);font-weight:600;letter-spacing:2px}
.upload-zone input{display:none}
.file-list{display:flex;flex-direction:column;gap:8px;margin-top:12px}
.file-item{display:flex;align-items:center;gap:10px;padding:10px 14px;background:rgba(255,255,255,0.02);border:1px solid var(--brd);border-radius:10px;transition:0.3s}
.file-item:hover{border-color:rgba(0,245,212,0.3);background:rgba(0,245,212,0.03)}
.file-icon{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.file-icon.php{background:rgba(155,93,229,0.15);color:var(--c3);border:1px solid rgba(155,93,229,0.3)}
.file-icon.html{background:rgba(0,245,212,0.1);color:var(--c1);border:1px solid rgba(0,245,212,0.25)}
.file-icon.other{background:rgba(0,187,249,0.1);color:var(--c2);border:1px solid rgba(0,187,249,0.25)}
.file-info{flex:1;min-width:0}
.file-name{font-size:11px;font-weight:700;letter-spacing:1px;color:var(--txt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.file-meta{font-size:9px;color:var(--mt);letter-spacing:2px;margin-top:2px}
.file-actions{display:flex;gap:4px;flex-shrink:0}
.file-actions a,.file-actions button{width:30px;height:30px;border-radius:8px;background:rgba(255,255,255,0.03);border:1px solid var(--brd);color:var(--mt);cursor:pointer;display:inline-flex;align-items:center;justify-content:center;font-size:11px;transition:0.3s;text-decoration:none}
.file-actions a:hover{background:rgba(0,245,212,0.1);color:var(--c1);border-color:rgba(0,245,212,0.3)}
.file-actions button:hover{background:rgba(241,91,181,0.1);color:var(--c4);border-color:rgba(241,91,181,0.3)}
.terminal{background:#020408;border-radius:12px;overflow:hidden;border:1px solid rgba(0,245,212,0.1);margin-top:8px}
.term-bar{display:flex;align-items:center;gap:6px;padding:8px 14px;background:rgba(0,245,212,0.03);border-bottom:1px solid rgba(0,245,212,0.08)}
.term-dot{width:8px;height:8px;border-radius:50%}
.term-dot.r{background:#F15BB5}.term-dot.y{background:#FFC107}.term-dot.g{background:#00F5D4}
.term-title{margin-left:6px;font-size:9px;color:var(--mt);letter-spacing:3px;font-family:monospace}
.term-body{padding:12px 16px;max-height:160px;overflow-y:auto;font-family:'Courier New',monospace;font-size:10px;line-height:1.9;white-space:pre-wrap;word-break:break-word;color:#A5F3E0;letter-spacing:0.5px}
.term-body::-webkit-scrollbar{width:4px}
.term-body::-webkit-scrollbar-thumb{background:rgba(0,245,212,0.2);border-radius:10px}
.share-badge{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;background:rgba(0,245,212,0.08);border:1px solid rgba(0,245,212,0.2);border-radius:8px;font-size:9px;color:var(--c1);letter-spacing:2px;cursor:pointer;transition:0.3s;font-family:monospace}
.share-badge:hover{background:rgba(0,245,212,0.15)}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
@media(max-width:600px){.glass-nav{padding:0.8rem 1rem}.wrap{padding:12px 14px}}
</style>
</head>
<body>
<canvas id="bg"></canvas><div class="mesh"></div>
<nav class="glass-nav">
<div class="brand"><div class="brand-icon">NX</div><span class="brand-text">NEXUS</span></div>
<div class="user-info">
<div class="user-badge"><i class="fas fa-user-astronaut"></i><span class="uname">{{ username }}</span>{% if expires_at %}<span class="expiry">⚡ {{ expires_at|timestamp_to_date }}</span>{% endif %}</div>
<a href="/logout" class="btn btn-danger btn-sm"><i class="fas fa-sign-out-alt"></i> LOGOUT</a>
</div>
</nav>
<div class="wrap">
<div class="grid">
<div class="panel">
<div class="panel-head"><i class="fas fa-server"></i><h2>PHP SERVER</h2></div>
{% if not php_available %}
<div style="padding:14px;background:rgba(241,91,181,0.08);border:1px solid rgba(241,91,181,0.2);border-radius:10px;font-size:10px;color:var(--c4);letter-spacing:2px;text-align:center;margin-bottom:12px"><i class="fas fa-exclamation-triangle"></i> PHP NOT INSTALLED ON SERVER</div>
{% endif %}
<div class="status-row"><div class="status-dot {% if php_running %}running{% else %}stopped{% endif %}"></div><span class="status-label {% if php_running %}running{% else %}stopped{% endif %}">{% if php_running %}● RUNNING ON PORT {{ php_port }}{% else %}● STOPPED{% endif %}</span></div>
{% if php_file %}<div class="running-file">ACTIVE: <span>{{ php_file }}</span></div>{% endif %}
<div class="ctrl-group">
<select class="file-select" id="phpSelect">
<option value="">— SELECT PHP FILE —</option>
{% for f in php_files %}<option value="{{ f }}">{{ f }}</option>{% endfor %}
</select>
</div>
<div class="ctrl-group">
<button class="btn btn-success" onclick="phpStart()"><i class="fas fa-play"></i> START</button>
<button class="btn btn-danger" onclick="phpStop()"><i class="fas fa-stop"></i> STOP</button>
<button class="btn btn-ghost" onclick="phpRestart()"><i class="fas fa-sync"></i> RESTART</button>
</div>
<div class="terminal"><div class="term-bar"><span class="term-dot r"></span><span class="term-dot y"></span><span class="term-dot g"></span><span class="term-title">PHP LOGS</span></div><div class="term-body" id="phpLogs">[SYSTEM] WAITING…</div></div>
</div>

<div class="panel">
<div class="panel-head"><i class="fas fa-cloud-upload-alt"></i><h2>UPLOAD FILES</h2></div>
<div class="upload-zone" id="uploadZone"><i class="fas fa-cloud-upload-alt"></i><p>DRAG &amp; DROP OR CLICK TO UPLOAD</p><p style="font-size:9px;margin-top:6px;color:rgba(232,244,248,0.25)">SUPPORTS .PHP .HTML .HTM .CSS .JS .TXT</p><input type="file" id="fileInput" multiple></div>
</div>
</div>

<div class="grid">
<div class="panel">
<div class="panel-head"><i class="fas fa-file-code"></i><h2>PHP FILES ({{ php_files|length }})</h2></div>
{% if php_files %}
<div class="file-list">
{% for f in php_files %}
<div class="file-item">
<div class="file-icon php"><i class="fas fa-code"></i></div>
<div class="file-info"><div class="file-name">{{ f }}</div><div class="file-meta">PHP SCRIPT</div></div>
<div class="file-actions">
<a href="/file/view/{{ f }}" target="_blank" title="VIEW"><i class="fas fa-eye"></i></a>
<a href="/download/{{ f }}" title="DOWNLOAD"><i class="fas fa-download"></i></a>
<form method="POST" action="/file/delete/{{ f }}" onsubmit="return confirm('DELETE?')"><button type="submit" title="DELETE"><i class="fas fa-trash"></i></button></form>
</div>
</div>
{% endfor %}
</div>
{% else %}<div style="text-align:center;padding:24px;color:var(--mt);font-size:10px;letter-spacing:2px">NO PHP FILES UPLOADED</div>{% endif %}
</div>

<div class="panel">
<div class="panel-head"><i class="fas fa-globe"></i><h2>HTML FILES ({{ html_files|length }})</h2></div>
{% if html_files %}
<div class="file-list">
{% for f in html_files %}
<div class="file-item">
<div class="file-icon html"><i class="fas fa-file-code"></i></div>
<div class="file-info"><div class="file-name">{{ f }}</div><div class="file-meta">SHAREABLE LINK READY</div></div>
<div class="file-actions">
<button class="share-badge" onclick="copyLink('{{ base_url }}/share/{{ username }}/{{ f }}')" title="COPY LINK"><i class="fas fa-link"></i></button>
<a href="/file/view/{{ f }}" target="_blank" title="VIEW"><i class="fas fa-eye"></i></a>
<a href="/download/{{ f }}" title="DOWNLOAD"><i class="fas fa-download"></i></a>
<form method="POST" action="/file/delete/{{ f }}" onsubmit="return confirm('DELETE?')"><button type="submit" title="DELETE"><i class="fas fa-trash"></i></button></form>
</div>
</div>
{% endfor %}
</div>
{% else %}<div style="text-align:center;padding:24px;color:var(--mt);font-size:10px;letter-spacing:2px">NO HTML FILES UPLOADED</div>{% endif %}
</div>
</div>

{% if files %}
<div class="panel">
<div class="panel-head"><i class="fas fa-folder"></i><h2>OTHER FILES ({{ files|length }})</h2></div>
<div class="file-list">
{% for f in files %}
<div class="file-item">
<div class="file-icon other"><i class="fas fa-file"></i></div>
<div class="file-info"><div class="file-name">{{ f }}</div></div>
<div class="file-actions">
<a href="/file/view/{{ f }}" target="_blank"><i class="fas fa-eye"></i></a>
<a href="/download/{{ f }}"><i class="fas fa-download"></i></a>
<form method="POST" action="/file/delete/{{ f }}" onsubmit="return confirm('DELETE?')"><button type="submit"><i class="fas fa-trash"></i></button></form>
</div>
</div>
{% endfor %}
</div>
</div>
{% endif %}
</div>

<script>
function showToast(msg,type='success'){const el=document.createElement('div');el.style.cssText=`position:fixed;top:80px;right:20px;z-index:9999;padding:12px 20px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;backdrop-filter:blur(20px);border:1px solid ${type==='success'?'rgba(0,245,212,0.3)':'rgba(241,91,181,0.3)'};background:${type==='success'?'rgba(0,245,212,0.1)':'rgba(241,91,181,0.1)'};color:${type==='success'?'#00F5D4':'#F15BB5'};animation:slideIn 0.3s ease;font-family:'El Messiri',sans-serif`;el.textContent=msg;document.body.appendChild(el);setTimeout(()=>el.remove(),3000)}
const style=document.createElement('style');style.textContent='@keyframes slideIn{from{opacity:0;transform:translateX(30px)}to{opacity:1;transform:translateX(0)}}';document.head.appendChild(style);

function phpStart(){const f=document.getElementById('phpSelect').value;if(!f){showToast('SELECT A PHP FILE',false);return}fetch('/php/start',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'file='+encodeURIComponent(f)}).then(r=>r.json()).then(d=>{showToast(d.msg,d.ok);if(d.ok)setTimeout(()=>location.reload(),800)})}
function phpStop(){if(!confirm('STOP PHP SERVER?'))return;fetch('/php/stop',{method:'POST'}).then(()=>location.reload())}
function phpRestart(){const f=document.getElementById('phpSelect').value;if(!f)return;fetch('/php/restart',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'file='+encodeURIComponent(f)}).then(r=>r.json()).then(d=>{showToast(d.msg,d.ok);if(d.ok)setTimeout(()=>location.reload(),800)})}

function copyLink(link){navigator.clipboard.writeText(link).then(()=>showToast('LINK COPIED!'));}

function refreshLogs(){fetch('/logs').then(r=>r.json()).then(d=>{document.getElementById('phpLogs').textContent=d.logs&&d.logs.length?d.logs.join('\\n'):'[SYSTEM] NO OUTPUT'})}
refreshLogs();setInterval(refreshLogs,4000);

const uploadZone=document.getElementById('uploadZone');
const fileInput=document.getElementById('fileInput');
uploadZone.addEventListener('click',()=>fileInput.click());
uploadZone.addEventListener('dragover',e=>{e.preventDefault();uploadZone.classList.add('drag-over')});
uploadZone.addEventListener('dragleave',()=>uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop',e=>{e.preventDefault();uploadZone.classList.remove('drag-over');if(e.dataTransfer.files.length)uploadFiles(e.dataTransfer.files)});
fileInput.addEventListener('change',function(){if(this.files.length)uploadFiles(this.files);this.value=''});
function uploadFiles(files){const fd=new FormData();for(let f of files)fd.append('files',f);fetch('/upload',{method:'POST',body:fd}).then(()=>location.reload())}

const c=document.getElementById('bg'),ctx=c.getContext('2d');
let W,H,p=[];
function resize(){W=c.width=innerWidth;H=c.height=innerHeight}
class P{constructor(){this.reset()}reset(){this.x=Math.random()*W;this.y=Math.random()*H;this.vx=(Math.random()-.5)*0.3;this.vy=(Math.random()-.5)*0.3;this.r=Math.random()*1.6+0.4;this.a=Math.random()*0.3+0.08;const cols=['0,245,212','0,187,249','155,93,229','241,91,181'];this.col=cols[Math.floor(Math.random()*cols.length)]}update(){this.x+=this.vx;this.y+=this.vy;if(this.x<0||this.x>W||this.y<0||this.y>H)this.reset()}draw(){ctx.beginPath();ctx.arc(this.x,this.y,this.r,0,Math.PI*2);ctx.fillStyle=`rgba(${this.col},${this.a})`;ctx.fill()}}
function init(){p=[];for(let i=0;i<70;i++)p.push(new P())}
function loop(){ctx.clearRect(0,0,W,H);p.forEach(d=>{d.update();d.draw()});requestAnimationFrame(loop)}
window.addEventListener('resize',()=>{resize();init()});resize();init();loop();
</script>
</body>
</html>"""

# ============================================
#  MAIN
# ============================================
if __name__ == "__main__":
    print("\n" + "="*70)
    print("🚀 NEXUS VPS PANEL - ULTRA PREMIUM EDITION v3")
    print("="*70)
    print(f"📍 LOCAL:  http://127.0.0.1:5000")
    print(f"👤 OWNER:  {OWNER_USER} / {OWNER_PASS}")
    print(f"🐘 PHP:    {'AVAILABLE' if PHP_AVAILABLE else 'NOT INSTALLED'}")
    print(f"💚 HEALTH: http://127.0.0.1:5000/health")
    print("="*70 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)