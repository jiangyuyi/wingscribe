#!/bin/bash
#===============================================================================
# WingScribe 一键部署脚本 - Linux/macOS/WSL
#===============================================================================

# 确保在项目根目录运行
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$(dirname "${SCRIPT_DIR}")" && pwd)"

# 配置变量
GITEE_MIRROR="https://gitee.com/jiangyuyi/wingscribe.git"
GITHUB_ORIGIN="https://github.com/jiangyuyi/wingscribe.git"
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
GRAY='\033[0;90m'
NC='\033[0m'

#===============================================================================
# 工具函数
#===============================================================================

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

get_os_type() {
    case "$(uname -s)" in
        Linux*)     echo "linux";;
        Darwin*)    echo "macos";;
        CYGWIN*|MINGW*|MSYS*) echo "windows";;
        *)          echo "unknown";;
    esac
}

is_windows() { [ "$(get_os_type)" = "windows" ]; }
is_macos()   { [ "$(get_os_type)" = "macos" ]; }
is_linux()   { [ "$(get_os_type)" = "linux" ]; }

pause() {
    printf "${GRAY}按 Enter 继续...${NC}\n"
    read -r
}

ask_input() {
    local prompt="$1"
    local default="${2:-}"
    local result=""

    # WSL2 兼容：使用 -u 0 明确从 stdin 读取
    if [ -n "$default" ]; then
        printf "${CYAN}%s${NC} [%s]: " "$prompt" "$default" >&2
    else
        printf "${CYAN}%s${NC}: " "$prompt" >&2
    fi

    # 使用 -u 0 从 stdin 读取，明确使用文件描述符
    if IFS= read -r result < /dev/stdin; then
        # 去除所有空白字符
        result=$(printf '%s' "$result" | tr -d '[:space:]')
        [ -z "$result" ] && result="$default"
    else
        result="$default"
    fi

    # 输出结果（追加换行）
    echo "$result"
}

ask_yes_no() {
    local prompt="$1"
    local default="${2:-y}"
    while true; do
        local answer
        local suffix
        if [ "$default" = "y" ]; then
            suffix="[Y/n]"
        else
            suffix="[y/N]"
        fi
        # 输出到 stderr，避免影响 stdin
        printf "${CYAN}%s ${suffix}: " "$prompt" >&2
        # 明确从 /dev/stdin 读取
        if IFS= read -r answer < /dev/stdin; then
            answer=$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')
            [ -z "$answer" ] && answer="$default"
        else
            answer="$default"
        fi
        case "$answer" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
        esac
    done
}

ensure_directory() {
    local path="$1"
    if [ ! -d "$path" ]; then
        mkdir -p "$path" 2>/dev/null
    fi
}

#===============================================================================
# 日志函数
#===============================================================================

log_info()   { printf "${GREEN}[INFO]   ${NC}%s\n" "$1"; }
log_warn()   { printf "${YELLOW}[WARN]   ${NC}%s\n" "$1"; }
log_error()  { printf "${RED}[ERROR]  ${NC}%s\n" "$1" >&2; }
log_step()   { printf "${CYAN}[STEP]   ${NC}%s\n" "$1"; }
log_success(){ printf "${GREEN}[OK]     ${NC}%s\n" "$1"; }

#===============================================================================
# 检测函数
#===============================================================================

test_git() {
    if command_exists git; then
        local version=$(git --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
        log_info "Git installed: $version"
        return 0
    fi
    log_warn "Git not found"
    return 1
}

test_python() {
    for cmd in python3.11 python3 python; do
        if command_exists "$cmd"; then
            local version=$($cmd --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
            local major=$($cmd -c "import sys; print(sys.version_info.major)" 2>/dev/null)
            local minor=$($cmd -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
            if [ "$major" = "3" ] && [ "$minor" -ge 8 ]; then
                log_info "Python installed: $version ($cmd)"
                PYTHON_CMD="$cmd"
                return 0
            fi
        fi
    done
    log_warn "Python 3.8+ not found"
    return 1
}

test_exiftool() {
    if command_exists exiftool; then
        local version=$(exiftool -ver 2>/dev/null)
        log_info "ExifTool installed: $version"
        return 0
    fi
    log_warn "ExifTool not found"
    return 1
}

test_gpu() {
    if command_exists nvidia-smi; then
        local gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        if [ -n "$gpu" ]; then
            log_info "GPU detected: $gpu"
            HAS_GPU=true
            return 0
        fi
    fi
    log_warn "No NVIDIA GPU detected, will use CPU"
    HAS_GPU=false
    return 1
}

test_cuda() {
    CUDA_STATUS="CUDA not detected"
    CUDA_VERSION=""
    DRIVER_VERSION=""

    # 检测 NVIDIA 驱动
    if command_exists nvidia-smi; then
        DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ')
        log_info "NVIDIA Driver: $DRIVER_VERSION"
    fi

    # 检测 CUDA (nvcc)
    if command_exists nvcc; then
        CUDA_VERSION=$(nvcc --version 2>/dev/null | grep "release" | awk '{print $5}' | tr -d ',' | head -1)
        CUDA_STATUS="CUDA $CUDA_VERSION ready"
        log_info "CUDA Toolkit: $CUDA_VERSION"
        return 0
    else
        log_warn "CUDA Toolkit (nvcc) not found"
    fi

    return 1
}

get_cuda_info() {
    if test_cuda 2>/dev/null; then
        echo "$CUDA_STATUS (Driver: $DRIVER_VERSION)"
    else
        echo "Not installed (CPU mode recommended)"
    fi
}

#===============================================================================
# 安装函数
#===============================================================================

install_apt_package() {
    local package="$1"
    log_info "Installing $package..."
    sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -3 || true
    sudo apt-get install -y "$package" 2>&1 | grep -v "^Selecting" | grep -v "^Preparing" | head -10
}

install_git() {
    log_step "Installing Git..."
    if is_macos && command_exists brew; then
        log_info "Using brew..."
        brew install git
    elif command_exists apt-get; then
        install_apt_package "git"
    elif command_exists yum; then
        sudo yum install -y git
    elif command_exists dnf; then
        sudo dnf install -y git
    else
        log_error "Cannot install Git automatically"
        log_info "Download: https://npm.taobao.org/mirrors/git-for-windows"
        return 1
    fi
    test_git
}

install_python() {
    log_step "Installing Python 3.11..."

    if is_macos && command_exists brew; then
        log_info "Using brew..."
        brew install python@3.11
    elif command_exists apt-get; then
        # 先安装 python3-venv（解决虚拟环境创建问题）
        log_info "Installing Python and python3-venv..."
        sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -3 || true
        sudo apt-get install -y python3.11 python3.11-venv python3-pip 2>&1 | grep -v "^Selecting" | head -10
    elif command_exists yum; then
        sudo yum install -y python3
    elif command_exists dnf; then
        sudo dnf install -y python3
    else
        log_error "Cannot install Python automatically"
        log_info "Download: https://registry.npmmirror.com/binaries/python"
        return 1
    fi

    # 验证安装
    test_python
}

install_exiftool() {
    log_step "Installing ExifTool..."
    if is_macos && command_exists brew; then
        brew install exiftool
    elif command_exists apt-get; then
        install_apt_package "perl-image-exiftool"
    elif command_exists yum; then
        sudo yum install -y perl-Image-ExifTool
    elif command_exists dnf; then
        sudo dnf install -y perl-Image-ExifTool
    else
        log_error "Cannot install ExifTool automatically"
        log_info "Download: https://exiftool.org/ or https://gitee.com/jiangyuyi/wingscribe/releases"
        return 1
    fi
    test_exiftool
}

install_venv_if_needed() {
    # 检测 Python 版本
    local py_version=$(python3 --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
    local py_major=$(echo "$py_version" | cut -d. -f1)
    local py_minor=$(echo "$py_version" | cut -d. -f2)

    # 检查 venv 模块是否存在
    if ! python3 -c "import venv" 2>/dev/null; then
        log_warn "python3-venv not found, attempting to install..."

        local pkg_name="python${py_major}.${py_minor}-venv"

        if command_exists apt-get; then
            log_info "Installing $pkg_name..."
            sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -3 || true
            sudo apt-get install -y "$pkg_name" 2>&1 | grep -v "^Selecting" | head -5
        elif command_exists yum; then
            sudo yum install -y python3-venv
        elif command_exists dnf; then
            sudo dnf install -y python3-venv
        fi

        # 验证安装
        if ! python3 -c "import venv" 2>/dev/null; then
            log_error "Failed to install python3-venv"
            log_info "Please run: sudo apt-get install $pkg_name"
            return 1
        fi
        log_success "python3-venv installed"
    fi
}

install_python_deps() {
    log_step "Installing Python dependencies..."

    if [ -z "$PYTHON_CMD" ]; then
        log_error "Python not found"
        return 1
    fi

    local venv_path="${PROJECT_ROOT}/venv"
    local pip_cmd=""

    # 创建虚拟环境前确保 venv 支持
    if [ ! -d "$venv_path" ]; then
        log_info "Creating virtual environment..."
        install_venv_if_needed

        # 使用 python3.11 确保版本正确
        if command_exists python3.11; then
            python3.11 -m venv "$venv_path"
        else
            $PYTHON_CMD -m venv "$venv_path"
        fi

        if [ $? -ne 0 ]; then
            log_error "Failed to create virtual environment"
            log_info "Try: sudo apt-get install python3.11-venv"
            return 1
        fi
    fi

    # 确定 pip 命令
    pip_cmd="${venv_path}/bin/pip"

    # 配置 pip 镜像
    log_info "Configuring pip mirror..."
    $pip_cmd config set global.index-url "$PIP_MIRROR" 2>/dev/null || true

    # 升级 pip
    log_info "Upgrading pip..."
    $pip_cmd install --upgrade pip 2>&1 | grep -v "Requirement already" || true

    # 安装依赖
    local requirements="${PROJECT_ROOT}/requirements.txt"
    if [ -f "$requirements" ]; then
        log_info "Installing requirements.txt..."
        log_info "Downloading and installing packages... (this may take several minutes)"

        $pip_cmd install -r "$requirements" --progress-bar on 2>&1 | grep -v "Requirement already" || true
        log_success "Python dependencies installed"
    else
        log_warn "requirements.txt not found"
    fi
}

#===============================================================================
# CUDA 安装
#===============================================================================

show_cuda_download_links() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${WHITE}CUDA Download Links${NC}                        ${CYAN}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
    echo -e "  ${GREEN}1. CUDA Toolkit 12.1 (Required)${NC}"
    echo -e "     https://developer.nvidia.com/cuda-downloads"
    echo -e "     Select: Linux > x86_64 > 12 > runfile (local)"
    echo ""
    echo -e "  ${GREEN}2. cuDNN 8.9 (Required for PyTorch)${NC}"
    echo -e "     https://developer.nvidia.com/rdp/cudnn-download"
    echo -e "     Select: cuDNN v8.9.x for CUDA 12.x > Linux"
    echo ""
    echo -e "  ${WHITE}Installation steps:${NC}"
    echo -e "     1. Run CUDA Toolkit installer"
    echo -e "     2. Extract cuDNN to /usr/local/cuda"
    echo -e "     3. Add to ~/.bashrc: export PATH=/usr/local/cuda/bin:\$PATH"
    echo -e "     4. Restart terminal"
    echo ""

    if ask_yes_no "Open CUDA download page?" "n"; then
        if command_exists xdg-open; then
            xdg-open "https://developer.nvidia.com/cuda-downloads" 2>/dev/null &
        fi
    fi
}

install_cuda_auto() {
    log_step "Auto-installing CUDA Toolkit 12.1..."

    # 检查是否是 root 用户
    if [ "$EUID" -ne 0 ]; then
        log_warn "CUDA installation requires root privileges"
        log_info "Please run: sudo bash $0 cuda"
        return 1
    fi

    # 检测系统版本和架构
    local os_version=""
    local os_arch=$(uname -m)
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        os_version="$ID"
        # 清理版本号（如 "ubuntu" -> "ubuntu", "22.04" -> "2204"）
        os_version="${os_version// /}"
    fi

    # 对于 WSL2，检测是否在 WSL 环境中
    local is_wsl=false
    if grep -qi "microsoft" /proc/version 2>/dev/null; then
        is_wsl=true
        log_info "Detected WSL2 environment"
    fi

    log_info "System: $os_version ($os_arch)"

    # 根据系统类型选择安装方法
    if [ "$is_wsl" = true ]; then
        # WSL2 环境：推荐使用 APT 安装
        install_cuda_apt
    else
        # 原生 Linux：使用 runfile 安装
        install_cuda_runfile
    fi
}

install_cuda_apt() {
    log_info "Installing CUDA via APT repository..."

    # 检测 Ubuntu 版本并设置仓库路径
    local ubuntu_codename=""
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        ubuntu_codename="$VERSION_CODENAME"
    fi

    if [ -z "$ubuntu_codename" ]; then
        # 尝试从 lsb-release 获取
        if command_exists lsb_release; then
            ubuntu_codename=$(lsb_release --codename --short 2>/dev/null)
        fi
    fi

    if [ -z "$ubuntu_codename" ]; then
        log_error "Cannot determine Ubuntu codename"
        log_info "Please run: sudo apt-get install nvidia-cuda-toolkit"
        return 1
    fi

    log_info "Ubuntu codename: $ubuntu_codename"

    # 添加 NVIDIA CUDA 仓库
    log_info "Adding NVIDIA CUDA repository..."

    # 下载并安装 CUDA 密钥环
    local keyring_path="/usr/share/keyrings/cuda-archive-keyring.gpg"
    local keyring_url="https://developer.download.nvidia.com/compute/cuda/repositories/ubuntu${ubuntu_codename}/x86_64/cuda-keyring_1.1-1_all.deb"

    log_info "Downloading CUDA keyring..."
    if ! curl -fsSL -o /tmp/cuda-keyring.deb "$keyring_url"; then
        log_error "Failed to download CUDA keyring"
        log_info "Trying alternative method..."
        # 备用方案：使用 ubuntu cuda-toolkit 仓库
        sudo apt-get install -y software-properties-common 2>/dev/null || true
        sudo add-apt-repository -y "deb [arch=amd64] https://archive.ubuntu.com/ubuntu/ ${ubuntu_codename} multiverse" 2>/dev/null || true
    else
        log_success "Downloaded CUDA keyring"
        sudo dpkg -i /tmp/cuda-keyring.deb
        rm -f /tmp/cuda-keyring.deb
    fi

    # 更新并安装 CUDA
    log_info "Installing CUDA toolkit..."
    sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -5 || true
    sudo apt-get install -y cuda-toolkit-12-1 2>&1 | grep -v "^Selecting" | head -20

    # 验证安装
    if command_exists nvcc; then
        local cuda_version=$(nvcc --version | grep "release" | awk '{print $5}')
        log_success "CUDA $cuda_version installed successfully"
        log_info "Add to PATH: export PATH=/usr/local/cuda/bin:\$PATH"
        return 0
    else
        # 备用：尝试安装 nvidia-cuda-toolkit
        log_warn "CUDA toolkit not found, trying alternative package..."
        sudo apt-get install -y nvidia-cuda-toolkit 2>&1 | tail -5

        if command_exists nvcc; then
            log_success "CUDA installed via nvidia-cuda-toolkit"
            return 0
        fi
    fi

    log_error "CUDA installation failed"
    log_info "Please install manually: sudo apt-get install nvidia-cuda-toolkit"
    return 1
}

install_cuda_runfile() {
    log_info "Installing CUDA via runfile..."

    # 检测系统版本和架构
    local os_version=""
    local os_arch=$(uname -m)
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        os_version="$ID"
    fi

    # 根据系统确定 CUDA 版本和下载 URL
    local cuda_version="12.1.1"
    local cuda_build="530.30.02"
    local cuda_installer=""
    local download_url=""

    # 根据系统和架构选择正确的安装包
    case "$os_version" in
        ubuntu)
            case "$os_arch" in
                x86_64)
                    cuda_installer="cuda_12.1.1_530.30.02_linux_64.x86_64.run"
                    ;;
                aarch64|arm64)
                    cuda_installer="cuda_12.1.1_530.30.02_linux_64.aarch64.run"
                    ;;
            esac
            ;;
        debian)
            case "$os_arch" in
                x86_64)
                    cuda_installer="cuda_12.1.1_530.30.02_linux_64.x86_64.run"
                    ;;
            esac
            ;;
        *)
            cuda_installer="cuda_12.1.1_530.30.02_linux_64.x86_64.run"
            ;;
    esac

    # 尝试多个可能的下载 URL
    local urls=(
        "https://developer.download.nvidia.com/compute/cuda/repositories/ubuntu2204/x86_64/${cuda_installer}"
        "https://developer.download.nvidia.com/compute/cuda/repositories/ubuntu2004/x86_64/${cuda_installer}"
        "https://developer.download.nvidia.com/compute/cuda/repositories/ubuntu2404/x86_64/${cuda_installer}"
    )

    local installer_path="/tmp/${cuda_installer}"
    local download_success=false

    for url in "${urls[@]}"; do
        log_info "Trying: $url"
        if curl -fsSL -o "$installer_path" "$url" 2>/dev/null; then
            local file_size=$(stat -c%s "$installer_path" 2>/dev/null || echo "0")
            if [ "$file_size" -gt 1000000 ]; then  # 至少 1MB
                download_success=true
                log_success "Downloaded from: $url"
                break
            fi
        fi
    done

    if [ "$download_success" = false ]; then
        log_error "Failed to download CUDA installer"
        log_info "Please download manually from:"
        log_info "  https://developer.nvidia.com/cuda-downloads"
        log_info "  Select: Linux > x86_64 > 12 > runfile (local)"
        return 1
    fi

    log_info "Installing CUDA (this may take several minutes)..."
    chmod +x "$installer_path"

    # 静默安装，只安装 toolkit
    if $installer_path --silent --toolkit --override 2>&1; then
        log_success "CUDA installed successfully"

        # 添加到 PATH
        if [ -d "/usr/local/cuda-12.1/bin" ]; then
            echo 'export PATH="/usr/local/cuda-12.1/bin:$PATH"' >> /root/.bashrc
            log_info "Added CUDA to PATH in /root/.bashrc"
        fi

        if [ -d "/usr/local/cuda/bin" ]; then
            echo 'export PATH="/usr/local/cuda/bin:$PATH"' >> /root/.bashrc
        fi

        log_success "Please restart terminal or run: source /root/.bashrc"
        return 0
    else
        log_error "CUDA installation failed"
        return 1
    fi
}

install_cuda() {
    log_step "Checking CUDA environment..."

    # WSL2 中 GPU 检测必须在普通用户下进行（不能使用 sudo）
    # 先检测 GPU（WSL2 需要普通用户访问 Windows 驱动）
    test_gpu
    if [ "$HAS_GPU" = "true" ]; then
        log_info "GPU detected: $gpu"
    else
        log_warn "No NVIDIA GPU detected"
    fi

    # 检测 CUDA
    if test_cuda; then
        log_success "CUDA environment ready"
        return 0
    fi

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${WHITE}CUDA Installation${NC}                              ${CYAN}"
    echo -e "${CYAN}========================================${NC}"
    echo ""

    # 根据 GPU 状态显示不同信息
    if [ "$HAS_GPU" = "true" ]; then
        echo -e "  GPU detected but CUDA Toolkit not installed."
        echo -e "  CUDA is required for GPU acceleration."
    else
        echo -e "  No GPU detected or CUDA not installed."
    fi
    echo ""
    echo -e "  ${GREEN}Option 1:${NC} Install CUDA Toolkit 12.1 (auto)"
    echo -e "  ${GREEN}Option 2:${NC} Show download links"
    echo -e "  ${YELLOW}Option 3:${NC} Continue with CPU mode"
    echo ""

    local choice=$(ask_input "Select option" "1")
    echo ""

    case "$choice" in
        1)
            # 检查是否需要 sudo
            if [ "$EUID" -ne 0 ]; then
                log_info "CUDA installation requires root privileges"
                echo ""
                echo -e "${YELLOW}Switching to sudo for installation...${NC}"
                echo ""

                # 使用 sudo 运行 CUDA 安装
                exec sudo bash "$SCRIPT_DIR/deploy.sh" cuda_install
                return 0
            fi

            install_cuda_auto
            ;;
        2)
            show_cuda_download_links
            ;;
        3)
            log_warn "Continuing with CPU mode"
            return 1
            ;;
        *)
            log_error "Invalid choice"
            return 1
            ;;
    esac
}

#===============================================================================
# 项目获取
#===============================================================================

get_project() {
    log_step "Getting project..."

    # 检查是否是 git 仓库
    if [ -d "${PROJECT_ROOT}/.git" ]; then
        log_info "Git repository found"

        # 获取当前远程 URL
        local remoteUrl=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null)

        # 如果是 GitHub，切换到 Gitee
        local isGithub=false
        if [ -n "$remoteUrl" ] && [[ "$remoteUrl" == *"github.com"* ]]; then
            log_info "Using Gitee mirror for fast update..."
            git -C "$PROJECT_ROOT" remote set-url origin "$GITEE_MIRROR" 2>/dev/null
            isGithub=true
        fi

        log_info "Updating project..."
        git -C "$PROJECT_ROOT" pull origin master 2>/dev/null
        local pullStatus=$?

        # 如果原先是 GitHub，改回去
        if [ "$isGithub" = true ]; then
            log_info "Restoring remote to GitHub..."
            git -C "$PROJECT_ROOT" remote set-url origin "$GITHUB_ORIGIN" 2>/dev/null
        fi

        if [ $pullStatus -eq 0 ]; then
            log_success "Project updated"
            return 0
        else
            log_warn "Update failed, using existing files"
            return 0
        fi
    fi

    # 检查是否有项目文件
    if [ -f "${PROJECT_ROOT}/settings.yaml" ]; then
        log_success "Project files found"
        return 0
    fi

    # 检查 src/ 目录
    if [ -d "${PROJECT_ROOT}/src" ] && [ -f "${PROJECT_ROOT}/requirements.txt" ]; then
        log_success "Project files found"
        return 0
    fi

    # 检查目录是否非空（排除脚本文件）
    local items=$(ls -A "$PROJECT_ROOT" 2>/dev/null | grep -v ".git" | grep -v "deploy.sh" | grep -v "deploy.ps1")
    if [ -n "$items" ]; then
        log_warn "Found existing files but no project detected"

        # 备份用户文件
        local backupDir="${HOME}/wingscribe_backup_$(date +%Y%m%d_%H%M%S)"
        log_info "Backing up your files to: $backupDir"

        mkdir -p "$backupDir"
        for item in $items; do
            [ "$item" != ".git" ] && [ "$item" != "deploy.sh" ] && [ "$item" != "deploy.ps1" ] && \
            [ "$item" != "deploy.ps1.bin" ] && cp -r "$item" "$backupDir/" 2>/dev/null
        done
        log_success "Backup complete"
    fi

    # 优先从 Gitee 克隆
    log_info "Cloning from Gitee..."
    local cloneSuccess=false
    local lastError=""

    local tempDir="/tmp/wingscribe_clone_$$"
    mkdir -p "$tempDir"

    # 尝试 Gitee
    log_info "Trying Gitee..."
    if git clone --depth 1 "$GITEE_MIRROR" "$tempDir" 2>&1; then
        if [ -f "${tempDir}/requirements.txt" ]; then
            # 自动改回 GitHub
            git -C "$tempDir" remote set-url origin "$GITHUB_ORIGIN" 2>/dev/null
            cloneSuccess=true
        else
            lastError="Clone succeeded but requirements.txt not found"
        fi
    else
        lastError=$(git clone --depth 1 "$GITEE_MIRROR" "$tempDir" 2>&1)
    fi

    # 尝试 GitHub（如果 Gitee 失败）
    if [ "$cloneSuccess" = false ]; then
        log_warn "Gitee clone failed, trying GitHub..."
        rm -rf "$tempDir"
        mkdir -p "$tempDir"

        if git clone --depth 1 "$GITHUB_ORIGIN" "$tempDir" 2>&1; then
            if [ -f "${tempDir}/requirements.txt" ]; then
                cloneSuccess=true
            else
                lastError="Clone succeeded but requirements.txt not found"
            fi
        else
            lastError=$(git clone --depth 1 "$GITHUB_ORIGIN" "$tempDir" 2>&1)
        fi
    fi

    if [ "$cloneSuccess" = true ]; then
        log_info "Moving files to project directory..."

        # 移动文件到目标目录
        for item in "${tempDir}"/*; do
            local basename=$(basename "$item")
            [ "$basename" != ".git" ] && cp -r "$item" "$PROJECT_ROOT/" 2>/dev/null
        done

        # 清理临时目录
        rm -rf "$tempDir"

        # 验证文件已移动
        if [ -f "${PROJECT_ROOT}/requirements.txt" ]; then
            log_success "Project cloned successfully"
            return 0
        else
            log_error "Clone verification failed: requirements.txt not found in destination"
        fi
    fi

    # Clone 失败
    log_error "Clone failed!"
    log_error "Details: $lastError"
    echo ""
    echo -e "${YELLOW}Possible solutions:${NC}"
    echo -e "  1. Check internet connection"
    echo -e "  2. Install Git: sudo apt-get install git"
    echo -e "  3. Or manually clone: git clone https://gitee.com/jiangyuyi/wingscribe.git ."
    echo ""

    return 1
}

#===============================================================================
# 配置向导
#===============================================================================

invoke_config_wizard() {
    log_step "Configuring project..."
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${WHITE}Configuration Wizard${NC}                         ${CYAN}"
    echo -e "${CYAN}========================================${NC}"
    echo ""

    # 1. 照片源目录
    echo -e "  ${CYAN}1/3 Photo source directory${NC}"
    echo -e "  ${GRAY}Enter the directory containing your bird photos${NC}"
    echo -e "  ${GRAY}Format: Year/yyyymmdd_Location/*.jpg${NC}"
    echo ""

    local default_source_dir="$HOME/Pictures"
    if is_macos; then
        default_source_dir="$HOME/Pictures"
    elif is_linux; then
        default_source_dir="$HOME/图片"
    fi

    local source_dir=$(ask_input "Photo directory" "$default_source_dir")
    if [ ! -d "$source_dir" ]; then
        if ask_yes_no "Directory does not exist, create it?"; then
            mkdir -p "$source_dir" 2>/dev/null
            log_success "Created: $source_dir"
        fi
    fi

    echo ""

    # 2. 输出目录
    echo -e "  ${CYAN}2/3 Output directory${NC}"
    local output_dir=$(ask_input "Output directory" "${PROJECT_ROOT}/data/processed")
    ensure_directory "$output_dir"

    echo ""

    # 3. 处理设备
    echo -e "  ${CYAN}3/3 Processing device${NC}"
    test_gpu

    if [ "$HAS_GPU" = "true" ]; then
        echo -e "  ${GREEN}GPU detected, CUDA recommended${NC}"
        echo -e "  $(get_cuda_info)"
        echo ""
        echo -e "  ${WHITE}Options:${NC}"
        echo "    1. auto   - Auto detect (recommended)"
        echo "    2. cuda   - Use GPU (requires CUDA)"
        echo "    3. cpu    - Use CPU (slower)"
        echo ""

        local choice=$(ask_input "Device" "1")
        case "$choice" in
            1) DEVICE="auto" ;;
            2)
                DEVICE="cuda"
                install_cuda || DEVICE="cpu"
                ;;
            3) DEVICE="cpu" ;;
            *) DEVICE="auto" ;;
        esac
    else
        echo -e "  ${YELLOW}No GPU detected, will use CPU${NC}"
        DEVICE="cpu"
    fi

    echo ""
    log_step "Generating config files..."

    # 生成 settings.yaml
    local config_path="${PROJECT_ROOT}/config/settings.yaml"
    ensure_directory "$(dirname "$config_path")"

    cat > "$config_path" << EOF
# WingScribe config
# Generated by deploy script

paths:
  allowed_roots:
    - "${source_dir//\\/\\\\}"
  references_path: "data/references"
  sources:
    - path: "${source_dir//\\/\\\\}"
      recursive: true
      enabled: true
  output:
    root_dir: "${output_dir//\\/\\\\}"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false
  db_path: "data/db/wingscribe.db"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
  model_cache_dir: "data/models"
processing:
  device: "$DEVICE"
  yolo_model: "yolov8n.pt"
  confidence_threshold: 0.5
  blur_threshold: 40.0
  target_size: 640
  crop_padding: 200
recognition:
  mode: "local"
  region_filter: "auto"
  top_k: 5
  alternatives_threshold: 70
  low_confidence_threshold: 60
  local:
    model_type: "bioclip-2"
    batch_size: 512
    inference_batch_size: 16
web:
  host: "0.0.0.0"
  port: 8000
EOF

    log_success "Config generated: $config_path"

    # 生成 secrets.yaml
    local secrets_path="${PROJECT_ROOT}/config/secrets.yaml"
    if [ ! -f "$secrets_path" ]; then
        cat > "$secrets_path" << 'EOF'
# WingScribe secrets
hf_api_key: ""
dongniao_api_key: ""
EOF
        log_success "Secrets generated: $secrets_path"
    fi

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${WHITE}Configuration Summary${NC}                        ${CYAN}"
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  Source:  ${WHITE}$source_dir${NC}"
    echo -e "${CYAN}  Output:  ${WHITE}$output_dir${NC}"
    echo -e "${CYAN}  Device:  ${WHITE}$DEVICE${NC}"
    echo -e "${CYAN}========================================${NC}"
}

#===============================================================================
# Web 服务
#===============================================================================

start_web_server() {
    log_step "Starting Web server..."

    local venv_python="${PROJECT_ROOT}/venv/bin/python"
    local web_script="${PROJECT_ROOT}/src/web/app.py"

    if [ ! -f "$venv_python" ]; then
        log_error "Virtual environment not found!"
        log_info "Please run '$0 deploy' first"
        return 1
    fi

    if [ ! -f "$web_script" ]; then
        log_error "Web script not found: $web_script"
        return 1
    fi

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${GREEN}Starting Web server...${NC}                        ${CYAN}"
    echo -e "${CYAN}  URL: ${WHITE}http://localhost:8000${NC}                    ${CYAN}"
    echo -e "${CYAN}  Press ${WHITE}Ctrl+C${NC} to stop                          ${CYAN}"
    echo -e "${CYAN}========================================${NC}"
    echo ""

    cd "$PROJECT_ROOT"
    "$venv_python" "$web_script"
}

#===============================================================================

#===============================================================================
# 使用说明
#===============================================================================

show_help() {
    cat << EOF
========================================
  WingScribe Deployment
========================================
  AI Bird Photo Management
========================================

Usage:
  $0 [command]

Commands:
  deploy           Full deployment (install + config)
  install          Install dependencies only
  config           Configuration wizard
  update           Update project
  cuda             Install CUDA (GPU support)
  web              Start Web server
  help             Show this help

Examples:
  $0 deploy           # Full deployment
  $0 config           # Configure only
  $0 web              # Start Web service
  $0 cuda             # Install CUDA

Quick Start:
  1. Run: $0 deploy
  2. Configure photo directory
  3. Run: $0 web
  4. Open: http://localhost:8000

EOF
}

#===============================================================================
# 主入口
#===============================================================================

main() {
    cd "$PROJECT_ROOT"

    local command="${1:-help}"

    case "$command" in
        deploy|d)
            echo ""
            echo -e "${CYAN}========================================${NC}"
            echo -e "${CYAN}  ${GREEN}Deployment${NC}                                    ${CYAN}"
            echo -e "${CYAN}========================================${NC}"
            echo ""

            log_step "1/4 Checking environment..."
            test_git || true
            test_python || log_error "Python installation recommended"
            test_exiftool || log_warn "ExifTool not found"
            test_gpu

            log_step "2/4 Installing dependencies..."
            if ! command_exists git; then
                if ask_yes_no "Install Git?"; then install_git; fi
            fi
            if ! test_python; then
                if ask_yes_no "Install Python?"; then install_python; fi
            fi
            if ! command_exists exiftool; then
                if ask_yes_no "Install ExifTool?"; then install_exiftool; fi
            fi

            log_step "3/4 Getting project..."
            if ! get_project; then
                log_error "Failed to get project from git"
                echo ""
                echo -e "${YELLOW}Please manually clone the project:${NC}"
                echo "  git clone https://gitee.com/jiangyuyi/wingscribe.git ."
                echo ""
                if ! ask_yes_no "Continue without project files?" "n"; then
                    exit 1
                fi
            fi

            # 验证 requirements.txt 存在
            if [ ! -f "${PROJECT_ROOT}/requirements.txt" ]; then
                log_error "requirements.txt not found!"
                exit 1
            fi

            log_step "4/4 Installing Python dependencies..."
            install_python_deps

            invoke_config_wizard

            echo ""
            log_success "Deployment complete!"
            echo ""
            echo -e "${WHITE}Next steps:${NC}"
            echo "  1. Run: $0 web"
            echo "  2. Open: http://localhost:8000"
            echo ""
            ;;
        install|i)
            echo ""
            echo -e "${CYAN}========================================${NC}"
            echo -e "${CYAN}  ${WHITE}Install Dependencies${NC}                         ${CYAN}"
            echo -e "${CYAN}========================================${NC}"
            echo ""

            # 验证 requirements.txt 存在
            if [ ! -f "${PROJECT_ROOT}/requirements.txt" ]; then
                log_error "requirements.txt not found!"
                log_info "Please run 'git clone' first or ensure you are in the project directory"
                exit 1
            fi

            log_step "Installing system dependencies..."
            if ! command_exists git; then install_git || true; fi
            if ! test_python; then install_python || true; fi
            if ! command_exists exiftool; then install_exiftool || true; fi

            log_step "Installing Python dependencies..."
            install_python_deps

            log_success "Dependencies installed"
            ;;
        config|c)
            invoke_config_wizard
            ;;
        update|u)
            echo ""
            echo -e "${CYAN}========================================${NC}"
            echo -e "${CYAN}  ${WHITE}Update Project${NC}                               ${CYAN}"
            echo -e "${CYAN}========================================${NC}"
            echo ""
            get_project
            ;;
        cuda|cuda_install)
            echo ""
            echo -e "${CYAN}========================================${NC}"
            echo -e "${CYAN}  ${GREEN}CUDA Installation${NC}                            ${CYAN}"
            echo -e "${CYAN}========================================${NC}"
            echo ""

            install_cuda
            ;;
        web|w)
            start_web_server
            ;;
        help|-h|--help|"")
            show_help
            ;;
        *)
            log_error "Unknown command: $command"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"
