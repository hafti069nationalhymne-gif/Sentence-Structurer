# ClaimComposer setup for Windows (Windows PowerShell 5.1 or PowerShell 7).
# Called by START_ClaimComposer.bat, INSTALL_ClaimComposer.bat and UNINSTALL_ClaimComposer.bat.
# Every step checks first and skips work that is already done, so re-running continues safely.
param(
  [ValidateSet("start", "setup", "install", "uninstall")] [string]$Mode = "start",
  [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

# "Continue", not "Stop": in Windows PowerShell 5.1 any text a program writes to stderr would otherwise
# abort the whole script. Every program call goes through Native and is judged by its exit code instead.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Tools = Join-Path $Root ".tools"
$LogDir = Join-Path $Root "logs"
$Log = Join-Path $LogDir "setup.log"
$UserData = Join-Path $Root "userdata"
$ChoiceFile = Join-Path $UserData "setup_choice.txt"
$OllamaUrl = "http://127.0.0.1:11434"
New-Item -ItemType Directory -Force -Path $Tools, $LogDir, $UserData | Out-Null

$env:UV_INSTALL_DIR = Join-Path $Tools "uv"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$env:UV_CACHE_DIR = Join-Path $Tools "uv-cache"
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Root ".venv"
$env:UV_NO_MODIFY_PATH = "1"
# Use only the Python that uv installs into .tools\python. Pythons on the PATH (including broken
# leftovers such as an old %USERPROFILE%\.local\bin\python3.12.exe) are ignored and never changed.
$env:UV_PYTHON_PREFERENCE = "only-managed"
$env:UV_PYTHON_BIN_DIR = Join-Path $Tools "python-bin"
$env:PYTHONUTF8 = "1"
$Uv = Join-Path $env:UV_INSTALL_DIR "uv.exe"
$Py = Join-Path $Root ".venv\Scripts\python.exe"

function Log([string]$m) { Add-Content -Path $Log -Value ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding UTF8 }
function Say([string]$m) { Write-Host $m; Log $m }
# Run a program, append everything it prints to the log, return its exit code. Never throws.
function Native([string]$exe, [string[]]$arguments, $stdin = $null) {
  Log ("> " + (Split-Path -Leaf $exe) + " " + ($arguments -join " "))
  try {
    if ($null -ne $stdin) { $out = $stdin | & $exe @arguments 2>&1 }
    else { $out = & $exe @arguments 2>&1 }
    $code = $LASTEXITCODE
    if ($out) { $out | ForEach-Object { "$_" } | Add-Content -Path $Log -Encoding UTF8 }
    if ($null -eq $code) { $code = 0 }
    return [int]$code
  } catch {
    Log "  failed to run: $_"
    return 1
  }
}

function Fail([string]$what, [string]$next = "Check your internet connection and double-click the launcher again.") {
  Write-Host ""
  Say "ClaimComposer could not finish setting up: $what"
  Say "Next step: $next"
  Write-Host "Details are in: $Log"
  Read-Host "Press Enter to close this window" | Out-Null
  exit 1
}

function FreeDiskGB { try { $d = Get-PSDrive -Name ((Get-Item $Root).PSDrive.Name); return [int]($d.Free / 1GB) } catch { return -1 } }
function RamGB { try { return [int]((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB) } catch { return -1 } }
function HaveUv { Test-Path $Uv }
function HavePython { if (-not (HaveUv)) { return $false }; return ((Native $Uv @("python", "find", "3.12")) -eq 0) }
function HaveEnv { if (-not (Test-Path $Py)) { return $false }; return ((Native $Py @("-c", "import fastapi, uvicorn, pydantic, httpx, yaml")) -eq 0) }
function OllamaExe {
  $c = Get-Command ollama -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  $p = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
  if (Test-Path $p) { return $p }
  return $null
}
function OllamaUp { try { Invoke-RestMethod -Uri "$OllamaUrl/api/version" -TimeoutSec 2 -ErrorAction Stop | Out-Null; return $true } catch { return $false } }
function ModelPresent([string]$m) {
  try { $t = Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -TimeoutSec 4 -ErrorAction Stop; return [bool]($t.models | Where-Object { $_.name -eq $m }) } catch { return $false }
}

function AskFirstRun {
  if (Test-Path $ChoiceFile) { return (Get-Content $ChoiceFile -Raw).Trim() }
  $disk = FreeDiskGB; $ram = RamGB
  Write-Host ""
  Write-Host "Welcome to ClaimComposer. This first start sets things up once:"
  if (-not (HaveUv)) { Write-Host "  - uv, a small installer for Python                       (about 35 MB)" }
  if (-not (HavePython)) { Write-Host "  - Python 3.12, only for this app (system Python untouched) (about 70 MB)" }
  if (-not (HaveEnv)) { Write-Host "  - the app's Python packages                               (about 40 MB)" }
  Write-Host "  Optional AI for tone, translation and explanations:"
  if (-not (OllamaExe)) { Write-Host "  - Ollama, the local AI runtime                            (about 1.5 GB)" }
  Write-Host "  - a language model: qwen3.5:4b (about 3.4 GB) or gpt-oss:20b on strong computers (about 14 GB)"
  Write-Host "  Or use Ollama Cloud with your API key: nothing is downloaded, but sentences and rule texts are sent to ollama.com."
  Write-Host "  Free disk space here: $disk GB - memory: $ram GB"
  if ($disk -ge 0 -and $disk -lt 2) { Fail "there is less than 2 GB of free disk space." "Free some disk space, then start again." }
  if ($disk -ge 0 -and $disk -lt 20) { Write-Host "  Warning: under 20 GB free. Choose 'Template mode only' unless you can free space." -ForegroundColor Yellow }
  if ($ram -ge 0 -and $ram -lt 8) { Write-Host "  Warning: under 8 GB of memory. The AI would be slow. Template mode is recommended." -ForegroundColor Yellow }
  Write-Host ""
  Write-Host "  [1] Install with AI     [2] Template mode only (works fully without AI)"
  Write-Host "  [3] Use Ollama Cloud with an API key (no model download)     [Q] Quit"
  $def = "2"
  $defFile = Join-Path $Root "installer\default_choice.txt"
  if (Test-Path $defFile) { $d = (Get-Content $defFile -Raw).Trim(); if ($d -match "^[123]$") { $def = $d } }
  $a = Read-Host "Your choice [1/2/3/Q] (Enter = $def)"
  if ($a -eq "") { $a = $def }
  switch ($a) {
    "1" { $c = "ai" }
    "2" { $c = "template" }
    "3" { $c = "cloud" }
    default { Write-Host "Nothing was installed."; exit 0 }
  }
  Set-Content -Path $ChoiceFile -Value $c -Encoding ASCII
  Log "choice: $c"
  return $c
}

function InstallUv {
  if (HaveUv) { Log "uv present"; return }
  Say "Installing uv into $($env:UV_INSTALL_DIR) ..."
  $code = Native "powershell" @("-ExecutionPolicy", "ByPass", "-NoProfile", "-c", "irm https://astral.sh/uv/install.ps1 | iex")
  if (-not (HaveUv)) { Fail "uv could not be downloaded (exit code $code)." }
  Native $Uv @("--version") | Out-Null
}

function InstallPython {
  if (HavePython) { Log "python 3.12 present"; return }
  Say "Installing Python 3.12 for ClaimComposer only ..."
  if ((Native $Uv @("python", "install", "3.12")) -ne 0) { Fail "Python 3.12 could not be installed." }
  if (-not (HavePython)) { Fail "Python 3.12 was installed but could not be found." }
}

function SyncEnv {
  $stamp = Join-Path $Root ".venv\.synced"
  if ((HaveEnv) -and (Test-Path $stamp) -and ((Get-Item $stamp).LastWriteTime -gt (Get-Item (Join-Path $Root "uv.lock")).LastWriteTime)) { Log "environment up to date"; return }
  Say "Installing the app's packages ..."
  Push-Location $Root
  $code = Native $Uv @("sync", "--frozen", "--no-dev", "--python", "3.12")
  Pop-Location
  if ($code -ne 0) { Fail "the app's packages could not be installed." }
  New-Item -ItemType File -Force -Path $stamp | Out-Null
}

function InstallOllama {
  if (OllamaExe) { Log "ollama present"; return $true }
  Say "Installing Ollama (optional local AI) ..."
  $w = Get-Command winget -ErrorAction SilentlyContinue
  if ($w) {
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    if (OllamaExe) { return $true }
  }
  try {
    $exe = Join-Path $Tools "OllamaSetup.exe"
    Say "Downloading the official OllamaSetup.exe ..."
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $exe -ErrorAction Stop
    Start-Process -FilePath $exe -ArgumentList "/SILENT" -Wait
  } catch { Log "OllamaSetup failed: $_"; return $false }
  return [bool](OllamaExe)
}

$script:OllamaProc = $null
function StartOllama {
  if (OllamaUp) { return $true }
  Say "Starting Ollama ..."
  $script:OllamaProc = Start-Process -FilePath (OllamaExe) -ArgumentList "serve" -WindowStyle Hidden -PassThru
  for ($i = 0; $i -lt 30; $i++) { if (OllamaUp) { return $true }; Start-Sleep -Seconds 1 }
  return $false
}

function PullModel {
  $model = (& $Py -m app.cli choose-model) 2>$null
  if (-not $model) { $model = "qwen3.5:4b" }
  $settings = Join-Path $UserData "settings.json"
  if (Test-Path $settings) { try { $s = Get-Content $settings -Raw | ConvertFrom-Json; if ($s.chat_model) { $model = $s.chat_model } } catch {} }
  if (ModelPresent $model) { Log "model $model present" }
  else {
    Say "Downloading the language model $model (this can take a while; progress below) ..."
    & (OllamaExe) pull $model
    if ($LASTEXITCODE -ne 0) { return $false }
  }
  Push-Location $Root
  Native $Py @("-m", "app.cli", "set-model", $model) | Out-Null
  Say "Checking that $model answers in the required JSON format ..."
  if ((Native $Py @("-m", "app.cli", "verify-model", $model)) -ne 0) {
    Say "The model did not pass the JSON test. ClaimComposer will use template mode."
    Native $Py @("-m", "app.cli", "set-ai", "off") | Out-Null
  }
  Pop-Location
  return $true
}

function SetupCloud {
  # Ollama Cloud: no Ollama install and no download. The key goes to Python on stdin, never as an argument or to the log.
  $keyFile = Join-Path $UserData "ollama_api_key.txt"
  Push-Location $Root
  try {
    if ($env:OLLAMA_API_KEY) { Native $Py @("-m", "app.cli", "set-cloud") "" | Out-Null }
    elseif (Test-Path $keyFile) { Native $Py @("-m", "app.cli", "set-cloud") (Get-Content $keyFile -Raw) | Out-Null }
    else {
      Write-Host "Create a key at https://ollama.com/settings/keys (sign in first)."
      $secure = Read-Host "Paste your Ollama API key (input is hidden), then press Enter" -AsSecureString
      $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
      $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
      $ok = ((Native $Py @("-m", "app.cli", "set-cloud") $plain) -eq 0)
      $plain = $null
      if (-not $ok) {
        Say "That does not look like an Ollama API key. ClaimComposer will run in template mode."
        Write-Host "You can add the key later in Settings > AI."
        Native $Py @("-m", "app.cli", "set-ai", "off") | Out-Null
        return
      }
    }
    Say "Checking Ollama Cloud ..."
    if ((Native $Py @("-m", "app.cli", "verify-model")) -eq 0) { Say "Ollama Cloud works. Sentences and rule texts will be sent to ollama.com when the AI is used." }
    else {
      Say "Ollama Cloud did not answer correctly (wrong key, model not offered, or no internet)."
      Write-Host "ClaimComposer still works fully in template mode. Fix the key or model in Settings > AI."
    }
  } finally { Pop-Location }
}

function Setup {
  Log "---- setup started in $Root ($([Environment]::OSVersion.VersionString), PowerShell $($PSVersionTable.PSVersion))"
  $choice = AskFirstRun
  InstallUv
  InstallPython
  SyncEnv
  if ($choice -eq "cloud") { SetupCloud; Log "setup finished"; return }
  Push-Location $Root
  if ($choice -ne "ai") { Native $Py @("-m", "app.cli", "set-ai", "off") | Out-Null; Pop-Location; return }
  Pop-Location
  if (-not (InstallOllama)) { Say "Ollama could not be installed. ClaimComposer will run in template mode."; return }
  if (-not (StartOllama)) { Say "Ollama did not start. ClaimComposer will run in template mode."; return }
  if (-not (PullModel)) { Say "The model could not be downloaded. ClaimComposer will run in template mode." }
  Log "setup finished"
}

function RunApp {
  Write-Host ""
  Write-Host "Starting ClaimComposer ... (keep this window open; close it to stop the app)"
  Push-Location $Root
  try {
    # Runs in this console: closing the window ends the server.
    & $Py -m app.main --open
  } finally {
    Pop-Location
    if ($script:OllamaProc) { try { Stop-Process -Id $script:OllamaProc.Id -ErrorAction SilentlyContinue } catch {} }
    Log "launcher closed"
  }
}

function CopyApp([string]$dest) {
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  $exclude = @(".venv", ".tools", "logs", "userdata", ".git", "dist", "__pycache__", ".pytest_cache")
  robocopy $Root $dest /E /XD $exclude /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { Fail "the app could not be copied to $dest." "Close other ClaimComposer windows and try again." }
}

function Shortcut([string]$path, [string]$target, [string]$arguments, [string]$workdir, [string]$icon) {
  $shell = New-Object -ComObject WScript.Shell
  $lnk = $shell.CreateShortcut($path)
  $lnk.TargetPath = $target
  $lnk.Arguments = $arguments
  $lnk.WorkingDirectory = $workdir
  $lnk.IconLocation = $icon
  $lnk.Description = "ClaimComposer (research prototype)"
  $lnk.Save()
}

$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\ClaimComposer"
$Desktop = [Environment]::GetFolderPath("Desktop")
$StartMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "ClaimComposer.lnk"

switch ($Mode) {
  "start" { Setup; RunApp }
  "setup" { Setup }
  "install" {
    if ($Root -ne $InstallDir) { Say "Copying ClaimComposer to $InstallDir ..."; CopyApp $InstallDir }
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallDir "installer\setup.ps1") -Mode setup -Root $InstallDir
    if ($LASTEXITCODE -ne 0) { Fail "the setup in $InstallDir did not finish." "Start INSTALL_ClaimComposer.bat again." }
    $bat = Join-Path $InstallDir "START_ClaimComposer.bat"
    $ico = Join-Path $InstallDir "installer\icon.ico"
    Shortcut (Join-Path $Desktop "ClaimComposer.lnk") $bat "" $InstallDir $ico
    Shortcut $StartMenu $bat "" $InstallDir $ico
    Say "ClaimComposer is installed. Start it from the Start menu or the desktop shortcut."
    Read-Host "Press Enter to close this window" | Out-Null
  }
  "uninstall" {
    Write-Host "This removes ClaimComposer from $InstallDir, its shortcuts and its local data (tickets and reviews)."
    $a = Read-Host "Remove ClaimComposer? [y/N]"
    if ($a -notmatch "^(y|yes|j|ja)$") { Write-Host "Nothing was removed."; exit 0 }
    $model = $null
    $settings = Join-Path $InstallDir "userdata\settings.json"
    if (Test-Path $settings) { try { $model = (Get-Content $settings -Raw | ConvertFrom-Json).chat_model } catch {} }
    foreach ($p in @((Join-Path $Desktop "ClaimComposer.lnk"), $StartMenu)) { if (Test-Path $p) { Remove-Item -Force $p } }
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    Write-Host "ClaimComposer was removed."
    if ($model -and (OllamaExe)) {
      $b = Read-Host "Also remove the AI model $model from Ollama (frees several GB)? [y/N]"
      if ($b -match "^(y|yes|j|ja)$") { & (OllamaExe) rm $model; Write-Host "Model removed." } else { Write-Host "The model was kept." }
      Write-Host "Ollama itself stays installed; remove it in Settings > Apps if you no longer need it."
    }
    Read-Host "Press Enter to close this window" | Out-Null
  }
}
