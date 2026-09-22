import os
import secrets
import mimetypes
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, abort, redirect
from werkzeug.utils import secure_filename
from vercel_blob import put, list as blob_list, delete as blob_delete
import io

app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

# Allowed extensions (security)
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx',
    'xls', 'xlsx', 'ppt', 'pptx', 'zip', 'rar', 'mp3', 'mp4',
    'csv', 'json', 'xml', 'webp', 'svg', 'py', 'js', 'html', 'css'
}

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
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    # Secure the original filename
    original_name = secure_filename(file.filename)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
    
    # Generate secure token
    token = secrets.token_urlsafe(16)
    stored_name = f"{token}.{ext}" if ext else token
    
    # File size check
    file_data = file.read()
    file_size = len(file_data)
    
    if file_size > 50 * 1024 * 1024:
        return jsonify({'error': 'File too large (max 50MB)'}), 400
    
    try:
        # Vercel Blob pe upload karo
        blob = put(
            stored_name,
            file_data,
            options={
                'access': 'public',
                'addRandomSuffix': False,
                'contentType': file.content_type or 'application/octet-stream'
            }
        )
        
        # Blob URL milega
        blob_url = blob.get('url')
        
        # Share URL — hamare khud ke download route se (original filename preserve karne ke liye)
        share_url = request.host_url.rstrip('/') + f"/d/{token}"
        
        return jsonify({
            'success': True,
            'token': token,
            'share_url': share_url,
            'direct_url': blob_url,
            'filename': original_name,
            'size': get_file_size(file_size),
            'expiry': 7
        })
    
    except Exception as e:
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/d/<token>')
def download(token):
    # Token validation
    if not token.replace('-', '').replace('_', '').isalnum():
        abort(400)
    
    try:
        # Vercel Blob se list karo aur matching file dhoondo
        blobs = blob_list({'prefix': token})
        
        matching = None
        for b in blobs.get('blobs', []):
            if b['pathname'].startswith(token):
                matching = b
                break
        
        if not matching:
            return render_template('error.html', 
                error="File not found or link has expired."), 404
        
        # Blob URL pe redirect karo (CDN se seedha download hoga)
        blob_url = matching['url']
        
        # Original filename extract karo
        ext = matching['pathname'].rsplit('.', 1)[-1] if '.' in matching['pathname'] else 'bin'
        download_name = f"file.{ext}"
        
        # Redirect with download param (Vercel Blob supports ?download=1)
        return redirect(f"{blob_url}?download=1", code=302)
    
    except Exception as e:
        return render_template('error.html', 
            error=f"Error: {str(e)}"), 500

@app.route('/api/info/<token>')
def file_info(token):
    if not token.replace('-', '').replace('_', '').isalnum():
        return jsonify({'error': 'Invalid token'}), 400
    
    try:
        blobs = blob_list({'prefix': token})
        for b in blobs.get('blobs', []):
            if b['pathname'].startswith(token):
                return jsonify({
                    'filename': b['pathname'],
                    'size': get_file_size(b.get('size', 0)),
                    'uploaded': b.get('uploadedAt', 'Unknown'),
                    'url': b['url']
                })
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error="Page not found."), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error="Something went wrong on our end."), 500

# Local development ke liye
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
