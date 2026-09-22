import os
import secrets
import mimetypes
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_file, abort, jsonify, session
from werkzeug.utils import secure_filename
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

# Allowed extensions (security)
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx',
    'xls', 'xlsx', 'ppt', 'pptx', 'zip', 'rar', 'mp3', 'mp4',
    'csv', 'json', 'xml', 'webp', 'svg', 'py', 'js', 'html', 'css'
}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Rate limiting (brute-force protection)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_size(bytes_size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
@limiter.limit("10 per minute")
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    # Generate secure token for shareable link
    token = secrets.token_urlsafe(16)
    
    # Secure the original filename
    original_name = secure_filename(file.filename)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
    
    # Store file with token name (prevents path traversal)
    stored_name = f"{token}.{ext}" if ext else token
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
    file.save(filepath)
    
    # Get expiry days from request
    expiry_days = int(request.form.get('expiry', 7))
    expiry_days = min(max(expiry_days, 1), 30)  # 1-30 days only
    
    file_size = os.path.getsize(filepath)
    
    return jsonify({
        'success': True,
        'token': token,
        'share_url': url_for('download', token=token, _external=True),
        'filename': original_name,
        'size': get_file_size(file_size),
        'expiry': expiry_days
    })

@app.route('/d/<token>')
@limiter.limit("30 per minute")
def download(token):
    # Sanitize token (only alphanumeric, dash, underscore)
    if not token.replace('-', '').replace('_', '').isalnum():
        abort(400)
    
    # Find file matching token
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if filename.startswith(token):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Check file age (expiry)
            file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(filepath))
            if file_age > timedelta(days=30):
                os.remove(filepath)
                return render_template('error.html', 
                    error="This file has expired and been deleted."), 410
            
            original_name = filename[len(token)+1:] if '.' in filename else filename
            return send_file(filepath, as_attachment=True, 
                           download_name=f"file.{filename.rsplit('.',1)[-1]}")
    
    return render_template('error.html', 
        error="File not found or link has expired."), 404

@app.route('/api/info/<token>')
def file_info(token):
    if not token.replace('-', '').replace('_', '').isalnum():
        return jsonify({'error': 'Invalid token'}), 400
    
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        if filename.startswith(token):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            size = os.path.getsize(filepath)
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            ext = filename.rsplit('.', 1)[-1].lower()
            
            return jsonify({
                'filename': filename,
                'size': get_file_size(size),
                'uploaded': mtime.strftime('%d %b %Y, %I:%M %p'),
                'type': ext.upper()
            })
    return jsonify({'error': 'Not found'}), 404

# Security Headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

@app.errorhandler(413)
def too_large(e):
    return render_template('error.html', error="File too large. Max size is 50MB."), 413

@app.errorhandler(429)
def ratelimit_handler(e):
    return render_template('error.html', error="Too many requests. Please try again later."), 429

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error="Page not found."), 404

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
