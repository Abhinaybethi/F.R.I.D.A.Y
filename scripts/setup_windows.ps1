# F.R.I.D.A.Y. Windows Environment Setup & Diagnostic Script

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " F.R.I.D.A.Y. Windows Setup & Verification" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Verify Python
Write-Host "`n[1/7] Verifying Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Python not found on PATH." -ForegroundColor Red
    exit 1
}

# 2. Verify Virtual Environment
Write-Host "`n[2/7] Checking Virtual Environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "[OK] Virtual environment 'venv' found." -ForegroundColor Green
} else {
    Write-Host "[INFO] Creating virtual environment 'venv'..." -ForegroundColor Yellow
    python -m venv venv
    Write-Host "[OK] Created venv." -ForegroundColor Green
}

# 3. Install Dependencies
Write-Host "`n[3/7] Installing Python dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Write-Host "[OK] Dependencies installed." -ForegroundColor Green

# 4. Verify Voice Models
Write-Host "`n[4/7] Verifying local voice models..." -ForegroundColor Yellow
if ((Test-Path "models/vad/silero_vad.onnx") -and (Test-Path "models/tts/piper/en_US-lessac-low.onnx")) {
    Write-Host "[OK] Local voice models found." -ForegroundColor Green
} else {
    Write-Host "[INFO] Downloading missing local voice models..." -ForegroundColor Yellow
    python main.py --download-models
    Write-Host "[OK] Models downloaded." -ForegroundColor Green
}

# 5. Verify Ollama
Write-Host "`n[5/7] Verifying Ollama service..." -ForegroundColor Yellow
try {
    $ollamaRes = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -Method Get -ErrorAction Stop
    Write-Host "[OK] Ollama server reachable at http://localhost:11434" -ForegroundColor Green
} catch {
    Write-Host "[WARNING] Ollama server not reachable at http://localhost:11434" -ForegroundColor Yellow
    Write-Host "         Please start Ollama service using: ollama serve" -ForegroundColor Yellow
}

# 6. Verify Audio Devices
Write-Host "`n[6/7] Verifying Audio Input/Output..." -ForegroundColor Yellow
python -c "import sounddevice as sd; print('[OK] Sounddevice output:', sd.query_devices())"

# 7. Run Health Diagnostics
Write-Host "`n[7/7] Running F.R.I.D.A.Y. Diagnostics..." -ForegroundColor Yellow
python main.py --diagnostics

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Setup Complete! Start Friday with: python main.py" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
