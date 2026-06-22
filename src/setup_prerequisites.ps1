# ============================================================
#  WhatsApp Order Bot - Automated Setup Helper
#  This script is designed to run elevated to handle installations.
#
#  It installs: Git, Python 3.12, Node.js, ODBC Driver, PostgreSQL
#  Then: creates .env, installs pip/npm deps, runs db_setup,
#        connects folder to GitHub for future updates,
#        and creates a Desktop shortcut.
# ============================================================

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "         WhatsApp Order Bot - Automated Setup" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ""

# ── Resolve repo root (one level up from src/) ──────────────────────────────
$repoRoot = Split-Path $PSScriptRoot -Parent
$envPath  = Join-Path $repoRoot ".env"
$examplePath = Join-Path $PSScriptRoot ".env.example"

# ══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

function Refresh-Path {
    $sysPath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $usrPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$sysPath;$usrPath"
}

function Get-PythonPath {
    # Must actually RUN python to check — Windows Store app aliases fool
    # Get-Command and where.exe but fail when executed.
    try {
        $result = & py --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $result -match 'Python 3') { return "py" }
    } catch {}

    try {
        $result = & python --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $result -match 'Python 3') { return "python" }
    } catch {}

    # Search common install directories
    $localAppData = [System.Environment]::GetFolderPath("LocalApplicationData")
    $searchRoots = @(
        "$localAppData\Programs\Python",
        "C:\Program Files",
        "C:\"
    )
    foreach ($root in $searchRoots) {
        $pyDirs = Get-ChildItem -Path $root -Filter "Python3*" -Directory -ErrorAction SilentlyContinue |
                  Sort-Object Name -Descending
        foreach ($d in $pyDirs) {
            $exe = Join-Path $d.FullName "python.exe"
            if (Test-Path $exe) {
                try {
                    $result = & $exe --version 2>&1
                    if ($LASTEXITCODE -eq 0) { return $exe }
                } catch {}
            }
        }
    }
    return $null
}

function Get-NodePath {
    try {
        $result = & node --version 2>&1
        if ($LASTEXITCODE -eq 0) { return "node" }
    } catch {}
    if (Test-Path "C:\Program Files\nodejs\node.exe") { return "C:\Program Files\nodejs\node.exe" }
    return $null
}

function Get-NpmPath {
    $cmd = Get-Command npm -ErrorAction SilentlyContinue
    if ($cmd) { return "npm" }
    if (Test-Path "C:\Program Files\nodejs\npm.cmd") { return "C:\Program Files\nodejs\npm.cmd" }
    return $null
}

function Get-GitPath {
    try {
        $result = & git --version 2>&1
        if ($LASTEXITCODE -eq 0) { return "git" }
    } catch {}
    if (Test-Path "C:\Program Files\Git\bin\git.exe") { return "C:\Program Files\Git\bin\git.exe" }
    return $null
}

# ══════════════════════════════════════════════════════════════════════════════
# MAIN SETUP
# ══════════════════════════════════════════════════════════════════════════════

try {

    # ── STEP 1: Verify winget ─────────────────────────────────────────────────
    Write-Host "[1/11] Checking Windows Package Manager (winget)..." -ForegroundColor Cyan
    $hasWinget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $hasWinget) {
        Write-Host "  [!] winget is not available. Trying to register App Installer..." -ForegroundColor Yellow
        try {
            Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe -ErrorAction Stop
            $hasWinget = Get-Command winget -ErrorAction SilentlyContinue
        } catch {}
    }
    if ($hasWinget) {
        Write-Host "  [OK] winget is available." -ForegroundColor Green
    } else {
        Write-Host "  [!] winget not found. Will attempt direct downloads for missing software." -ForegroundColor Yellow
    }

    # ── STEP 2: Disable Windows Store Python aliases ──────────────────────────
    Write-Host "[2/11] Disabling Windows Store Python app aliases..." -ForegroundColor Cyan
    $aliasDir = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
    foreach ($alias in @("python.exe", "python3.exe")) {
        $aliasPath = Join-Path $aliasDir $alias
        if (Test-Path $aliasPath) {
            try {
                Remove-Item $aliasPath -Force -ErrorAction Stop
                Write-Host "  Removed fake alias: $alias" -ForegroundColor Yellow
            } catch {
                Write-Host "  Could not remove $alias alias (non-critical)." -ForegroundColor DarkGray
            }
        }
    }

    # ── STEP 3: Install Git ───────────────────────────────────────────────────
    Write-Host "[3/11] Checking Git..." -ForegroundColor Cyan
    Refresh-Path
    $gitExe = Get-GitPath
    if ($gitExe) {
        Write-Host "  [OK] Git is installed." -ForegroundColor Green
    } else {
        Write-Host "  [ ] Installing Git..." -ForegroundColor Yellow
        if ($hasWinget) {
            winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
        } else {
            # Direct download
            $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe"
            $gitInstaller = Join-Path $env:TEMP "git-installer.exe"
            Write-Host "  Downloading Git installer..." -ForegroundColor Yellow
            Invoke-WebRequest -Uri $gitUrl -OutFile $gitInstaller -UseBasicParsing
            Start-Process -FilePath $gitInstaller -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS=`"icons,ext\reg\shellhere,assoc,assoc_sh`"" -Wait
        }
        # Add Git to PATH for this session
        if (Test-Path "C:\Program Files\Git\bin") {
            $env:Path = "C:\Program Files\Git\bin;$env:Path"
        }
        Refresh-Path
        $gitExe = Get-GitPath
        if ($gitExe) {
            Write-Host "  [OK] Git installed successfully!" -ForegroundColor Green
        } else {
            Write-Host "  [!] Git install may need a restart to take effect." -ForegroundColor Yellow
        }
    }

    # ── STEP 4: Install Python ────────────────────────────────────────────────
    Write-Host "[4/11] Checking Python..." -ForegroundColor Cyan
    Refresh-Path
    $pyExe = Get-PythonPath
    if ($pyExe) {
        Write-Host "  [OK] Python is installed ($pyExe)." -ForegroundColor Green
    } else {
        Write-Host "  [ ] Installing Python 3.12..." -ForegroundColor Yellow
        if ($hasWinget) {
            winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
        } else {
            $pyUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
            $pyInstaller = Join-Path $env:TEMP "python-installer.exe"
            Write-Host "  Downloading Python installer..." -ForegroundColor Yellow
            Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing
            Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1" -Wait
        }
        # Add to PATH immediately
        $localAppData = [System.Environment]::GetFolderPath("LocalApplicationData")
        $pyDir = Get-ChildItem -Path "$localAppData\Programs\Python" -Filter "Python3*" -Directory -ErrorAction SilentlyContinue |
                 Sort-Object Name -Descending | Select-Object -First 1
        if ($pyDir) {
            $pyBin = $pyDir.FullName
            $pyScripts = Join-Path $pyBin "Scripts"
            $currentPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
            if ($currentPath -notlike "*$pyBin*") {
                [System.Environment]::SetEnvironmentVariable("Path", "$pyBin;$pyScripts;$currentPath", "User")
                Write-Host "  Added Python to user PATH." -ForegroundColor Yellow
            }
            $env:Path = "$pyBin;$pyScripts;$env:Path"
        }
        Refresh-Path
        $pyExe = Get-PythonPath
        if ($pyExe) {
            Write-Host "  [OK] Python installed successfully ($pyExe)!" -ForegroundColor Green
        } else {
            Write-Host "  [!] Python install failed. Please download manually from https://www.python.org/downloads/" -ForegroundColor Red
        }
    }

    # ── STEP 5: Install Node.js ───────────────────────────────────────────────
    Write-Host "[5/11] Checking Node.js..." -ForegroundColor Cyan
    Refresh-Path
    $nodeExe = Get-NodePath
    if ($nodeExe) {
        Write-Host "  [OK] Node.js is installed." -ForegroundColor Green
    } else {
        Write-Host "  [ ] Installing Node.js..." -ForegroundColor Yellow
        if ($hasWinget) {
            winget install --id OpenJS.NodeJS -e --silent --accept-package-agreements --accept-source-agreements
        } else {
            $nodeUrl = "https://nodejs.org/dist/v22.12.0/node-v22.12.0-x64.msi"
            $nodeMsi = Join-Path $env:TEMP "node-installer.msi"
            Write-Host "  Downloading Node.js installer..." -ForegroundColor Yellow
            Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeMsi -UseBasicParsing
            Start-Process msiexec.exe -ArgumentList "/i `"$nodeMsi`" /passive /norestart" -Wait
        }
        # Add to PATH for this session
        if (Test-Path "C:\Program Files\nodejs") {
            $env:Path = "C:\Program Files\nodejs;$env:Path"
        }
        Refresh-Path
        $nodeExe = Get-NodePath
        if ($nodeExe) {
            Write-Host "  [OK] Node.js installed successfully!" -ForegroundColor Green
        } else {
            Write-Host "  [!] Node.js install failed. Please download manually from https://nodejs.org/" -ForegroundColor Red
        }
    }

    # ── STEP 6: Install ODBC Driver for SQL Server ────────────────────────────
    Write-Host "[6/11] Checking ODBC Driver for SQL Server..." -ForegroundColor Cyan
    $installedDriver = Get-OdbcDriver -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like '*SQL Server*' -and $_.Name -match 'ODBC Driver \d+' } |
        Sort-Object Name -Descending | Select-Object -First 1

    if ($installedDriver) {
        Write-Host "  [OK] $($installedDriver.Name) is installed." -ForegroundColor Green
    } else {
        Write-Host "  [ ] Installing ODBC Driver..." -ForegroundColor Yellow
        $driverInstalled = $false

        # Try winget with both IDs
        if ($hasWinget) {
            foreach ($driverId in @('Microsoft.ODBCDriver18ForSQLServer', 'Microsoft.ODBCDriver17ForSQLServer')) {
                Write-Host "    Trying: $driverId ..." -ForegroundColor DarkGray
                winget install --id $driverId -e --silent --accept-package-agreements --accept-source-agreements 2>$null
                if ($LASTEXITCODE -eq 0) { $driverInstalled = $true; break }
            }
        }
        # Fallback: direct MSI download
        if (-not $driverInstalled) {
            Write-Host "    Downloading ODBC Driver 18 directly..." -ForegroundColor Yellow
            $msiUrl = "https://go.microsoft.com/fwlink/?linkid=2266337"
            $msiPath = Join-Path $env:TEMP "msodbcsql18.msi"
            try {
                Invoke-WebRequest -Uri $msiUrl -OutFile $msiPath -UseBasicParsing
                Start-Process msiexec.exe -ArgumentList "/i `"$msiPath`" /passive /norestart IACCEPTMSODBCSQLLICENSETERMS=YES" -Wait
                $driverInstalled = $true
            } catch {
                Write-Host "  [!] Could not install ODBC Driver. Download manually:" -ForegroundColor Red
                Write-Host "      https://go.microsoft.com/fwlink/?linkid=2266337" -ForegroundColor Yellow
            }
        }
        if ($driverInstalled) {
            Write-Host "  [OK] ODBC Driver installed." -ForegroundColor Green
        }
        # Re-detect
        $installedDriver = Get-OdbcDriver -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like '*SQL Server*' -and $_.Name -match 'ODBC Driver \d+' } |
            Sort-Object Name -Descending | Select-Object -First 1
    }

    # ── STEP 7: Install PostgreSQL ────────────────────────────────────────────
    Write-Host "[7/11] Checking PostgreSQL..." -ForegroundColor Cyan
    $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
    if ($pgService) {
        Write-Host "  [OK] PostgreSQL is installed (Service: $($pgService.Name))." -ForegroundColor Green
        # Make sure it's running
        if ($pgService.Status -ne "Running") {
            Write-Host "  [ ] Starting PostgreSQL service..." -ForegroundColor Yellow
            Start-Service $pgService.Name -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        }
    } else {
        Write-Host ""
        Write-Host "  ┌──────────────────────────────────────────────────────────┐" -ForegroundColor Yellow
        Write-Host "  │          PostgreSQL Interactive Setup                    │" -ForegroundColor Yellow
        Write-Host "  └──────────────────────────────────────────────────────────┘" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  A graphical installer window will open." -ForegroundColor White
        Write-Host "  Just click NEXT on everything, except:" -ForegroundColor White
        Write-Host ""
        Write-Host "    Step 5 - Password: type 'openpgpwd' (or your own)" -ForegroundColor White
        Write-Host "    Last step: UNCHECK 'Launch Stack Builder', click Finish" -ForegroundColor White
        Write-Host ""
        Write-Host "    *** REMEMBER YOUR PASSWORD ***" -ForegroundColor Yellow
        Write-Host ""

        Read-Host "  Press ENTER to open the PostgreSQL installer"
        Write-Host ""
        Write-Host "  [ ] Downloading and installing PostgreSQL..." -ForegroundColor Yellow

        if ($hasWinget) {
            winget install --id PostgreSQL.PostgreSQL -e --interactive --accept-package-agreements --accept-source-agreements
        } else {
            $pgUrl = "https://get.enterprisedb.com/postgresql/postgresql-16.6-1-windows-x64.exe"
            $pgInstaller = Join-Path $env:TEMP "postgresql-installer.exe"
            Invoke-WebRequest -Uri $pgUrl -OutFile $pgInstaller -UseBasicParsing
            Start-Process -FilePath $pgInstaller -Wait
        }

        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] PostgreSQL setup completed!" -ForegroundColor Green
        } else {
            Write-Host "  [!] PostgreSQL installer closed with code $LASTEXITCODE." -ForegroundColor Yellow
        }

        # Ensure the service is running after install
        Start-Sleep -Seconds 3
        $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
        if ($pgService -and $pgService.Status -ne "Running") {
            Start-Service $pgService.Name -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        }
    }

    # ── STEP 8: Create .env and configure database credentials ────────────────
    Write-Host "[8/11] Configuring environment (.env)..." -ForegroundColor Cyan

    # Create .env from template if it doesn't exist
    if (-not (Test-Path $envPath)) {
        if (Test-Path $examplePath) {
            Copy-Item -Path $examplePath -Destination $envPath
            Write-Host "  [OK] Created .env from template." -ForegroundColor Green
        } else {
            Write-Host "  [!] .env.example not found — cannot create .env." -ForegroundColor Red
        }
    } else {
        Write-Host "  [OK] .env already exists." -ForegroundColor Green
    }

    # Auto-update .env to match installed ODBC driver version
    if ($installedDriver -and (Test-Path $envPath)) {
        $driverName = $installedDriver.Name
        $content = Get-Content $envPath -Raw
        if ($content -match 'ODBC Driver \d+ for SQL Server' -and $content -notmatch [regex]::Escape($driverName)) {
            $content = $content -replace 'ODBC Driver \d+ for SQL Server', $driverName
            Set-Content $envPath $content -NoNewline
            Write-Host "  [OK] Updated .env to use '$driverName'." -ForegroundColor Green
        }
    }

    # Test database connection / prompt for credentials
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
    Refresh-Path
    $pyExe = Get-PythonPath

    # Quick check: try to install psycopg2 first so the test can run
    if ($pyExe) {
        & $pyExe -m pip install psycopg2-binary -q 2>$null
    }

    if ($pyExe -and $dbUser -and $dbPassword) {
        Write-Host "  [ ] Testing database connection (user='$dbUser')..." -ForegroundColor Yellow
        $testScript = "import psycopg2; psycopg2.connect(host='localhost', port=5432, user='$dbUser', password='$dbPassword', database='postgres').close(); print('OK')"
        $testResult = & $pyExe -c $testScript 2>$null
        if ($testResult -eq "OK") {
            $dbConnectionOk = $true
            Write-Host "  [OK] Database connection successful!" -ForegroundColor Green
        } else {
            Write-Host "  [!] Connection failed." -ForegroundColor Yellow
        }
    }

    if (-not $dbConnectionOk) {
        Write-Host ""
        Write-Host "  Enter your PostgreSQL credentials (from the installer):" -ForegroundColor Yellow
        $inputUser = Read-Host "  Username (press Enter for '$dbUser')"
        if (-not $inputUser) { $inputUser = $dbUser }

        $inputPwd = Read-Host "  Password (press Enter for 'openpgpwd')"
        if (-not $inputPwd) { $inputPwd = "openpgpwd" }

        if (Test-Path $envPath) {
            $content = Get-Content $envPath
            $content = $content -replace '^DB_USER=.*', "DB_USER=$inputUser"
            $content = $content -replace '^DB_PASSWORD=.*', "DB_PASSWORD=$inputPwd"
            $content | Set-Content $envPath
            Write-Host "  [OK] Credentials saved to .env." -ForegroundColor Green

            # Verify
            if ($pyExe) {
                $testScript = "import psycopg2; psycopg2.connect(host='localhost', port=5432, user='$inputUser', password='$inputPwd', database='postgres').close(); print('OK')"
                $testResult = & $pyExe -c $testScript 2>$null
                if ($testResult -eq "OK") {
                    Write-Host "  [OK] Connection verified!" -ForegroundColor Green
                } else {
                    Write-Host "  [!] Connection test failed. Make sure PostgreSQL is running." -ForegroundColor Yellow
                }
            }
        }
    }

    # ── STEP 9: Install Python + Node dependencies ────────────────────────────
    Write-Host "[9/11] Installing dependencies..." -ForegroundColor Cyan
    Refresh-Path
    $pyExe = Get-PythonPath

    if ($pyExe) {
        Write-Host "  [ ] Python packages (pip install)..." -ForegroundColor Yellow
        & $pyExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt") -q
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Python packages installed." -ForegroundColor Green
        } else {
            Write-Host "  [!] pip install had errors — some packages may be missing." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  [!] Python not found — skipping pip install." -ForegroundColor Red
    }

    $npmExe = Get-NpmPath
    if ($npmExe) {
        Write-Host "  [ ] Node.js packages (npm install)..." -ForegroundColor Yellow
        Push-Location $PSScriptRoot
        $env:PUPPETEER_SKIP_DOWNLOAD = "true"
        & $npmExe install --no-audit --no-fund 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [!] npm install failed — retrying clean..." -ForegroundColor Yellow
            $lockFile = Join-Path $PSScriptRoot "package-lock.json"
            if (Test-Path $lockFile) { Remove-Item $lockFile -Force -ErrorAction SilentlyContinue }
            $nodeModules = Join-Path $PSScriptRoot "node_modules"
            if (Test-Path $nodeModules) { Remove-Item $nodeModules -Recurse -Force -ErrorAction SilentlyContinue }
            & $npmExe install --no-audit --no-fund
        }
        $env:PUPPETEER_SKIP_DOWNLOAD = $null
        Pop-Location
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Node.js packages installed." -ForegroundColor Green
        } else {
            Write-Host "  [!] npm install failed." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  [!] npm not found — skipping npm install." -ForegroundColor Red
    }

    # ── STEP 10: Initialize database ──────────────────────────────────────────
    Write-Host "[10/11] Initializing database..." -ForegroundColor Cyan
    if ($pyExe) {
        Push-Location $repoRoot
        & $pyExe (Join-Path $PSScriptRoot "db_setup.py")
        Pop-Location
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [OK] Database initialized." -ForegroundColor Green
        } else {
            Write-Host "  [!] Database setup had issues. You can retry later with: py src\db_setup.py" -ForegroundColor Yellow
        }
    }

    # ── STEP 11: Connect to GitHub + Create shortcut ──────────────────────────
    Write-Host "[11/11] Finishing up..." -ForegroundColor Cyan
    Refresh-Path
    $gitExe = Get-GitPath

    # Connect folder to GitHub so SAPI_WATCHER.bat can auto-update
    if ($gitExe) {
        $gitDir = Join-Path $repoRoot ".git"
        if (-not (Test-Path $gitDir)) {
            Write-Host "  [ ] Connecting to GitHub for automatic updates..." -ForegroundColor Yellow
            Push-Location $repoRoot
            & $gitExe init 2>$null
            & $gitExe remote add origin "https://github.com/PatricioSal/ColinasOrder.git" 2>$null
            & $gitExe fetch origin 2>$null
            & $gitExe reset origin/main 2>$null
            Pop-Location
            Write-Host "  [OK] Connected to GitHub (auto-updates enabled)." -ForegroundColor Green
        } else {
            Write-Host "  [OK] Already connected to GitHub." -ForegroundColor Green
        }
    } else {
        Write-Host "  [!] Git not available — auto-updates disabled." -ForegroundColor Yellow
    }

    # Create Desktop shortcut
    $shortcutScript = Join-Path $PSScriptRoot "create_shortcut.bat"
    if (Test-Path $shortcutScript) {
        & cmd.exe /c $shortcutScript
    }

    # ══════════════════════════════════════════════════════════════════════════
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Setup complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Close this window and double-click 'SAPI_WATCHER'" -ForegroundColor White
    Write-Host "  on your Desktop to start the application." -ForegroundColor White
    Write-Host ""
    Write-Host "==========================================================" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "[!] Setup encountered a critical error:" -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    $($_)" -ForegroundColor DarkGray
}
finally {
    Write-Host ""
    Read-Host "Press Enter to close this window..."
}
