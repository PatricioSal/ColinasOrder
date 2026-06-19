# ============================================================
#  WhatsApp Order Bot - Automated Setup Helper
#  This script is designed to run elevated to handle installations.
# ============================================================

$ErrorActionPreference = "Continue"

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "         WhatsApp Order Bot - Automated Setup" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""

# Helper to refresh current environment PATH variables from registry
function Refresh-Path {
    Write-Host "Refreshing environment paths..." -ForegroundColor Cyan
    $sysPath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $usrPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$sysPath;$usrPath"
}

# Helper to find Python executable
function Get-PythonPath {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { return "py" }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return "python" }

    # Fallback to local app data installation
    $localAppData = [System.Environment]::GetFolderPath("LocalApplicationData")
    $pyPath = Get-ChildItem -Path "$localAppData\Programs\Python" -Filter "Python3*" -ErrorAction SilentlyContinue | 
              Sort-Object Name -Descending | Select-Object -First 1
    if ($pyPath) {
        $exe = Join-Path $pyPath.FullName "python.exe"
        if (Test-Path $exe) { return $exe }
    }
    
    # Fallback to Program Files
    $programFilesPy = Get-ChildItem -Path "C:\Program Files\Python3*" -ErrorAction SilentlyContinue | 
                      Sort-Object Name -Descending | Select-Object -First 1
    if ($programFilesPy) {
        $exe = Join-Path $programFilesPy.FullName "python.exe"
        if (Test-Path $exe) { return $exe }
    }

    return $null
}

# Helper to find Node.js executable
function Get-NodePath {
    $cmd = Get-Command node -ErrorAction SilentlyContinue
    if ($cmd) { return "node" }
    if (Test-Path "C:\Program Files\nodejs\node.exe") { return "C:\Program Files\nodejs\node.exe" }
    return $null
}

# Helper to find npm executable
function Get-NpmPath {
    $cmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($cmd) { return "npm" }
    if (Test-Path "C:\Program Files\nodejs\npm.cmd") { return "C:\Program Files\nodejs\npm.cmd" }
    return $null
}

try {
    # --- 1. Verify winget Availability ---
    $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $wingetCheck) {
        Write-Host "[!] Windows Package Manager (winget) is not installed or available on this PC." -ForegroundColor Red
        Write-Host "    Please ensure you are running Windows 10/11 and have the App Installer installed." -ForegroundColor Red
        Write-Host "    You may need to download dependencies manually as listed in SETUP.md." -ForegroundColor Red
        Write-Host ""
        Read-Host "Press Enter to exit..."
        exit
    }

    # --- 2. Check/Install Python ---
    Refresh-Path
    $pyExe = Get-PythonPath
    if ($pyExe) {
        Write-Host "[OK] Python is already installed." -ForegroundColor Green
    } else {
        Write-Host "[ ] Python not detected. Installing via winget..." -ForegroundColor Yellow
        winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        $pyExe = Get-PythonPath
        if ($pyExe) {
            Write-Host "[OK] Python installed successfully!" -ForegroundColor Green
        } else {
            Write-Host "[!] Python installation could not be completed automatically. Please download it from https://www.python.org/downloads/." -ForegroundColor Red
        }
    }

    # --- 3. Check/Install Node.js ---
    Refresh-Path
    $nodeExe = Get-NodePath
    if ($nodeExe) {
        Write-Host "[OK] Node.js is already installed." -ForegroundColor Green
    } else {
        Write-Host "[ ] Node.js not detected. Installing via winget..." -ForegroundColor Yellow
        winget install --id OpenJS.NodeJS -e --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        $nodeExe = Get-NodePath
        if ($nodeExe) {
            Write-Host "[OK] Node.js installed successfully!" -ForegroundColor Green
        } else {
            Write-Host "[!] Node.js installation could not be completed automatically. Please download it from https://nodejs.org/." -ForegroundColor Red
        }
    }

    # --- Check/Install Git ---
    Refresh-Path
    $gitCheck = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCheck) {
        Write-Host "[OK] Git is already installed." -ForegroundColor Green
    } else {
        Write-Host "[ ] Git not detected. Installing via winget..." -ForegroundColor Yellow
        winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        $gitCheck = Get-Command git -ErrorAction SilentlyContinue
        if ($gitCheck) {
            Write-Host "[OK] Git installed successfully!" -ForegroundColor Green
        } else {
            Write-Host "[!] Git installation could not be completed automatically. Please download it from https://git-scm.com/." -ForegroundColor Red
        }
    }

    # --- 4. Check/Install ODBC Driver 18 for SQL Server ---
    Write-Host "[ ] Ensuring ODBC Driver 18 for SQL Server is installed..." -ForegroundColor Yellow
    winget install --id Microsoft.ODBCDriverForSQLServer -e --silent --accept-package-agreements --accept-source-agreements
    Write-Host "[OK] ODBC Driver 18 checked/installed." -ForegroundColor Green

    # --- 5. Check/Install PostgreSQL ---
    $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
    if ($pgService) {
        Write-Host "[OK] PostgreSQL is already installed and registered (Service: $($pgService.Name))." -ForegroundColor Green
    } else {
        Write-Host "[ ] PostgreSQL service not found. Starting PostgreSQL installer via winget..." -ForegroundColor Yellow
        Write-Host "    ----------------------------------------------------------------------------------" -ForegroundColor Cyan
        Write-Host "    IMPORTANT: An interactive PostgreSQL setup window will open." -ForegroundColor Cyan
        Write-Host "    - Choose the default installation path, components, and ports (5432)." -ForegroundColor Cyan
        Write-Host "    - When prompted for a password, enter 'openpgpwd' (or note what you enter and update" -ForegroundColor Cyan
        Write-Host "      your .env file with the password later)." -ForegroundColor Cyan
        Write-Host "    ----------------------------------------------------------------------------------" -ForegroundColor Cyan
        winget install --id PostgreSQL.PostgreSQL -e --interactive --accept-package-agreements --accept-source-agreements
        Write-Host "[OK] PostgreSQL setup initiated/finished." -ForegroundColor Green
    }

    # --- 6. Set up `.env` File ---
    $repoRoot = Split-Path $PSScriptRoot -Parent
    $envPath = Join-Path $repoRoot ".env"
    $examplePath = Join-Path $PSScriptRoot ".env.example"
    if (-not (Test-Path $envPath)) {
        if (Test-Path $examplePath) {
            Write-Host "[ ] Creating default .env file from template..." -ForegroundColor Yellow
            Copy-Item -Path $examplePath -Destination $envPath
            Write-Host "[OK] .env file created." -ForegroundColor Green
        } else {
            Write-Host "[!] .env.example template not found. Cannot create default .env." -ForegroundColor Red
        }
    } else {
        Write-Host "[OK] .env file already exists." -ForegroundColor Green
    }

    # --- 7. Install Python Dependencies ---
    Refresh-Path
    $pyExe = Get-PythonPath
    if ($pyExe) {
        Write-Host "[ ] Installing Python dependencies from requirements.txt..." -ForegroundColor Yellow
        & $pyExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Python dependencies installed successfully." -ForegroundColor Green
        } else {
            Write-Host "[!] Failed to install Python dependencies. You may need to run 'pip install -r requirements.txt' manually." -ForegroundColor Red
        }
    } else {
        Write-Host "[x] Cannot install Python dependencies because Python was not found in PATH." -ForegroundColor Red
    }

    # --- 8. Install Node.js Dependencies ---
    Refresh-Path
    $npmCmd = Get-NpmPath
    if ($npmCmd) {
        Write-Host "[ ] Installing Node.js dependencies from package.json..." -ForegroundColor Yellow
        Push-Location $PSScriptRoot
        $env:PUPPETEER_SKIP_DOWNLOAD = "true"
        & $npmCmd install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[!] npm install failed. Attempting clean install (removing package-lock.json)..." -ForegroundColor Yellow
            $lockFile = Join-Path $PSScriptRoot "package-lock.json"
            if (Test-Path $lockFile) {
                Remove-Item -Path $lockFile -Force -ErrorAction SilentlyContinue
            }
            $nodeModules = Join-Path $PSScriptRoot "node_modules"
            if (Test-Path $nodeModules) {
                Remove-Item -Path $nodeModules -Recurse -Force -ErrorAction SilentlyContinue
            }
            & $npmCmd install --no-audit --no-fund
        }
        $env:PUPPETEER_SKIP_DOWNLOAD = $null
        Pop-Location
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Node.js dependencies installed successfully." -ForegroundColor Green
        } else {
            Write-Host "[!] Failed to install Node.js dependencies. You may need to run 'npm install' manually." -ForegroundColor Red
        }
    } else {
        Write-Host "[x] Cannot install Node.js dependencies because npm/node was not found in PATH." -ForegroundColor Red
    }

    # --- 9. Run Database Setup Script ---
    Refresh-Path
    $pyExe = Get-PythonPath
    if ($pyExe) {
        Write-Host "[ ] Initializing database tables and syncing data..." -ForegroundColor Yellow
        Write-Host "    (Make sure PostgreSQL is running. If this is a fresh PostgreSQL install, you may need" -ForegroundColor Yellow
        Write-Host "     to create the database 'whatsapp_orders' or ensure the superuser credentials match your .env)" -ForegroundColor Yellow
        & $pyExe (Join-Path $PSScriptRoot "db_setup.py")
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Database setup and sync completed successfully." -ForegroundColor Green
        } else {
            Write-Host "[!] Database initialization failed. If PostgreSQL was just installed, please restart your computer" -ForegroundColor Red
            Write-Host "    and run: py src\db_setup.py manually." -ForegroundColor Red
        }
    }

    # --- 10. Create Desktop Shortcut ---
    Write-Host "[ ] Creating Desktop shortcut..." -ForegroundColor Yellow
    if (Test-Path (Join-Path $PSScriptRoot "create_shortcut.bat")) {
        & cmd.exe /c (Join-Path $PSScriptRoot "create_shortcut.bat")
    } else {
        Write-Host "[x] create_shortcut.bat not found." -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host " Setup complete! Double-click 'SAPI_WATCHER' on your" -ForegroundColor Green
    Write-Host " Desktop to start the application." -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "[!] Setup encountered a critical error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    Details: $($_)" -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "Press Enter to close this window..."
}

