# F.R.I.D.A.Y. Windows Environment Update Script

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " F.R.I.D.A.Y. Windows Update & Verify" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Update Dependencies
Write-Host "`n[1/3] Updating Python dependencies..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Write-Host "[OK] Dependencies updated." -ForegroundColor Green

# 2. Check Voice Models
Write-Host "`n[2/3] Verifying voice models..." -ForegroundColor Yellow
python main.py --models

# 3. Run Health Diagnostics
Write-Host "`n[3/3] Running Diagnostics..." -ForegroundColor Yellow
python main.py --diagnostics

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " Update Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
