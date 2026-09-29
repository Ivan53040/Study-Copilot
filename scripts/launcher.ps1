# Study Copilot one-click launcher (Windows).
#
#   1. Starts the backend on http://127.0.0.1:8767. In this mode it also serves
#      the built interface (frontend\dist-web), so no dev server is needed.
#   2. Opens it in its own app window (Microsoft Edge or Chrome "app mode":
#      no tabs or address bar).
#   3. When that window is closed, stops the backend and runs one vault sync,
#      like the packaged desktop app does.
#
# The interface is rebuilt automatically (npm run build:web) whenever the
# frontend source is newer than the last build. The first run also puts a
# "Study Copilot" shortcut on the desktop.
#
# Start it with "Study Copilot.cmd" in the project folder, or the shortcut.
# Logs: data\launcher.log, data\launcher-backend.log, data\launcher-build.log

$ErrorActionPreference = 'Stop'

$Port       = 8767
$Root       = Split-Path -Parent $PSScriptRoot
$AppUrl     = "http://127.0.0.1:$Port/"
$HealthUrl  = "http://127.0.0.1:$Port/health"
$Frontend   = Join-Path $Root 'frontend'
$WebDir     = Join-Path $Frontend 'dist-web'
$DataDir    = Join-Path $Root 'data'
$ProfileDir = Join-Path $DataDir 'app-window'
$LogFile    = Join-Path $DataDir 'launcher.log'
$BackendLog = Join-Path $DataDir 'launcher-backend.log'
$BuildLog   = Join-Path $DataDir 'launcher-build.log'
$Python     = Join-Path $Root '.venv\Scripts\python.exe'
$PythonW    = Join-Path $Root '.venv\Scripts\pythonw.exe'
$SyncScript = Join-Path $Root 'scripts\sync_standalone.py'
$Icon       = Join-Path $Frontend 'src-tauri\icons\icon.ico'

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Write-Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format s), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# ---- small "Starting..." window -------------------------------------------

$splash = New-Object System.Windows.Forms.Form
$splash.Text = 'Study Copilot'
$splash.FormBorderStyle = 'None'
$splash.StartPosition = 'CenterScreen'
$splash.Size = New-Object System.Drawing.Size(380, 118)
$splash.BackColor = [System.Drawing.Color]::FromArgb(250, 249, 245)
$splash.ShowInTaskbar = $true
if (Test-Path $Icon) { $splash.Icon = New-Object System.Drawing.Icon($Icon) }

$accent = New-Object System.Windows.Forms.Panel
$accent.Dock = 'Left'
$accent.Width = 5
$accent.BackColor = [System.Drawing.Color]::FromArgb(217, 119, 87)

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Study Copilot'
$title.Font = New-Object System.Drawing.Font('Georgia', 17)
$title.ForeColor = [System.Drawing.Color]::FromArgb(31, 30, 29)
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(26, 22)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'Starting...'
$status.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$status.ForeColor = [System.Drawing.Color]::FromArgb(116, 114, 107)
$status.AutoSize = $true
$status.Location = New-Object System.Drawing.Point(28, 68)

$splash.Controls.Add($title)
$splash.Controls.Add($status)
$splash.Controls.Add($accent)

function Set-Status([string]$Text) {
    $status.Text = $Text
    [System.Windows.Forms.Application]::DoEvents()
}

function Wait-Briefly([int]$Milliseconds) {
    $until = (Get-Date).AddMilliseconds($Milliseconds)
    while ((Get-Date) -lt $until) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 50
    }
}

# ---- helpers ----------------------------------------------------------------

function Test-Backend {
    # True only when Study Copilot answers on our port (not some other program).
    try {
        $request = [System.Net.WebRequest]::Create($HealthUrl)
        $request.Timeout = 2000
        $request.Proxy = $null
        $response = $request.GetResponse()
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            return ($reader.ReadToEnd() -match '"vault_root"')
        } finally {
            $response.Close()
        }
    } catch {
        return $false
    }
}

function Get-NewestWriteTime([string[]]$Paths) {
    $newest = [datetime]::MinValue
    foreach ($path in $Paths) {
        if (-not (Test-Path $path)) { continue }
        if (Test-Path $path -PathType Container) {
            foreach ($file in (Get-ChildItem -Path $path -Recurse -File)) {
                if ($file.LastWriteTimeUtc -gt $newest) { $newest = $file.LastWriteTimeUtc }
            }
        } else {
            $time = (Get-Item $path).LastWriteTimeUtc
            if ($time -gt $newest) { $newest = $time }
        }
    }
    return $newest
}

function Update-InterfaceIfNeeded {
    $builtIndex = Join-Path $WebDir 'index.html'
    $sources = @(
        (Join-Path $Frontend 'src'),
        (Join-Path $Frontend 'public'),
        (Join-Path $Frontend 'index.html'),
        (Join-Path $Frontend 'package.json'),
        (Join-Path $Frontend 'vite.config.ts')
    )
    if (Test-Path $builtIndex) {
        $builtAt = (Get-Item $builtIndex).LastWriteTimeUtc
        if ((Get-NewestWriteTime $sources) -le $builtAt) { return }
    }
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) {
        if (Test-Path $builtIndex) {
            Write-Log 'Interface source changed but npm was not found; using the existing build.'
            return
        }
        throw "Node.js (npm) was not found, so the interface can't be built. Install Node.js, then try again."
    }
    Set-Status 'Updating the interface (can take a minute)...'
    Write-Log 'Building the interface (npm run build:web)'
    $command = '/c ""{0}" run build:web > "{1}" 2>&1"' -f $npm.Source, $BuildLog
    $build = Start-Process -FilePath $env:ComSpec -ArgumentList $command `
        -WorkingDirectory $Frontend -WindowStyle Hidden -PassThru
    while (-not $build.HasExited) { Wait-Briefly 200 }
    if ($build.ExitCode -ne 0 -or -not (Test-Path $builtIndex)) {
        throw 'Building the interface failed. Details: data\launcher-build.log'
    }
}

function Start-Backend {
    if (-not (Test-Path $Python)) {
        throw "Python environment not found (.venv). Set it up first, see README.md."
    }
    $env:STUDY_COPILOT_WEB_DIR = $WebDir
    $command = '/c ""{0}" -m uvicorn app.main:app --host 127.0.0.1 --port {1} --log-level warning > "{2}" 2>&1"' -f `
        $Python, $Port, $BackendLog
    $process = Start-Process -FilePath $env:ComSpec -ArgumentList $command `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    Write-Log "Started backend (cmd pid $($process.Id)) on port $Port"
    return $process
}

function Stop-Backend($Process) {
    if ($null -eq $Process -or $Process.HasExited) { return }
    & taskkill.exe /PID $Process.Id /T /F | Out-Null
    Write-Log 'Stopped backend'
}

function Find-AppBrowser {
    $candidates = @()
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA)) {
        if ($base) {
            $candidates += (Join-Path $base 'Microsoft\Edge\Application\msedge.exe')
            $candidates += (Join-Path $base 'Google\Chrome\Application\chrome.exe')
        }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    foreach ($name in @('msedge.exe', 'chrome.exe')) {
        try {
            $key = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$name"
            $path = (Get-ItemProperty -Path $key -ErrorAction Stop).'(default)'
            if ($path -and (Test-Path $path)) { return $path }
        } catch { }
    }
    return $null
}

function Get-AppWindowProcesses {
    # Browser processes that belong to our app window's own profile folder.
    $marker = $ProfileDir.ToLowerInvariant()
    $all = Get-CimInstance Win32_Process -Filter "Name='msedge.exe' OR Name='chrome.exe'" `
        -ErrorAction SilentlyContinue
    return @($all | Where-Object { $_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($marker) })
}

function Open-AppWindow {
    $browser = Find-AppBrowser
    if (-not $browser) {
        Write-Log 'Edge/Chrome not found; opening the default browser'
        Start-Process $AppUrl
        return $false
    }
    New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
    $arguments = '--app={0} --user-data-dir="{1}" --no-first-run --no-default-browser-check --window-size=1400,900' -f `
        $AppUrl, $ProfileDir
    Start-Process -FilePath $browser -ArgumentList $arguments | Out-Null
    Write-Log "Opened app window with $browser"
    return $true
}

function Install-DesktopShortcut {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktop 'Study Copilot.lnk'
    if (Test-Path $shortcutPath) { return }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $PSHOME 'powershell.exe'
    $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $PSCommandPath
    $shortcut.WorkingDirectory = $Root
    if (Test-Path $Icon) { $shortcut.IconLocation = $Icon }
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Open Study Copilot'
    $shortcut.Save()
    Write-Log "Created desktop shortcut: $shortcutPath"
}

# ---- main -------------------------------------------------------------------

$backend = $null
try {
    Write-Log 'Launcher started'
    try { Install-DesktopShortcut } catch { Write-Log "Could not create the desktop shortcut: $($_.Exception.Message)" }

    if (Test-Backend) {
        # Already running (opened earlier): just show another window.
        Write-Log 'Backend already running; opening a window only'
        [void](Open-AppWindow)
        return
    }

    $splash.Show()
    [System.Windows.Forms.Application]::DoEvents()

    Update-InterfaceIfNeeded

    Set-Status 'Starting...'
    $backend = Start-Backend
    $deadline = (Get-Date).AddSeconds(90)
    while (-not (Test-Backend)) {
        if ($backend.HasExited) {
            $tail = ''
            if (Test-Path $BackendLog) { $tail = (Get-Content $BackendLog -Tail 12) -join "`n" }
            throw "The backend stopped while starting.`n`n$tail"
        }
        if ((Get-Date) -gt $deadline) { throw 'The backend did not start within 90 seconds. Details: data\launcher-backend.log' }
        Wait-Briefly 250
    }

    Set-Status 'Opening...'
    $tracked = Open-AppWindow
    Wait-Briefly 800
    $splash.Hide()

    if (-not $tracked) {
        # A normal browser tab: we can't tell when it closes, so leave the
        # backend running (the next launch reuses it).
        $backend = $null
        return
    }

    # Wait for the window to appear, then for every window of it to close.
    $appeared = $false
    $until = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $until) {
        if ((Get-AppWindowProcesses).Count -gt 0) { $appeared = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $appeared) {
        Write-Log 'Could not track the app window; leaving the backend running'
        $backend = $null
        return
    }
    while ((Get-AppWindowProcesses).Count -gt 0) { Start-Sleep -Seconds 2 }
    Write-Log 'App window closed'

    Stop-Backend $backend
    $backend = $null

    # Same as the packaged app: one vault sync after closing.
    if ((Test-Path $PythonW) -and (Test-Path $SyncScript)) {
        Start-Process -FilePath $PythonW -ArgumentList ('"{0}" --on-close' -f $SyncScript) `
            -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
        Write-Log 'Started sync-on-close'
    }
} catch {
    Write-Log "ERROR $($_.Exception.Message)"
    $splash.Hide()
    [void][System.Windows.Forms.MessageBox]::Show(
        "Study Copilot could not start.`n`n$($_.Exception.Message)",
        'Study Copilot', 'OK', 'Error')
    Stop-Backend $backend
} finally {
    $splash.Close()
}
