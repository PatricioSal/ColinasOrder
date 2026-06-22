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
    # IMPORTANT: We must actually RUN python to check, because Windows 10/11
    # has fake "app aliases" (python.exe, python3.exe) that point to the
    # Microsoft Store and fool Get-Command / where.exe.

    # Try 'py' launcher first
    try {
        $result = & py --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $result -match 'Python 3') { return "py" }
    } catch {}

    # Try 'python' on PATH (but verify it actually runs)
    try {
        $result = & python --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $result -match 'Python 3') { return "python" }
    } catch {}

    # Fallback: search common install directories
    $localAppData = [System.Environment]::GetFolderPath("LocalApplicationData")
    $searchPaths = @(
        "$localAppData\Programs\Python",
        "C:\Program Files\Python3*",
        "C:\Python3*"
    )
    foreach ($basePath in $searchPaths) {
        $pyDirs = Get-ChildItem -Path $basePath -Filter "Python3*" -Directory -ErrorAction SilentlyContinue |
                  Sort-Object Name -Descending
        foreach ($d in $pyDirs) {
            $exe = Join-Path $d.FullName "python.exe"
            if (Test-Path $exe) {
                # Verify it actually works
                try {
                    $result = & $exe --version 2>&1
                    if ($LASTEXITCODE -eq 0) { return $exe }
                } catch {}
            }
        }
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

    # --- 2. Disable Windows Store app aliases for Python ---
    # These fake stubs fool 'where python' and prevent real Python from running
    Write-Host "[ ] Disabling Windows Store Python app aliases..." -ForegroundColor Yellow
    $aliasDir = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
    foreach ($alias in @("python.exe", "python3.exe")) {
        $aliasPath = Join-Path $aliasDir $alias
        if (Test-Path $aliasPath) {
            try {
                Remove-Item $aliasPath -Force -ErrorAction Stop
                Write-Host "    Removed app alias: $alias" -ForegroundColor Cyan
            } catch {
                Write-Host "    Could not remove $alias alias (non-critical)." -ForegroundColor Yellow
            }
        }
    }

    # --- 3. Check/Install Python ---
    Refresh-Path
    $pyExe = Get-PythonPath
    if ($pyExe) {
        Write-Host "[OK] Python is already installed ($pyExe)." -ForegroundColor Green
    } else {
        Write-Host "[ ] Python not detected. Installing via winget..." -ForegroundColor Yellow
        winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
        
        # Add Python to PATH immediately so it's available for the rest of this script
        $localAppData = [System.Environment]::GetFolderPath("LocalApplicationData")
        $pyDir = Get-ChildItem -Path "$localAppData\Programs\Python" -Filter "Python3*" -Directory -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending | Select-Object -First 1
        if ($pyDir) {
            $pyBin = $pyDir.FullName
            $pyScripts = Join-Path $pyBin "Scripts"
            $currentPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
            if ($currentPath -notlike "*$pyBin*") {
                [System.Environment]::SetEnvironmentVariable("Path", "$pyBin;$pyScripts;$currentPath", "User")
                Write-Host "    Added Python to user PATH." -ForegroundColor Cyan
            }
        }
        
        Refresh-Path
        $pyExe = Get-PythonPath
        if ($pyExe) {
            Write-Host "[OK] Python installed successfully ($pyExe)!" -ForegroundColor Green
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

    # --- 4. Check/Install ODBC Driver for SQL Server ---
    # Detect if any ODBC driver for SQL Server is already installed
    $installedDriver = Get-OdbcDriver -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*SQL Server*' -and $_.Name -match 'ODBC Driver \d+' } | Sort-Object Name -Descending | Select-Object -First 1
    if ($installedDriver) {
        Write-Host "[OK] $($installedDriver.Name) is already installed." -ForegroundColor Green
    } else {
        Write-Host "[ ] ODBC Driver for SQL Server not found. Installing..." -ForegroundColor Yellow
        # Try Driver 18 first, then Driver 17
        $installed = $false
        foreach ($driverId in @('Microsoft.ODBCDriver18ForSQLServer', 'Microsoft.ODBCDriver17ForSQLServer')) {
            Write-Host "    Trying winget ID: $driverId ..." -ForegroundColor Cyan
            winget install --id $driverId -e --silent --accept-package-agreements --accept-source-agreements 2>$null
            if ($LASTEXITCODE -eq 0) { $installed = $true; break }
        }
        if (-not $installed) {
            Write-Host "    Winget install failed. Downloading ODBC Driver 18 directly..." -ForegroundColor Yellow
            $msiUrl = "https://go.microsoft.com/fwlink/?linkid=2266337"
            $msiPath = Join-Path $env:TEMP "msodbcsql18.msi"
            try {
                Invoke-WebRequest -Uri $msiUrl -OutFile $msiPath -UseBasicParsing
                Start-Process msiexec.exe -ArgumentList "/i `"$msiPath`" /passive /norestart IACCEPTMSODBCSQLLICENSETERMS=YES" -Wait
                Write-Host "[OK] ODBC Driver installed from direct download." -ForegroundColor Green
            } catch {
                Write-Host "[!] Could not install ODBC Driver automatically. Please download from:" -ForegroundColor Red
                Write-Host "    https://go.microsoft.com/fwlink/?linkid=2266337" -ForegroundColor Yellow
            }
        } else {
            Write-Host "[OK] ODBC Driver installed via winget." -ForegroundColor Green
        }
        $installedDriver = Get-OdbcDriver -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*SQL Server*' -and $_.Name -match 'ODBC Driver \d+' } | Sort-Object Name -Descending | Select-Object -First 1
    }

    # Auto-update .env to match whichever ODBC driver version is installed
    $repoRoot = Split-Path $PSScriptRoot -Parent
    $envPath = Join-Path $repoRoot ".env"
    if ($installedDriver -and (Test-Path $envPath)) {
        $driverName = $installedDriver.Name
        Write-Host "[ ] Updating .env to use '$driverName'..." -ForegroundColor Yellow
        $content = Get-Content $envPath -Raw
        $content = $content -replace 'ODBC Driver \d+ for SQL Server', $driverName
        Set-Content $envPath $content -NoNewline
        Write-Host "[OK] .env updated to use $driverName." -ForegroundColor Green
    }

    # --- 5. Check/Install PostgreSQL ---
    $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
    if ($pgService) {
        Write-Host "[OK] PostgreSQL is already installed and registered (Service: $($pgService.Name))." -ForegroundColor Green
    } else {
        Write-Host "----------------------------------------------------------" -ForegroundColor Yellow
        Write-Host "           PostgreSQL Interactive Setup Guidance" -ForegroundColor Yellow
        Write-Host "----------------------------------------------------------" -ForegroundColor Yellow
        Write-Host "The PostgreSQL database installer is about to download. Since this" -ForegroundColor Cyan
        Write-Host "requires administrative/user configurations, a graphical window will" -ForegroundColor Cyan
        Write-Host "open once the download is complete." -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Please follow these exact steps in the setup window:" -ForegroundColor White
        Write-Host "  1. Click 'Next' on the Welcome screen." -ForegroundColor White
        Write-Host "  2. Installation Directory: Keep default and click 'Next'." -ForegroundColor White
        Write-Host "  3. Select Components: Keep all checked and click 'Next'." -ForegroundColor White
        Write-Host "  4. Data Directory: Keep default and click 'Next'." -ForegroundColor White
        Write-Host "  5. Password: Choose a secure password (e.g., 'openpgpwd' or a custom one)." -ForegroundColor White
        Write-Host "     **WRITE DOWN THIS PASSWORD** - you will enter it later in this script." -ForegroundColor Yellow
        Write-Host "  6. Port: Keep default '5432' and click 'Next'." -ForegroundColor White
        Write-Host "  7. Advanced Options: Keep default Locale and click 'Next'." -ForegroundColor White
        Write-Host "  8. Click 'Next' to start the installation." -ForegroundColor White
        Write-Host "  9. Finish: Uncheck 'Launch Stack Builder' and click 'Finish'." -ForegroundColor White
        Write-Host "----------------------------------------------------------" -ForegroundColor Yellow
        Write-Host ""
        
        Read-Host "Press Enter to start downloading and open the installer..."
        Write-Host ""
        Write-Host "[ ] Downloading and starting PostgreSQL installer (this may take a few minutes)..." -ForegroundColor Yellow
        
        # Execute winget install. PowerShell will wait synchronously for it to finish.
        winget install --id PostgreSQL.PostgreSQL -e --interactive --accept-package-agreements --accept-source-agreements
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] PostgreSQL setup completed successfully!" -ForegroundColor Green
        } else {
            Write-Host "[!] PostgreSQL installer closed or failed (Exit code: $LASTEXITCODE)." -ForegroundColor Red
        }
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

    # --- 6.1 Configure Database Credentials ---
    Write-Host ""
    Write-Host "----------------------------------------------------------" -ForegroundColor Cyan
    Write-Host "            PostgreSQL Database Configuration" -ForegroundColor Cyan
    Write-Host "----------------------------------------------------------" -ForegroundColor Cyan
    
    # Check if we can parse DB_USER and DB_PASSWORD from current .env
    $dbUser = "postgres"
    $dbPassword = ""
    if (Test-Path $envPath) {
        $envContent = Get-Content $envPath
        foreach ($line in $envContent) {
            if ($line -match '^DB_USER=(.*)') { $dbUser = $Matches[1].Trim() }
            if ($line -match '^DB_PASSWORD=(.*)') { $dbPassword = $Matches[1].Trim() }
        }
    }

    $dbConnectionOk = $false
    $pyExe = Get-PythonPath
    if ($pyExe -and $dbUser -and $dbPassword) {
        Write-Host "[ ] Testing database connection with user '$dbUser'..." -ForegroundColor Yellow
        $testCommand = "import psycopg2; psycopg2.connect(host='localhost', port=5432, user='$dbUser', password='$dbPassword', database='postgres').close(); print('OK')"
        $testResult = & $pyExe -c $testCommand 2>$null
        if ($testResult -eq "OK") {
            $dbConnectionOk = $true
            Write-Host "[OK] Connection to PostgreSQL successful using user '$dbUser'!" -ForegroundColor Green
        } else {
            Write-Host "[!] Connection failed with user '$dbUser'." -ForegroundColor Yellow
        }
    }

    if (-not $dbConnectionOk) {
        # Prompt the user for the password
        Write-Host "Please enter the password for the PostgreSQL user (e.g. 'openpgpwd'):" -ForegroundColor Yellow
        $inputUser = Read-Host "Database Username (default: $dbUser)"
        if (-not $inputUser) { $inputUser = $dbUser }
        
        $inputPwd = Read-Host "Database Password"
        if (-not $inputPwd) { $inputPwd = "openpgpwd" }

        # Dynamically update the credentials in .env
        if (Test-Path $envPath) {
            $content = Get-Content $envPath
            $content = $content -replace '^DB_USER=.*', "DB_USER=$inputUser"
            $content = $content -replace '^DB_PASSWORD=.*', "DB_PASSWORD=$inputPwd"
            $content | Set-Content $envPath
            Write-Host "[OK] Database credentials updated in .env." -ForegroundColor Green
            
            if ($pyExe) {
                Write-Host "[ ] Verifying connection with new credentials..." -ForegroundColor Yellow
                $testCommand = "import psycopg2; psycopg2.connect(host='localhost', port=5432, user='$inputUser', password='$inputPwd', database='postgres').close(); print('OK')"
                $testResult = & $pyExe -c $testCommand 2>$null
                if ($testResult -eq "OK") {
                    Write-Host "[OK] Database connection verified successfully!" -ForegroundColor Green
                } else {
                    Write-Host "[WARNING] Database connection test failed with the new credentials. Please double check PostgreSQL is running." -ForegroundColor Yellow
                }
            }
        } else {
            Write-Host "[x] Could not update database credentials because .env does not exist." -ForegroundColor Red
        }
    }

    # --- 6.2 Ensure PostgreSQL Service is Running ---
    Write-Host ""
    Write-Host "[ ] Checking PostgreSQL service status..." -ForegroundColor Yellow
    $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
    if ($pgService) {
        if ($pgService.Status -ne "Running") {
            Write-Host "[ ] Starting PostgreSQL service ($($pgService.Name))..." -ForegroundColor Yellow
            Start-Service $pgService.Name -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        }
        Write-Host "[OK] PostgreSQL database service is running." -ForegroundColor Green
    } else {
        Write-Host "[!] PostgreSQL service was not found. If you just installed it, you may need to restart the computer." -ForegroundColor Red
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
    $hasNpm = Get-Command npm -ErrorAction SilentlyContinue
    if ($hasNpm -or (Test-Path "C:\Program Files\nodejs\npm.cmd")) {
        Write-Host "[ ] Installing Node.js dependencies from package.json..." -ForegroundColor Yellow
        Push-Location $PSScriptRoot
        $env:PUPPETEER_SKIP_DOWNLOAD = "true"
        if ($hasNpm) {
            npm install --no-audit --no-fund
        } else {
            & "C:\Program Files\nodejs\npm.cmd" install --no-audit --no-fund
        }
        
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
            if ($hasNpm) {
                npm install --no-audit --no-fund
            } else {
                & "C:\Program Files\nodejs\npm.cmd" install --no-audit --no-fund
            }
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

