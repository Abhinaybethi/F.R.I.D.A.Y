# F.R.I.D.A.Y. Windows Environment Uninstall Script

Write-Host "========================================" -ForegroundColor Red
Write-Host " F.R.I.D.A.Y. Windows Uninstall Helper" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red

$confirmation = Read-Host "Are you sure you want to remove F.R.I.D.A.Y. virtual environment and logs? (y/N)"

if ($confirmation -eq "y" -or $confirmation -eq "Y") {
    if (Test-Path "venv") {
        Write-Host "Removing virtual environment 'venv'..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force venv
        Write-Host "[OK] Removed venv." -ForegroundColor Green
    }
    if (Test-Path "logs") {
        Write-Host "Cleaning log directory 'logs'..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force logs
        Write-Host "[OK] Cleaned logs." -ForegroundColor Green
    }
    Write-Host "`nF.R.I.D.A.Y. environment files uninstalled cleanly." -ForegroundColor Green
} else {
    Write-Host "`nUninstall cancelled." -ForegroundColor Yellow
}
