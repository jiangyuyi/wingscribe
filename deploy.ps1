#!/usr/bin/env pwsh
#===============================================================================
# WingScribe Windows Deployment Script
#===============================================================================

$ProgressPreference = "SilentlyContinue"

# 检查并设置执行策略（允许运行脚本）
try {
    $currentPolicy = Get-ExecutionPolicy -Scope CurrentUser -ErrorAction SilentlyContinue
    if ($currentPolicy -eq "Restricted") {
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force -ErrorAction SilentlyContinue
        Log-Info "Execution policy set to RemoteSigned"
    }
} catch {
    # 如果设置失败，脚本仍可通过右键运行方式执行
}

$PROJECT_ROOT = $PSScriptRoot
$GITEE_MIRROR = "https://gitee.com/jiangyuyi/wingscribe.git"
$GITHUB_ORIGIN = "https://github.com/jiangyuyi/wingscribe.git"
$PIP_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

$COLORS = @{
    RED     = "Red"
    GREEN   = "Green"
    YELLOW  = "Yellow"
    CYAN    = "Cyan"
    WHITE   = "White"
    GRAY    = "Gray"
}

function Test-Command {
    param([string]$Name)
    try {
        Get-Command $Name -ErrorAction Stop | Out-Null
        return $true
    } catch { return $false }
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Read-Input {
    param([string]$Prompt, [string]$Default)
    if ($Default) {
        $result = Read-Host "$Prompt [$Default]"
        if ([string]::IsNullOrWhiteSpace($result)) { return $Default }
        return $result.Trim()
    }
    return (Read-Host $Prompt).Trim()
}

function Read-YesNo {
    param([string]$Prompt, [string]$Default = "y")
    while ($true) {
        $suffix = if ($Default -eq "y") { "[Y/n]" } else { "[y/N]" }
        $answer = Read-Host "$Prompt $suffix"
        if ([string]::IsNullOrWhiteSpace($answer)) { $answer = $Default }
        $answer = $answer.ToLower()
        if ($answer -eq "y" -or $answer -eq "yes") { return $true }
        if ($answer -eq "n" -or $answer -eq "no") { return $false }
    }
}

function Pause-Host {
    Write-Host "Press Enter to continue..." -ForegroundColor Gray
    Read-Host
}

function Log-Info   { Write-Host "[INFO]   $($args[0])" -ForegroundColor $COLORS.GREEN }
function Log-Warn   { Write-Host "[WARN]   $($args[0])" -ForegroundColor $COLORS.YELLOW }
function Log-Error  { Write-Host "[ERROR]  $($args[0])" -ForegroundColor $COLORS.RED }
function Log-Step   { Write-Host "[STEP]   $($args[0])" -ForegroundColor $COLORS.CYAN }
function Log-Success{ Write-Host "[OK]     $($args[0])" -ForegroundColor $COLORS.GREEN }

function Test-Git {
    if (Test-Command "git") {
        Log-Info "Git installed: $(git --version)"
        return $true
    }
    Log-Warn "Git not found"
    return $false
}

function Test-Python {
    foreach ($cmd in @("python3", "python")) {
        if (Test-Command $cmd) {
            try {
                $version = & $cmd --version 2>&1 | Out-String
                if ($version -match "Python (\d+)\.(\d+)") {
                    $major = [int]$Matches[1]
                    $minor = [int]$Matches[2]
                    if ($major -eq 3 -and $minor -ge 8) {
                        Log-Info "Python installed: $version".Trim()
                        $script:PYTHON_CMD = $cmd
                        return $true
                    }
                }
            } catch { }
        }
    }
    Log-Warn "Python 3.8+ not found"
    return $false
}

function Test-ExifTool {
    if (Test-Command "exiftool") {
        Log-Info "ExifTool installed: $(exiftool -ver)"
        return $true
    }
    Log-Warn "ExifTool not found"
    return $false
}

function Test-GPU {
    if (Test-Command "nvidia-smi") {
        try {
            $gpu = nvidia-smi --query-gpu=name --format=csv,noheader 2>&1 | Select-Object -First 1
            if ($gpu) {
                Log-Info "GPU detected: $gpu"
                $script:HAS_GPU = $true
                return $true
            }
        } catch { }
    }
    Log-Warn "No NVIDIA GPU detected, will use CPU"
    $script:HAS_GPU = $false
    return $false
}

function Test-CUDA {
    <#
    .SYNOPSIS
        Check if CUDA and cuDNN are installed
    .OUTPUTS
        Returns hashtable with cuda_version, cudnn_version, is_available
    #>
    $result = @{
        cuda_version = $null
        cudnn_version = $null
        is_available = $false
        driver_version = $null
    }

    # 检测 NVIDIA 驱动
    if (Test-Command "nvidia-smi") {
        try {
            $driverVersion = nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>&1 | Select-Object -First 1
            $result.driver_version = $driverVersion.Trim()
            Log-Info "NVIDIA Driver: $driverVersion"
        } catch { }
    }

    # 检测 CUDA (nvcc)
    if (Test-Command "nvcc") {
        try {
            $cudaVersion = nvcc --version 2>&1 | Select-String "release" | ForEach-Object {
                $_ -replace ".*release (\d+\.\d+).*", '$1'
            }
            if ($cudaVersion) {
                $result.cuda_version = $cudaVersion.Trim()
                $result.is_available = $true
                Log-Info "CUDA Toolkit: $cudaVersion"
            }
        } catch { }
    } else {
        Log-Warn "CUDA Toolkit (nvcc) not found"
    }

    # 检测 cuDNN
    $cudnnPaths = @(
        "$env:ProgramFiles\NVIDIA GPU Computing Toolkit\CUDA\*\lib\x64\cudnn*",
        "$env:ProgramFiles\NVIDIA Corporation\cudnn\*\bin\cudnn*",
        "$env:CUDA_PATH\lib\x64\cudnn*",
        "$env:LOCALAPPDATA\NVIDIA\cudnn\*"
    )

    foreach ($path in $cudnnPaths) {
        $cudnn = Get-ChildItem -Path $path -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cudnn) {
            $result.cudnn_version = "Installed"
            $result.is_available = $true
            Log-Info "cuDNN found: $($cudnn.FullName)"
            break
        }
    }

    if (-not $result.cudnn_version) {
        Log-Warn "cuDNN not found"
    }

    return $result
}

function Install-CUDA {
    <#
    .SYNOPSIS
        Provide CUDA installation guidance
    #>
    param([string]$Device)

    if ($Device -ne "cuda" -and $Device -ne "auto") {
        return $true
    }

    Log-Step "Checking CUDA environment for $Device mode..."

    $cudaStatus = Test-CUDA

    if ($cudaStatus.is_available) {
        Log-Success "CUDA environment ready (Driver: $($cudaStatus.driver_version), CUDA: $($cudaStatus.cuda_version))"
        return $true
    }

    # CUDA 不可用，提供安装指引
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  CUDA Installation Required" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  GPU detected but CUDA/cuDNN not installed." -ForegroundColor White
    Write-Host "  FeatherTrace requires CUDA for GPU acceleration." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Option 1: Auto-download (requires admin)" -ForegroundColor Cyan
    Write-Host "  Option 2: Manual download links" -ForegroundColor Cyan
    Write-Host "  Option 3: Continue with CPU (slower)" -ForegroundColor Yellow
    Write-Host ""

    $choice = Read-Host "Select option (1-3)"

    switch ($choice) {
        "1" {
            # 尝试自动下载
            Install-CUDAAuto
        }
        "2" {
            Show-CudaDownloadLinks
        }
        "3" {
            Log-Warn "Continuing with CPU mode"
            return $false  # 返回 false 让调用方切换到 CPU
        }
        default {
            Log-Error "Invalid choice"
            return $false
        }
    }
}

function Install-CUDAAuto {
    <#
    .SYNOPSIS
        Auto-download and install CUDA
    #>
    Log-Step "Attempting automatic CUDA installation..."

    # 检查是否为管理员
    $isAdmin = [bool]([System.Security.Principal.WindowsIdentity]::GetCurrent().Groups -match 'S-1-5-32-544')

    if (-not $isAdmin) {
        Log-Warn "Administrator privileges required for auto-install"
        Log-Info "Please run as Administrator or use manual download"
        Show-CudaDownloadLinks
        return $false
    }

    # 使用 winget 安装 CUDA (如果可用)
    if (Test-Command "winget") {
        Log-Info "Installing CUDA via winget (this may take a while)..."

        # 安装 CUDA Toolkit 12.1
        $cudaInstall = winget install --id NVIDIA.CUDA -e --source winget 2>&1
        if ($LASTEXITCODE -eq 0) {
            Log-Success "CUDA installed, please restart terminal"
            return $true
        }
        Log-Warn "winget CUDA install failed, trying direct download..."
    }

    # 打开下载页面
    Log-Info "Opening CUDA download page..."
    Start-Process "https://developer.nvidia.com/cuda-downloads"
    Show-CudaDownloadLinks
}

function Show-CudaDownloadLinks {
    <#
    .SYNOPSIS
        Show CUDA download links
    #>
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  CUDA Download Links" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  1. CUDA Toolkit 12.1 (Required)" -ForegroundColor Green
    Write-Host "     https://developer.nvidia.com/cuda-downloads" -ForegroundColor Gray
    Write-Host "     Select: Windows > x86_64 > 12 > exe (network)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  2. cuDNN 8.9 (Required for PyTorch)" -ForegroundColor Green
    Write-Host "     https://developer.nvidia.com/rdp/cudnn-download" -ForegroundColor Gray
    Write-Host "     Select: cuDNN v8.9.x for CUDA 12.x > Windows" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Installation steps:" -ForegroundColor White
    Write-Host "     1. Run CUDA Toolkit installer" -ForegroundColor Gray
    Write-Host "     2. Extract cuDNN zip to CUDA installation directory" -ForegroundColor Gray
    Write-Host "     3. Add to PATH: C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\bin" -ForegroundColor Gray
    Write-Host "     4. Restart terminal" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Alternative: Use CPU mode (slower, no CUDA needed)" -ForegroundColor Yellow
    Write-Host ""

    # 询问是否打开链接
    if (Read-YesNo "Open CUDA download page in browser?") {
        Start-Process "https://developer.nvidia.com/cuda-downloads"
    }
    if (Read-YesNo "Open cuDNN download page?") {
        Start-Process "https://developer.nvidia.com/rdp/cudnn-download"
    }
}

function Get-CudaInfo {
    <#
    .SYNOPSIS
        Get CUDA status info string
    #>
    $status = Test-CUDA
    if ($status.is_available) {
        return "CUDA $($status.cuda_version) (Driver $($status.driver_version))"
    }
    return "Not installed (CPU mode recommended)"
}

function Install-Git {
    Log-Step "Installing Git..."
    if (Test-Command "winget") {
        Log-Info "Using winget..."
        Log-Info "Downloading... (this may take a few minutes)"

        $process = Start-Process -FilePath "winget" -ArgumentList "install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements" -NoNewWindow -Wait -PassThru
        if ($process.ExitCode -eq 0) { Log-Success "Git installed (restart terminal)"; return $true }
    }
    if (Test-Command "scoop") {
        Log-Info "Using scoop..."
        scoop install git
        if ($LASTEXITCODE -eq 0) { Log-Success "Git installed"; return $true }
    }
    if (Test-Command "choco") {
        Log-Info "Using choco..."
        choco install git -y
        if ($LASTEXITCODE -eq 0) { Log-Success "Git installed"; return $true }
    }
    Log-Error "Cannot install Git automatically. Download: https://npm.taobao.org/mirrors/git-for-windows"
    return $false
}

function Install-Python {
    Log-Step "Installing Python 3.11..."
    if (Test-Command "winget") {
        Log-Info "Using winget..."
        Log-Info "Downloading... (this may take a few minutes)"

        $process = Start-Process -FilePath "winget" -ArgumentList "install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements" -NoNewWindow -Wait -PassThru
        if ($process.ExitCode -eq 0) { Log-Success "Python installed (restart terminal)"; return $true }
    }
    if (Test-Command "scoop") {
        Log-Info "Using scoop..."
        scoop install python311
        if ($LASTEXITCODE -eq 0) { Log-Success "Python installed"; return $true }
    }
    if (Test-Command "choco") {
        Log-Info "Using choco..."
        choco install python311 -y
        if ($LASTEXITCODE -eq 0) { Log-Success "Python installed"; return $true }
    }
    Log-Error "Cannot install Python automatically. Download: https://registry.npmmirror.com/binaries/python"
    return $false
}

function Install-ExifTool {
    Log-Step "Installing ExifTool..."

    # 使用 winget 安装（直接运行，显示下载进度）
    if (Test-Command "winget") {
        Log-Info "Installing via winget (OliverBetz.ExifTool)..."
        Log-Info "Downloading... (this may take a few minutes)"

        # 直接运行 winget，让它显示自己的进度条
        $process = Start-Process -FilePath "winget" -ArgumentList "install --id OliverBetz.ExifTool -e --source winget --accept-package-agreements --accept-source-agreements" -NoNewWindow -Wait -PassThru
        $exitCode = $process.ExitCode

        if ($exitCode -eq 0) {
            Log-Success "Winget installation completed"

            # 等待安装完成
            Start-Sleep -Seconds 3

            # 刷新 PATH
            $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User")

            # 直接测试 exiftool 命令
            try {
                $version = exiftool -ver 2>&1
                if ($?) {
                    Log-Success "ExifTool verified: $version"
                    return $true
                }
            } catch {
                Log-Warn "exiftool -ver failed, trying to find..."
            }

            # 尝试手动查找
            $exiftoolPaths = @(
                "C:\Program Files\ExifTool",
                "C:\Program Files (x86)\ExifTool",
                "$env:LOCALAPPDATA\Microsoft\WindowsApps"
            )

            foreach ($basePath in $exiftoolPaths) {
                if (Test-Path $basePath) {
                    $exe = Get-ChildItem -Path $basePath -Filter "exiftool*.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
                    if ($exe) {
                        $dir = $exe.Directory.FullName
                        $env:PATH = "$dir;$env:PATH"
                        Log-Success "ExifTool found: $($exe.FullName)"
                        return $true
                    }
                }
            }

            Log-Warn "ExifTool installed but verification failed"
            Log-Info "Please restart terminal and run 'exiftool -ver' to verify"
            return $true
        }
        else {
            Log-Warn "Winget install failed (exit code: $exitCode)"
        }
    }

    # 尝试 scoop
    if (Test-Command "scoop") {
        Log-Info "Trying scoop..."
        $null = scoop install exiftool
        if ($LASTEXITCODE -eq 0) {
            Log-Success "ExifTool installed via scoop"
            return $true
        }
    }

    # 尝试 choco
    if (Test-Command "choco") {
        Log-Info "Trying choco..."
        $null = choco install exiftool -y
        if ($LASTEXITCODE -eq 0) {
            Log-Success "ExifTool installed via choco"
            return $true
        }
    }

    Log-Error "Cannot install ExifTool automatically."
    Log-Info "Please download manually: https://exiftool.org/ or https://gitee.com/jiangyuyi/wingscribe/releases"
    return $false
}

function Install-AllDependencies {
    Log-Step "Installing system dependencies..."
    $failed = $false

    # Git
    if (-not (Test-Git)) {
        if (Read-YesNo "Install Git?") {
            if (-not (Install-Git)) {
                Log-Error "Git installation failed"
                exit 1
            }
        } else {
            Log-Error "Git is required"
            exit 1
        }
    }

    # Python
    if (-not (Test-Python)) {
        if (Read-YesNo "Install Python?") {
            if (-not (Install-Python)) {
                Log-Error "Python installation failed"
                exit 1
            }
            Log-Warn "Python installed. Please RESTART this terminal and run the script again."
            Log-Info "Or press Enter to exit and manually restart..."
            Read-Host
            exit 1
        } else {
            Log-Error "Python is required"
            exit 1
        }
    }

    # ExifTool
    if (-not (Test-ExifTool)) {
        if (Read-YesNo "Install ExifTool?") {
            if (-not (Install-ExifTool)) {
                Log-Error "ExifTool installation failed. Please install manually."
                Log-Info "Download: https://exiftool.org/ or https://gitee.com/jiangyuyi/wingscribe/releases"
                exit 1
            }
        } else {
            Log-Error "ExifTool is required"
            exit 1
        }
    }

    Log-Success "All dependencies installed"
    return $true
}

function Get-Project {
    Log-Step "Getting project..."

    # 检查是否是 git 仓库
    if (Test-Path "$PROJECT_ROOT\.git") {
        Log-Info "Git repository found"

        # 获取当前远程 URL
        $remoteUrl = git -C $PROJECT_ROOT remote get-url origin 2>$null

        # 如果是 GitHub，直接切换到 Gitee（不测试连通性，避免超时）
        if ($remoteUrl -and $remoteUrl.Contains("github.com")) {
            Log-Info "Using Gitee mirror for fast update..."
            git -C $PROJECT_ROOT remote set-url origin $GITEE_MIRROR 2>&1 | Out-Null
            $isGithub = $true
        }

        Log-Info "Updating project..."
        $pullResult = git -C $PROJECT_ROOT pull origin master 2>&1 | Out-String

        # 如果之前是 GitHub，操作完改回去
        if ($isGithub) {
            Log-Info "Restoring remote to GitHub..."
            git -C $PROJECT_ROOT remote set-url origin $GITHUB_ORIGIN 2>&1 | Out-Null
        }

        if ($LASTEXITCODE -eq 0) {
            Log-Success "Project updated"
            return $true
        }
        else {
            Log-Warn "Update failed, using existing files"
            return $true
        }
    }

    # 检查是否有项目文件（必须有 src/ 目录和 requirements.txt）
    $hasSrc = Test-Path "$PROJECT_ROOT\src"
    $hasConfig = Test-Path "$PROJECT_ROOT\config"
    $hasRequirements = Test-Path "$PROJECT_ROOT\requirements.txt"

    if ($hasSrc -and $hasConfig -and $hasRequirements) {
        Log-Success "Project files found"
        return $true
    }

    # 如果有 settings.yaml 也算有项目
    if (Test-Path "$PROJECT_ROOT\settings.yaml") {
        Log-Success "Project files found"
        return $true
    }

    # 收集用户文件（排除脚本文件）
    $userFiles = Get-ChildItem -Path $PROJECT_ROOT -Force | Where-Object {
        $_.Name -ne ".git" -and $_.Name -ne "deploy.ps1" -and
        $_.Name -ne "deploy.sh" -and $_.Name -ne "deploy.ps1.bin"
    }

    # 如果目录非空，先备份用户文件
    $backupDir = $null
    if ($userFiles) {
        Log-Warn "Found existing files but no project detected"
        $backupDir = Join-Path $env:TEMP "feather_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        Log-Info "Backing up your files to: $backupDir"
        $userFiles | Copy-Item -Destination $backupDir -Recurse -Force
        Log-Info "Backup complete"
    }

    # 使用临时目录 clone，避免直接在目标目录操作
    $tempDir = Join-Path $env:TEMP "feather_clone_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

    # 优先从 Gitee 克隆
    $cloneSuccess = $false
    $lastError = ""

    Log-Info "Cloning from Gitee..."
    $gitOutput = git clone --depth 1 $GITEE_MIRROR $tempDir 2>&1
    $lastError = $gitOutput | Out-String
    if ($LASTEXITCODE -eq 0 -and (Test-Path "$tempDir\src")) {
        # 自动改回 GitHub
        git -C $tempDir remote set-url origin $GITHUB_ORIGIN 2>&1 | Out-Null
        $cloneSuccess = $true
        Log-Success "Cloned from Gitee"
    }
    else {
        # 尝试 GitHub
        Log-Warn "Gitee clone failed: $lastError"
        Log-Info "Trying GitHub..."
        $gitOutput = git clone --depth 1 $GITHUB_ORIGIN $tempDir 2>&1
        $lastError = $gitOutput | Out-String
        if ($LASTEXITCODE -eq 0 -and (Test-Path "$tempDir\src")) {
            $cloneSuccess = $true
            Log-Success "Cloned from GitHub"
        }
        else {
            Log-Warn "GitHub clone failed: $lastError"
        }
    }

    if ($cloneSuccess) {
        Log-Info "Moving files to project directory..."

        # 如果目标目录有文件，先清空（保留脚本文件）
        Get-ChildItem -Path $PROJECT_ROOT -Force | Where-Object {
            $_.Name -ne ".git" -and $_.Name -ne "deploy.ps1" -and
            $_.Name -ne "deploy.sh" -and $_.Name -ne "deploy.ps1.bin"
        } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

        # 移动新文件
        Get-ChildItem -Path $tempDir -Force | Move-Item -Destination $PROJECT_ROOT -ErrorAction SilentlyContinue

        # 清理临时目录
        Remove-Item -Path $tempDir -Recurse -ErrorAction SilentlyContinue

        Log-Success "Project cloned successfully"
        if ($backupDir) {
            Log-Info "Your files are backed up at: $backupDir"
        }
        return $true
    }
    else {
        # Clone 失败，恢复用户文件
        Log-Error "Clone failed!"
        Log-Error "Details: $lastError"

        # 显示常见解决方案
        Write-Host ""
        Write-Host "  Possible solutions:" -ForegroundColor Yellow
        Write-Host "    1. Check internet connection" -ForegroundColor Gray
        Write-Host "    2. Install Git: https://npm.taobao.org/mirrors/git-for-windows" -ForegroundColor Gray
        Write-Host "    3. Or manually clone the repository to this folder" -ForegroundColor Gray
        Write-Host ""

        if ($backupDir -and (Test-Path $backupDir)) {
            Log-Info "Your files are backed up at: $backupDir"
        }
        return $false
    }
}

function Install-PythonDependencies {
    Log-Step "Installing Python dependencies..."

    if (-not (Test-Python)) { Log-Error "Python not found"; return $false }
    $venvPath = "$PROJECT_ROOT\venv"

    # 创建虚拟环境
    if (-not (Test-Path "$venvPath\Scripts\python.exe")) {
        Log-Info "Creating virtual environment..."
        $createResult = python -m venv $venvPath
        if ($LASTEXITCODE -ne 0) {
            Log-Error "Failed to create virtual environment"
            return $false
        }
    }

    $pythonVenv = "$venvPath\Scripts\python.exe"

    # 配置 pip 镜像
    Log-Info "Configuring pip mirror..."
    & $pythonVenv -m pip config set global.index-url $PIP_MIRROR 2>&1 | Out-Null

    # 升级 pip（显示进度）
    Log-Info "Upgrading pip..."
    $pipUpgrade = Start-Process -FilePath $pythonVenv -ArgumentList "-m pip install --upgrade pip" -NoNewWindow -Wait -PassThru
    if ($pipUpgrade.ExitCode -ne 0) {
        Log-Warn "pip upgrade failed, continuing..."
    }

    # 安装依赖（显示进度和下载速度）
    Log-Info "Installing requirements.txt..."
    Log-Info "Downloading and installing packages... (this may take several minutes)"

    $pipInstall = Start-Process -FilePath $pythonVenv -ArgumentList "-m pip install -r ""$PROJECT_ROOT\requirements.txt"" --progress-bar on" -NoNewWindow -Wait -PassThru
    if ($pipInstall.ExitCode -eq 0) {
        Log-Success "Python dependencies installed"
        return $true
    }

    # 失败重试
    Log-Warn "First attempt failed, retrying..."
    $pipRetry = Start-Process -FilePath $pythonVenv -ArgumentList "-m pip install -r ""$PROJECT_ROOT\requirements.txt"" --progress-bar on" -NoNewWindow -Wait -PassThru
    if ($pipRetry.ExitCode -eq 0) {
        Log-Success "Python dependencies installed (retry)"
        return $true
    }

    Log-Error "Failed to install Python dependencies"
    return $false
}

function Invoke-ConfigWizard {
    Log-Step "Configuring project..."
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Configuration Wizard" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    Write-Host "  1/3 Photo source directory" -ForegroundColor Cyan
    Write-Host "  Enter the directory containing your bird photos" -ForegroundColor Gray
    Write-Host "  Format: Year/yyyymmdd_Location/*.jpg" -ForegroundColor Gray
    Write-Host ""
    $sourceDir = Read-Input "Photo directory" "$env:USERPROFILE\Pictures"
    if (-not (Test-Path $sourceDir)) {
        if (Read-YesNo "Directory does not exist, create it?") { Ensure-Directory -Path $sourceDir; Log-Success "Created: $sourceDir" }
    }

    Write-Host ""
    Write-Host "  2/3 Output directory" -ForegroundColor Cyan
    $outputDir = Read-Input "Output directory" "$PROJECT_ROOT\data\processed"
    Ensure-Directory -Path $outputDir

    Write-Host ""
    Write-Host "  3/3 Processing device" -ForegroundColor Cyan
    Test-GPU

    if ($script:HAS_GPU) {
        Write-Host "  GPU detected, CUDA recommended for acceleration" -ForegroundColor Green
        Write-Host "  $(Get-CudaInfo)" -ForegroundColor Gray
        Write-Host ""

        $deviceOptions = @("auto - Auto detect (recommended)", "cuda - Use GPU (requires CUDA)", "cpu - Use CPU (slower)")
        foreach ($opt in $deviceOptions) { Write-Host "    $opt" -ForegroundColor White }

        $device = Read-Input "Device" "auto"

        # 如果用户选择了 cuda，检测 CUDA 环境
        if ($device -match "^cuda$|^auto$") {
            $cudaReady = Install-CUDA -Device $device
            if (-not $cudaReady -and $device -eq "cuda") {
                Log-Warn "CUDA not available, switching to CPU"
                $device = "cpu"
            }
        }
    } else {
        Write-Host "  No GPU detected, will use CPU" -ForegroundColor Yellow
        $device = "cpu"
    }

    Write-Host ""
    Log-Step "Generating config files..."

    $configPath = "$PROJECT_ROOT\config\settings.yaml"
    Ensure-Directory -Path (Split-Path $configPath)

    $lines = @()
    $lines += "# FeatherTrace config"
    $lines += "# Generated by deploy script"
    $lines += ""
    $lines += "paths:"
    $lines += "  allowed_roots:"
    $lines += "    - ""$($sourceDir.Replace('\', '/'))"""
    $lines += "  references_path: ""data/references"""
    $lines += "  sources:"
    $lines += "    - path: ""$($sourceDir.Replace('\', '/'))"""
    $lines += "      recursive: true"
    $lines += "      enabled: true"
    $lines += "  output:"
    $lines += "    root_dir: ""$($outputDir.Replace('\', '/'))"""
    $lines += "    structure_template: ""{source_structure}/{filename}_{species_cn}_{confidence}"""
    $lines += "    write_back_to_source: false"
    $lines += "  db_path: ""data/db/wingscribe.db"""
    $lines += "  ioc_list_path: ""data/references/Multiling IOC 15.1_d.xlsx"""
    $lines += "  model_cache_dir: ""data/models"""
    $lines += "processing:"
    $lines += "  device: ""$device"""
    $lines += "  yolo_model: ""yolov8n.pt"""
    $lines += "  confidence_threshold: 0.5"
    $lines += "  blur_threshold: 40.0"
    $lines += "  target_size: 640"
    $lines += "  crop_padding: 200"
    $lines += "recognition:"
    $lines += "  mode: ""local"""
    $lines += "  region_filter: ""auto"""
    $lines += "  top_k: 5"
    $lines += "  alternatives_threshold: 70"
    $lines += "  low_confidence_threshold: 60"
    $lines += "  local:"
    $lines += "    model_type: ""bioclip-2"""
    $lines += "    batch_size: 512"
    $lines += "    inference_batch_size: 16"
    $lines += "web:"
    $lines += "  host: ""0.0.0.0"""
    $lines += "  port: 8000"

    $lines | Out-File -FilePath $configPath -Encoding UTF8
    Log-Success "Config generated: $configPath"

    $secretsPath = "$PROJECT_ROOT\config\secrets.yaml"
    if (-not (Test-Path $secretsPath)) {
        @"
# FeatherTrace secrets
hf_api_key: ""
dongniao_api_key: ""
"@ | Out-File -FilePath $secretsPath -Encoding UTF8
        Log-Success "Secrets generated: $secretsPath"
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Configuration Summary" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Source: $sourceDir" -ForegroundColor White
    Write-Host "  Output: $outputDir" -ForegroundColor White
    Write-Host "  Device: $device" -ForegroundColor White
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    Write-Host "  Done!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Cyan
    return $true
}

function Start-WebServer {
    Log-Step "Starting Web server..."
    $venvPython = "$PROJECT_ROOT\venv\Scripts\python.exe"
    $webScript = "$PROJECT_ROOT\src\web\app.py"

    if (-not (Test-Path $venvPython)) {
        Log-Error "Virtual environment not found!"
        Log-Info "Please run [1] Start Deployment first"
        Write-Host ""
        Write-Host "Press Enter to continue..." -ForegroundColor Gray
        Read-Host
        return $false
    }

    if (-not (Test-Path $webScript)) {
        Log-Error "Web script not found: $webScript"
        Write-Host ""
        Write-Host "Press Enter to continue..." -ForegroundColor Gray
        Read-Host
        return $false
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Starting Web server..." -ForegroundColor Green
    Write-Host "  URL: http://localhost:8000" -ForegroundColor White
    Write-Host "  Press Ctrl+C to stop" -ForegroundColor Gray
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # 启动服务
    & $venvPython $webScript
    $exitCode = $LASTEXITCODE

    # 服务退出
    Write-Host ""
    Log-Warn "Web server stopped (exit code: $exitCode)"
    Write-Host ""
    Write-Host "Press Enter to return to menu..." -ForegroundColor Gray
    Read-Host
    return $true
}

function Show-Menu {
    Clear-Host
    Write-Host ""
    Write-Host "  ========================================  " -ForegroundColor Cyan
    Write-Host "  FeatherTrace Deployment" -ForegroundColor Cyan -NoNewline
    Write-Host "  AI Bird Photo Management" -ForegroundColor Gray
    Write-Host "  ========================================  " -ForegroundColor Cyan
    Write-Host ""

    # 显示 CUDA 状态
    $cudaStatus = Test-CUDA
    if ($script:HAS_GPU) {
        if ($cudaStatus.is_available) {
            Write-Host "  GPU: $($cudaStatus.driver_version) | CUDA: $($cudaStatus.cuda_version)" -ForegroundColor Green
        } else {
            Write-Host "  GPU: Detected (CUDA not installed)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Mode: CPU" -ForegroundColor Gray
    }

    Write-Host ""
    Write-Host "  [1] Start Deployment" -ForegroundColor White
    Write-Host "  [2] Configuration" -ForegroundColor White
    Write-Host "  [3] Update Project" -ForegroundColor White
    Write-Host "  [4] Install CUDA (GPU Support)" -ForegroundColor White
    Write-Host "  [5] Start Service" -ForegroundColor White
    Write-Host "  [6] Help" -ForegroundColor White
    Write-Host "  [7] Exit" -ForegroundColor White
    Write-Host ""
    Write-Host "  ========================================  " -ForegroundColor Cyan
}

function Invoke-Main {
    $script:PYTHON_CMD = $null
    $script:HAS_GPU = $false
    while ($true) {
        Show-Menu
        $choice = Read-Host "Enter option (1-7)"
        Write-Host ""
        switch ($choice) {
            "1" {
                Write-Host "========================================" -ForegroundColor Cyan
                Write-Host "  Deployment" -ForegroundColor Green
                Write-Host "========================================" -ForegroundColor Cyan
                Write-Host ""
                Install-AllDependencies
                Get-Project
                Install-PythonDependencies
                Invoke-ConfigWizard
                Write-Host ""
                Log-Success "Deployment complete!"
                Write-Host ""
                Write-Host "  Next: Select [5] to start service, open http://localhost:8000" -ForegroundColor Gray
                Write-Host ""
                Pause-Host
            }
            "2" { Invoke-ConfigWizard; Pause-Host }
            "3" { Get-Project; Pause-Host }
            "4" {
                Write-Host "========================================" -ForegroundColor Cyan
                Write-Host "  CUDA Installation" -ForegroundColor Green
                Write-Host "========================================" -ForegroundColor Cyan
                Write-Host ""
                Test-GPU
                if ($script:HAS_GPU) {
                    Install-CUDA -Device "cuda"
                } else {
                    Log-Warn "No NVIDIA GPU detected"
                }
                Write-Host ""
                Pause-Host
            }
            "5" { Start-WebServer }
            "6" {
                Clear-Host
                Write-Host ""
                Write-Host "  Help" -ForegroundColor Cyan
                Write-Host ""
                Write-Host "  Features:" -ForegroundColor White
                Write-Host "    - YOLOv8 bird detection" -ForegroundColor Gray
                Write-Host "    - BioCLIP species recognition" -ForegroundColor Gray
                Write-Host "    - EXIF metadata injection" -ForegroundColor Gray
                Write-Host "    - Web interface management" -ForegroundColor Gray
                Write-Host ""
                Write-Host "  How to Run:" -ForegroundColor White
                Write-Host "    - Right-click deploy.ps1 > 'Run with PowerShell'" -ForegroundColor Yellow
                Write-Host "    - Or run in PowerShell: Set-ExecutionPolicy RemoteSigned; .\\deploy.ps1" -ForegroundColor Gray
                Write-Host ""
                Write-Host "  GPU Acceleration:" -ForegroundColor White
                Write-Host "    - Select [4] Install CUDA for GPU support" -ForegroundColor Gray
                Write-Host "    - Requires NVIDIA GPU + CUDA Toolkit + cuDNN" -ForegroundColor Gray
                Write-Host "    - GPU mode is ~10x faster than CPU" -ForegroundColor Gray
                Write-Host ""
                Write-Host "  Quick Start:" -ForegroundColor White
                Write-Host "    1. Select [1] Start Deployment" -ForegroundColor Gray
                Write-Host "    2. Configure photo directory" -ForegroundColor Gray
                Write-Host "    3. (Optional) Select [4] Install CUDA" -ForegroundColor Gray
                Write-Host "    4. Select [5] Start Service" -ForegroundColor Gray
                Write-Host ""
                Write-Host "  Format: Year/yyyymmdd_Location/*.jpg" -ForegroundColor Gray
                Write-Host ""
                Write-Host "  GitHub: https://github.com/jiangyuyi/wingscribe" -ForegroundColor Gray
                Write-Host ""
                Pause-Host
            }
            "7" { Write-Host ""; Write-Host "  Goodbye!"; Write-Host ""; exit 0 }
            default { Log-Error "Invalid option"; Start-Sleep -Seconds 1 }
        }
    }
}

try { Invoke-Main } catch {
    Log-Error "Error: $_"
    Write-Host ""
    Write-Host "Press Enter to exit..." -ForegroundColor Gray
    Read-Host
    exit 1
}
