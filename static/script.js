const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const uploadBtn = document.getElementById('uploadBtn');
const progressContainer = document.getElementById('progressContainer');
const progressFill = document.getElementById('progressFill');
const progressText = document.getElementById('progressText');
const resultCard = document.getElementById('resultCard');
const uploadCard = document.getElementById('uploadCard');
const shareLink = document.getElementById('shareLink');

let selectedFile = null;

dropzone.addEventListener('click', () => fileInput.click());

dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('drag-over');
});

dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));

dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length) handleFile(e.target.files[0]);
});

function handleFile(file) {
    if (file.size > 50 * 1024 * 1024) {
        alert('File too large! Max 50MB allowed.');
        return;
    }
    selectedFile = file;
    uploadBtn.disabled = false;
    uploadBtn.querySelector('span').textContent = `Upload "${file.name}"`;
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function getFileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    const icons = {
        pdf: '📕', doc: '📘', docx: '📘', xls: '📗', xlsx: '📗',
        ppt: '📙', pptx: '📙', zip: '🗜️', rar: '🗜️',
        png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️',
        mp3: '🎵', mp4: '🎬', txt: '📄', csv: '📊',
        py: '🐍', js: '📜', html: '🌐', css: '🎨', json: '⚙️'
    };
    return icons[ext] || '📄';
}

uploadBtn.addEventListener('click', () => {
    if (!selectedFile) return;
    
    const formData = new FormData();
    formData.append('file', selectedFile);
    
    document.getElementById('fileName').textContent = selectedFile.name;
    document.getElementById('fileSize').textContent = formatSize(selectedFile.size);
    document.getElementById('fileIcon').textContent = getFileIcon(selectedFile.name);
    progressContainer.classList.add('active');
    uploadBtn.disabled = true;
    
    const xhr = new XMLHttpRequest();
    
    xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
            const percent = Math.round((e.loaded / e.total) * 100);
            progressFill.style.width = percent + '%';
            progressText.textContent = `Uploading... ${percent}%`;
        }
    });
    
    xhr.addEventListener('load', () => {
        if (xhr.status === 200) {
            const data = JSON.parse(xhr.responseText);
            progressFill.style.width = '100%';
            progressText.textContent = 'Complete! ✓';
            
            setTimeout(() => {
                progressContainer.classList.remove('active');
                uploadCard.style.display = 'none';
                resultCard.classList.add('active');
                shareLink.value = data.share_url;
                document.getElementById('resultFileName').textContent = 
                    data.filename.length > 25 ? data.filename.substring(0, 22) + '...' : data.filename;
                document.getElementById('resultFileSize').textContent = data.size;
            }, 600);
        } else {
            const err = JSON.parse(xhr.responseText || '{}');
            alert('Error: ' + (err.error || 'Upload failed'));
            progressContainer.classList.remove('active');
            uploadBtn.disabled = false;
        }
    });
    
    xhr.addEventListener('error', () => {
        alert('Upload failed. Please try again.');
        progressContainer.classList.remove('active');
        uploadBtn.disabled = false;
    });
    
    xhr.open('POST', '/upload');
    xhr.send(formData);
});

document.getElementById('copyBtn').addEventListener('click', async function() {
    try {
        await navigator.clipboard.writeText(shareLink.value);
        this.classList.add('copied');
        this.querySelector('span').textContent = 'Copied!';
        setTimeout(() => {
            this.classList.remove('copied');
            this.querySelector('span').textContent = 'Copy';
        }, 2000);
    } catch {
        shareLink.select();
        document.execCommand('copy');
    }
});

document.getElementById('newUploadBtn').addEventListener('click', () => {
    selectedFile = null;
    fileInput.value = '';
    uploadBtn.disabled = true;
    uploadBtn.querySelector('span').textContent = 'Upload & Generate Link';
    progressFill.style.width = '0%';
    resultCard.classList.remove('active');
    uploadCard.style.display = 'block';
});
