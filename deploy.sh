#!/bin/bash
#===============================================================================
# WingScribe Deployment Script - Linux/macOS/WSL
#===============================================================================

# 确保在项目根目录运行
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

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

# 全局变量
PYTHON_CMD=""
HAS_GPU=false
CUDA_VERSION=""
DRIVER_VERSION=""

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
    printf "${GRAY}Press Enter to continue...${NC}\n"
    read -r
}

ask_input() {
    local prompt="$1"
    local default="${2:-}"
    local result=""

    if [ -n "$default" ]; then
        printf "${CYAN}%s${NC} [%s]: " "$prompt" "$default"
    else
        printf "${CYAN}%s${NC}: " "$prompt"
    fi

    if IFS= read -r result; then
        result=$(echo "$result" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        [ -z "$result" ] && result="$default"
    else
        result="$default"
    fi

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
        printf "${CYAN}%s ${suffix}: " "$prompt"
        if IFS= read -r answer; then
            answer=$(echo "$answer" | tr '[:upper:]' '[:lower:]' | sed 's/[[:space:]]*//g')
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

test_command() {
    local name="$1"
    if command_exists "$name"; then
        return 0
    fi
    return 1
}

test_git() {
    if command_exists git; then
        local version=$(git --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        log_info "Git installed: $version"
        return 0
    fi
    log_warn "Git not found"
    return 1
}

test_python() {
    # 先检测系统默认的 python3，再检测特定版本
    for cmd in python3 python python3.12 python3.11 python3.10 python3.9; do
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
    HAS_GPU=false
    if command_exists nvidia-smi; then
        local gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        if [ -n "$gpu" ]; then
            log_info "GPU detected: $gpu"
            HAS_GPU=true
            return 0
        fi
    fi
    log_warn "No NVIDIA GPU detected, will use CPU"
    return 1
}

test_cuda() {
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
        log_info "CUDA Toolkit: $CUDA_VERSION"
        return 0
    else
        log_warn "CUDA Toolkit (nvcc) not found"
    fi

    return 1
}

get_cuda_info() {
    if test_cuda 2>/dev/null; then
        echo "CUDA $CUDA_VERSION (Driver: $DRIVER_VERSION)"
    else
        echo "Not installed (CPU mode recommended)"
    fi
}

#===============================================================================
# 安装函数 - 系统依赖
#===============================================================================

install_git() {
    log_step "Installing Git..."

    # 检查是否可以使用 sudo
    local use_sudo=""
    if [ "$EUID" -ne 0 ]; then
        if sudo -n true 2>/dev/null; then
            use_sudo="sudo"
        else
            use_sudo="sudo"
        fi
    fi

    if is_macos && command_exists brew; then
        log_info "Using brew..."
        brew install git
    elif command_exists apt-get; then
        log_info "Installing via apt-get..."
        $use_sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -3 || true
        $use_sudo apt-get install -y git 2>&1 | tail -5
    elif command_exists yum; then
        $use_sudo yum install -y git
    elif command_exists dnf; then
        $use_sudo dnf install -y git
    else
        log_error "Cannot install Git automatically"
        log_info "Download: https://git-scm.com/"
        return 1
    fi
    test_git
}

install_python() {
    log_step "Installing Python..."

    # 检查是否可以使用 sudo
    local use_sudo=""
    if [ "$EUID" -ne 0 ]; then
        if sudo -n true 2>/dev/null; then
            use_sudo="sudo"
        else
            use_sudo="sudo"
        fi
    fi

    if is_macos && command_exists brew; then
        log_info "Using brew..."
        brew install python@3.11
    elif command_exists apt-get; then
        log_info "Installing Python and python3-venv..."
        $use_sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -3 || true
        # 安装系统默认的 Python3 版本
        $use_sudo apt-get install -y python3 python3-venv python3-pip 2>&1 | tail -10
    elif command_exists yum; then
        $use_sudo yum install -y python3 python3-venv
    elif command_exists dnf; then
        $use_sudo dnf install -y python3 python3-venv
    else
        log_error "Cannot install Python automatically"
        log_info "Download: https://www.python.org/downloads/"
        return 1
    fi

    test_python
}

install_exiftool() {
    log_step "Installing ExifTool..."

    # 检查是否可以使用 sudo
    local use_sudo=""
    if [ "$EUID" -ne 0 ]; then
        if sudo -n true 2>/dev/null; then
            use_sudo="sudo"
        else
            use_sudo="sudo"
        fi
    fi

    if is_macos && command_exists brew; then
        brew install exiftool
    elif command_exists apt-get; then
        log_info "Installing via apt-get..."
        $use_sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -3 || true
        $use_sudo apt-get install -y libimage-exiftool-perl 2>&1 | tail -5
    elif command_exists yum; then
        $use_sudo yum install -y perl-Image-ExifTool
    elif command_exists dnf; then
        $use_sudo dnf install -y perl-Image-ExifTool
    else
        log_error "Cannot install ExifTool automatically"
        log_info "Download: https://exiftool.org/"
        return 1
    fi
    test_exiftool
}

install_venv_if_needed() {
    local py_version=$(python3 --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
    local py_major=$(echo "$py_version" | cut -d. -f1)
    local py_minor=$(echo "$py_version" | cut -d. -f2)

    if ! python3 -c "import venv" 2>/dev/null; then
        log_warn "python3-venv not found, attempting to install..."

        local pkg_name="python${py_major}.${py_minor}-venv"
        local use_sudo=""

        # 检查是否可以使用 sudo
        if [ "$EUID" -ne 0 ]; then
            if sudo -n true 2>/dev/null; then
                use_sudo="sudo"
                log_info "Using sudo for installation..."
            else
                log_info "Requesting sudo access..."
                use_sudo="sudo"
            fi
        fi

        if command_exists apt-get; then
            log_info "Installing $pkg_name..."
            $use_sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -3 || true
            $use_sudo apt-get install -y "$pkg_name" 2>&1 | tail -5
        elif command_exists yum; then
            $use_sudo yum install -y python3-venv
        elif command_exists dnf; then
            $use_sudo dnf install -y python3-venv
        fi

        if ! python3 -c "import venv" 2>/dev/null; then
            log_error "Failed to install python3-venv"
            log_info "Please run: sudo apt-get install $pkg_name"
            return 1
        fi
        log_success "python3-venv installed"
    fi
}

#===============================================================================
# 安装函数 - CUDA
#===============================================================================

show_cuda_download_links() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${WHITE}CUDA Download Links${NC}"
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

install_cuda_apt() {
    log_info "Installing CUDA via APT repository..."

    local ubuntu_codename=""
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        ubuntu_codename="$VERSION_CODENAME"
    fi

    if [ -z "$ubuntu_codename" ]; then
        if command_exists lsb_release; then
            ubuntu_codename=$(lsb_release --codename --short 2>/dev/null)
        fi
    fi

    if [ -z "$ubuntu_codename" ]; then
        log_error "Cannot determine Ubuntu codename"
        return 1
    fi

    log_info "Ubuntu codename: $ubuntu_codename"

    # 添加 NVIDIA CUDA 仓库
    log_info "Adding NVIDIA CUDA repository..."
    local keyring_url="https://developer.download.nvidia.com/compute/cuda/repositories/ubuntu${ubuntu_codename}/x86_64/cuda-keyring_1.1-1_all.deb"

    if ! curl -fsSL -o /tmp/cuda-keyring.deb "$keyring_url" 2>/dev/null; then
        log_warn "Failed to download CUDA keyring, trying alternative..."
        sudo apt-get install -y software-properties-common 2>/dev/null || true
    else
        sudo dpkg -i /tmp/cuda-keyring.deb
        rm -f /tmp/cuda-keyring.deb
    fi

    log_info "Installing CUDA toolkit..."
    sudo apt-get update 2>&1 | grep -v "^Hit" | grep -v "^Reading" | head -5 || true
    sudo apt-get install -y cuda-toolkit-12-1 2>&1 | tail -10

    if command_exists nvcc; then
        local cuda_v=$(nvcc --version | grep "release" | awk '{print $5}')
        log_success "CUDA $cuda_v installed"
        log_info "Add to PATH: export PATH=/usr/local/cuda/bin:\$PATH"
        return 0
    fi

    log_error "CUDA installation failed"
    return 1
}

install_cuda() {
    log_step "Checking CUDA environment..."

    test_gpu
    if [ "$HAS_GPU" = "true" ]; then
        log_info "GPU detected"
    else
        log_warn "No NVIDIA GPU detected"
    fi

    if test_cuda; then
        log_success "CUDA environment ready"
        return 0
    fi

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${WHITE}CUDA Installation${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""

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
            if [ "$EUID" -ne 0 ]; then
                log_info "CUDA installation requires root privileges"
                echo ""
                echo -e "${YELLOW}Please enter password for sudo...${NC}"
                echo ""
            fi
            install_cuda_apt
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
# 安装函数 - Python 依赖
#===============================================================================

install_python_deps() {
    log_step "Installing Python dependencies..."

    if [ -z "$PYTHON_CMD" ]; then
        if ! test_python; then
            log_error "Python not found"
            return 1
        fi
    fi

    local venv_path="${PROJECT_ROOT}/venv"
    local pip_cmd=""

    # 创建虚拟环境
    if [ ! -d "$venv_path" ]; then
        log_info "Creating virtual environment..."
        install_venv_if_needed

        # 使用检测到的 Python 版本创建虚拟环境
        $PYTHON_CMD -m venv "$venv_path"

        if [ $? -ne 0 ]; then
            log_error "Failed to create virtual environment"
            return 1
        fi
    fi

    # 确定 pip 命令
    if [ -f "${venv_path}/bin/pip" ]; then
        pip_cmd="${venv_path}/bin/pip"
    elif [ -f "${venv_path}/bin/pip3" ]; then
        pip_cmd="${venv_path}/bin/pip3"
    else
        log_error "pip not found in virtual environment!"
        return 1
    fi

    # 配置 pip 镜像
    log_info "Configuring pip mirror..."
    $pip_cmd config set global.index-url "$PIP_MIRROR" 2>/dev/null || true

    # 升级 pip
    log_info "Upgrading pip..."
    $pip_cmd install --upgrade pip 2>&1 | tail -3 || true

    # 检测 GPU
    local has_gpu=false
    local gpu_name=""
    local needs_nightly=false

    if command_exists nvidia-smi; then
        gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        if [ -n "$gpu_name" ]; then
            has_gpu=true
            log_info "GPU detected: $gpu_name"

            # 检测 RTX 50/60/70/80/90 系列
            if echo "$gpu_name" | grep -qiE "RTX[[:space:]]*[5-9][0-9]|GeForce[[:space:]]*[5-9][0-9]"; then
                needs_nightly=true
                log_warn "Detected newer GPU: $gpu_name - will try nightly PyTorch"
            fi
        fi
    fi

    # 先安装 CPU 版本保底
    if [ "$has_gpu" = true ]; then
        log_info "Installing CPU PyTorch as fallback..."
        $pip_cmd install torch torchvision torchaudio 2>&1 | tail -3 || true
    fi

    # 根据 GPU 类型选择 PyTorch 版本
    if [ "$has_gpu" = true ]; then
        local torch_index_url=""
        if [ "$needs_nightly" = true ]; then
            torch_index_url="https://download.pytorch.org/whl/nightly/cu128"
            log_info "Installing nightly PyTorch with CUDA 12.8 for RTX 50 series..."
        else
            torch_index_url="https://download.pytorch.org/whl/cu121"
            log_info "Installing stable CUDA PyTorch..."
        fi

        # 卸载旧版本
        log_info "Uninstalling any existing PyTorch..."
        $pip_cmd uninstall -y torch torchvision torchaudio 2>/dev/null || true
        $pip_cmd cache purge 2>/dev/null || true

        # 清除镜像配置
        log_info "Clearing pip config..."
        $pip_cmd config unset global.index-url 2>/dev/null || true
        $pip_cmd config unset global.extra-index-url 2>/dev/null || true

        log_info "Installing CUDA PyTorch..."
        log_info "Using index: $torch_index_url"

        if $pip_cmd install torch torchvision --index-url "$torch_index_url" --no-cache-dir 2>&1; then
            log_success "CUDA PyTorch installed"
        else
            log_warn "CUDA PyTorch install failed"

            # 如果不是 nightly，尝试 nightly
            if [ "$needs_nightly" = false ]; then
                log_info "Trying nightly version..."
                torch_index_url="https://download.pytorch.org/whl/nightly/cu128"

                if $pip_cmd install torch torchvision --index-url "$torch_index_url" --no-cache-dir 2>&1; then
                    log_success "Nightly CUDA PyTorch installed"
                fi
            fi

            # 检查是否安装成功，否则回退到 CPU
            if ! $pip_cmd show torch 2>/dev/null | grep -q "Name: torch"; then
                log_warn "Using CPU PyTorch instead"
                $pip_cmd install torch torchvision torchaudio 2>&1 | tail -3 || true
            fi
        fi
    else
        log_info "No CUDA detected, installing CPU PyTorch..."
        $pip_cmd install torch torchvision torchaudio 2>&1 | tail -3 || true
    fi

    # 安装其他依赖
    local requirements="${PROJECT_ROOT}/requirements.txt"
    if [ -f "$requirements" ]; then
        # 临时过滤 torch
        local temp_req="/tmp/wingscribe_req_$$.txt"
        grep -v "^torch" "$requirements" > "$temp_req" || cp "$requirements" "$temp_req"

        log_info "Installing other dependencies..."
        $pip_cmd install -r "$temp_req" 2>&1 | tail -10

        rm -f "$temp_req"
        log_success "Python dependencies installed"
    else
        log_warn "requirements.txt not found"
    fi
}

reinstall_pytorch() {
    log_step "Reinstalling PyTorch..."

    local venv_path="${PROJECT_ROOT}/venv"
    local pip_cmd=""

    if [ -f "${venv_path}/bin/pip" ]; then
        pip_cmd="${venv_path}/bin/pip"
    else
        log_error "Virtual environment not found!"
        log_info "Please run '$0 install' first"
        return 1
    fi

    # 显示当前版本
    log_info "Current PyTorch:"
    $pip_cmd show torch 2>/dev/null | grep -E "^Version:|^CUDA:" || echo "  Not installed"

    # 检测 GPU
    local has_gpu=false
    local needs_nightly=false

    if command_exists nvidia-smi; then
        local gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        if [ -n "$gpu_name" ]; then
            has_gpu=true
            log_info "GPU detected: $gpu_name"

            if echo "$gpu_name" | grep -qiE "RTX[[:space:]]*[5-9][0-9]|GeForce[[:space:]]*[5-9][0-9]"; then
                needs_nightly=true
            fi
        fi
    fi

    if [ "$has_gpu" = true ]; then
        # CPU 保底
        $pip_cmd install torch torchvision torchaudio 2>&1 | tail -3 || true

        local torch_index_url=""
        if [ "$needs_nightly" = true ]; then
            torch_index_url="https://download.pytorch.org/whl/nightly/cu128"
        else
            torch_index_url="https://download.pytorch.org/whl/cu121"
        fi

        log_info "Uninstalling old PyTorch..."
        $pip_cmd uninstall -y torch torchvision torchaudio 2>/dev/null || true
        $pip_cmd cache purge 2>/dev/null || true

        $pip_cmd config unset global.index-url 2>/dev/null || true

        log_info "Installing CUDA PyTorch from $torch_index_url..."
        if $pip_cmd install torch torchvision --index-url "$torch_index_url" --no-cache-dir 2>&1; then
            log_success "CUDA PyTorch installed"
        else
            log_warn "Failed, using CPU version"
            $pip_cmd install torch torchvision torchaudio 2>&1 | tail -3 || true
        fi
    else
        log_info "Installing CPU PyTorch..."
        $pip_cmd install torch torchvision torchaudio 2>&1 | tail -3 || true
    fi

    echo ""
    log_info "New PyTorch version:"
    $pip_cmd show torch 2>/dev/null | grep -E "^Version:|^CUDA:" || echo "  Not installed"
}

#===============================================================================
# 项目获取
#===============================================================================

get_project() {
    log_step "Getting project..."

    # 检查是否是 git 仓库
    if [ -d "${PROJECT_ROOT}/.git" ]; then
        log_info "Git repository found"

        local remoteUrl=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null)
        local isGithub=false

        if [ -n "$remoteUrl" ] && [[ "$remoteUrl" == *"github.com"* ]]; then
            log_info "Using Gitee mirror..."
            git -C "$PROJECT_ROOT" remote set-url origin "$GITEE_MIRROR" 2>/dev/null
            isGithub=true
        fi

        log_info "Pulling updates..."
        git -C "$PROJECT_ROOT" pull origin master 2>/dev/null

        if [ "$isGithub" = true ]; then
            git -C "$PROJECT_ROOT" remote set-url origin "$GITHUB_ORIGIN" 2>/dev/null
        fi

        log_success "Project updated"
        return 0
    fi

    # 检查项目文件
    if [ -f "${PROJECT_ROOT}/settings.yaml" ]; then
        log_success "Project files found"
        return 0
    fi

    if [ -d "${PROJECT_ROOT}/src" ] && [ -f "${PROJECT_ROOT}/requirements.txt" ]; then
        log_success "Project files found"
        return 0
    fi

    # 备份用户文件
    local items=$(ls -A "$PROJECT_ROOT" 2>/dev/null | grep -v "^deploy\." | grep -v "^\.git$")
    if [ -n "$items" ]; then
        log_warn "Found existing files but no project detected"
        local backupDir="${HOME}/wingscribe_backup_$(date +%Y%m%d_%H%M%S)"
        log_info "Backing up to: $backupDir"
        mkdir -p "$backupDir"
        for item in $items; do
            [ "$item" != ".git" ] && [ "$item" != "deploy.sh" ] && [ "$item" != "deploy.ps1" ] && \
                cp -r "$item" "$backupDir/" 2>/dev/null
        done
    fi

    # 克隆项目
    log_info "Cloning from Gitee..."
    local tempDir="/tmp/wingscribe_clone_$$"
    mkdir -p "$tempDir"

    local cloneSuccess=false

    if git clone --depth 1 "$GITEE_MIRROR" "$tempDir" 2>&1; then
        if [ -f "${tempDir}/requirements.txt" ]; then
            git -C "$tempDir" remote set-url origin "$GITHUB_ORIGIN" 2>/dev/null
            cloneSuccess=true
        fi
    fi

    if [ "$cloneSuccess" = false ]; then
        log_warn "Gitee failed, trying GitHub..."
        rm -rf "$tempDir"
        mkdir -p "$tempDir"

        if git clone --depth 1 "$GITHUB_ORIGIN" "$tempDir" 2>&1; then
            if [ -f "${tempDir}/requirements.txt" ]; then
                cloneSuccess=true
            fi
        fi
    fi

    if [ "$cloneSuccess" = true ]; then
        log_info "Moving files..."
        for item in "${tempDir}"/*; do
            [ -f "$item" ] && cp -r "$item" "$PROJECT_ROOT/" 2>/dev/null
        done
        rm -rf "$tempDir"

        if [ -f "${PROJECT_ROOT}/requirements.txt" ]; then
            log_success "Project cloned successfully"
            return 0
        fi
    fi

    log_error "Clone failed!"
    echo ""
    echo -e "${YELLOW}Please manually clone:${NC}"
    echo "  git clone https://gitee.com/jiangyuyi/wingscribe.git ."
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
    echo -e "${CYAN}  ${WHITE}Configuration Wizard${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""

    # 1. 照片源目录
    echo -e "  ${CYAN}1/3 Photo source directory${NC}"
    echo -e "  ${GRAY}Format: Year/yyyymmdd_Location/*.jpg${NC}"
    echo ""

    local default_source="$HOME/Pictures"
    if is_linux; then
        default_source="$HOME/图片"
    fi

    local source_dir=$(ask_input "Photo directory" "$default_source")
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

    local DEVICE="cpu"

    if [ "$HAS_GPU" = "true" ]; then
        echo -e "  ${GREEN}GPU detected${NC}"
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

    # 计算相对于 base_dir 的输出目录
    local relative_output_dir="${output_dir#${source_dir}/}"

    cat > "$config_path" << EOF
# WingScribe config
# Generated by deploy script

paths:
  base_dir: "$source_dir"
  references_path: "data/references"
  sources:
    - path: "."
      recursive: true
      enabled: true
  output:
    root_dir: "$relative_output_dir"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false
  db_path: "data/db/wingscribe.db"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
  model_cache_dir: "data/models"
processing:
  device: "$DEVICE"
  yolo_model: "yolo26n.pt"
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
  hf_mirror: ""
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
# 请填入您的 API 密钥

# 顶层 API 密钥
hf_api_key: ""
dongniao_api_key: ""

# 云端识别配置
cloud:
  huggingface:
    api_token: ""
    model_id: "imageomics/bioclip-2"
  modelscope:
    api_token: ""
  baidu:
    api_key: ""
    secret_key: ""
  aliyun:
    access_key_id: ""
    access_key_secret: ""
EOF
        log_success "Secrets generated: $secrets_path"
    fi

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${WHITE}Configuration Summary${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo -e "  Source:  $source_dir"
    echo -e "  Output:  $output_dir"
    echo -e "  Device:  $DEVICE"
    echo -e "${CYAN}========================================${NC}"
}

#===============================================================================
# Web 服务
#===============================================================================

start_web_server() {
    log_step "Starting Web server..."

    local venv_python=""
    local web_script="${PROJECT_ROOT}/src/web/app.py"

    # 检测虚拟环境 Python
    if [ -f "${PROJECT_ROOT}/venv/bin/python" ]; then
        venv_python="${PROJECT_ROOT}/venv/bin/python"
    elif [ -f "${PROJECT_ROOT}/venv/Scripts/python.exe" ]; then
        venv_python="${PROJECT_ROOT}/venv/Scripts/python.exe"
    fi

    if [ -z "$venv_python" ] || [ ! -f "$venv_python" ]; then
        log_error "Virtual environment not found!"
        log_info "Please run '$0 install' first"
        return 1
    fi

    if [ ! -f "$web_script" ]; then
        log_error "Web script not found: $web_script"
        return 1
    fi

    # 读取配置文件中的 HuggingFace 镜像并设置为环境变量
    local config_file="${PROJECT_ROOT}/config/settings.yaml"
    if [ -f "$config_file" ]; then
        local hf_mirror=$(grep -E "^\s*hf_mirror:" "$config_file" | sed 's/.*hf_mirror:\s*["\x27]*\(.*\)["\x27]*/\1/' | xargs)
        if [ -n "$hf_mirror" ]; then
            log_info "Setting HuggingFace mirror: $hf_mirror"
            export HF_ENDPOINT="$hf_mirror"
            export HF_HUB_URL="$hf_mirror"
        fi
    fi

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}  ${GREEN}Starting Web server...${NC}"
    echo -e "${CYAN}  URL: ${WHITE}http://localhost:8000${NC}"
    echo -e "${CYAN}  Press ${WHITE}Ctrl+C${NC} to stop"
    echo -e "${CYAN}========================================${NC}"
    echo ""

    cd "$PROJECT_ROOT"
    "$venv_python" "$web_script"
}

#===============================================================================
# 菜单界面
#===============================================================================

show_menu() {
    clear
    echo ""
    echo -e "  ${CYAN}========================================${NC}"
    echo -e "  ${CYAN}WingScribe Deployment${NC}  ${GRAY}AI Bird Photo Management${NC}"
    echo -e "  ${CYAN}========================================${NC}"
    echo ""

    # 显示 CUDA 状态
    if test_cuda 2>/dev/null; then
        echo -e "  ${GREEN}GPU: $DRIVER_VERSION | CUDA: $CUDA_VERSION${NC}"
    elif [ "$HAS_GPU" = "true" ]; then
        echo -e "  ${YELLOW}GPU: Detected (CUDA not installed)${NC}"
    else
        echo -e "  ${GRAY}Mode: CPU${NC}"
    fi

    echo ""
    echo -e "  ${WHITE}[1]${NC} Start Deployment"
    echo -e "  ${WHITE}[2]${NC} Configuration"
    echo -e "  ${WHITE}[3]${NC} Update Project"
    echo -e "  ${WHITE}[4]${NC} Install CUDA (GPU Support)"
    echo -e "  ${WHITE}[5]${NC} Reinstall PyTorch (Fix GPU)"
    echo -e "  ${WHITE}[6]${NC} Start Service"
    echo -e "  ${WHITE}[7]${NC} Help"
    echo -e "  ${WHITE}[8]${NC} Exit"
    echo ""
    echo -e "  ${CYAN}========================================${NC}"
}

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
  pytorch          Reinstall PyTorch (fix GPU issues)
  web              Start Web server
  help             Show this help

Examples:
  $0 deploy           # Full deployment
  $0 config           # Configure only
  $0 pytorch          # Reinstall PyTorch for GPU
  $0 web              # Start Web service

Quick Start:
  1. Run: $0 deploy
  2. Configure photo directory
  3. Run: $0 web
  4. Open: http://localhost:8000

Format: Year/yyyymmdd_Location/*.jpg

EOF
}

#===============================================================================
# 主入口
#===============================================================================

main() {
    cd "$PROJECT_ROOT"

    # 检测 GPU（全局）
    test_gpu

    local command="${1:-}"

    # 如果有命令行参数，直接执行对应命令
    if [ -n "$command" ]; then
        case "$command" in
            deploy|d)
                echo ""
                echo -e "${CYAN}========================================${NC}"
                echo -e "${CYAN}  ${GREEN}Deployment${NC}"
                echo -e "${CYAN}========================================${NC}"
                echo ""

                log_step "1/4 Checking environment..."
                test_git || true
                test_python || log_error "Python installation recommended"
                test_exiftool || log_warn "ExifTool not found"

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
                get_project || true

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
                echo -e "${CYAN}  ${WHITE}Install Dependencies${NC}"
                echo -e "${CYAN}========================================${NC}"
                echo ""

                if [ ! -f "${PROJECT_ROOT}/requirements.txt" ]; then
                    log_error "requirements.txt not found!"
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
                echo -e "${CYAN}  ${WHITE}Update Project${NC}"
                echo -e "${CYAN}========================================${NC}"
                echo ""
                get_project
                ;;
            cuda)
                echo ""
                echo -e "${CYAN}========================================${NC}"
                echo -e "${CYAN}  ${GREEN}CUDA Installation${NC}"
                echo -e "${CYAN}========================================${NC}"
                echo ""
                install_cuda
                ;;
            pytorch)
                echo ""
                echo -e "${CYAN}========================================${NC}"
                echo -e "${CYAN}  ${GREEN}Reinstall PyTorch${NC}"
                echo -e "${CYAN}========================================${NC}"
                echo ""
                reinstall_pytorch
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
        return 0
    fi

    # 交互式菜单模式
    while true; do
        show_menu
        local choice=$(ask_input "Enter option" "")
        echo ""

        case "$choice" in
            1)
                echo -e "${CYAN}========================================${NC}"
                echo -e "${CYAN}  ${GREEN}Deployment${NC}"
                echo -e "${CYAN}========================================${NC}"
                echo ""

                log_step "1/4 Checking environment..."
                test_git || true
                test_python || log_error "Python installation recommended"
                test_exiftool || log_warn "ExifTool not found"

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
                get_project || true

                log_step "4/4 Installing Python dependencies..."
                install_python_deps

                invoke_config_wizard

                echo ""
                log_success "Deployment complete!"
                echo ""
                echo -e "${WHITE}Next: Select [6] to start service, open http://localhost:8000${NC}"
                echo ""
                pause
                ;;
            2)
                invoke_config_wizard
                pause
                ;;
            3)
                get_project
                pause
                ;;
            4)
                echo -e "${CYAN}========================================${NC}"
                echo -e "${CYAN}  ${GREEN}CUDA Installation${NC}"
                echo -e "${CYAN}========================================${NC}"
                echo ""
                test_gpu
                if [ "$HAS_GPU" = "true" ]; then
                    install_cuda
                else
                    log_warn "No NVIDIA GPU detected"
                fi
                pause
                ;;
            5)
                echo -e "${CYAN}========================================${NC}"
                echo -e "${CYAN}  ${GREEN}Reinstall PyTorch${NC}"
                echo -e "${CYAN}========================================${NC}"
                echo ""
                reinstall_pytorch
                pause
                ;;
            6)
                start_web_server
                ;;
            7)
                clear
                show_help
                pause
                ;;
            8)
                echo ""
                echo "  Goodbye!"
                echo ""
                exit 0
                ;;
            *)
                log_error "Invalid option"
                sleep 1
                ;;
        esac
    done
}

main "$@"
