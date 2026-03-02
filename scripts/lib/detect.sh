#!/bin/bash
#===============================================================================
# WingScribe 一键部署脚本 - 环境检测模块
#===============================================================================

# 加载通用函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

#===============================================================================
# 检测 Git
#===============================================================================
detect_git() {
    if command_exists git; then
        local version=$(git --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        log_info "Git 已安装: $version"
        return 0
    else
        log_warn "Git 未安装"
        return 1
    fi
}

#===============================================================================
# 检测 Python
#===============================================================================
detect_python() {
    local python_cmd=""
    local python_found=0

    # 尝试多种 Python 命令
    for cmd in python3 python python python3.11 python3.10 python3.9; do
        if command_exists "$cmd"; then
            local version=$($cmd --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
            local major=$($cmd -c "import sys; print(sys.version_info.major)" 2>/dev/null)
            local minor=$($cmd -c "import sys; print(sys.version_info.minor)" 2>/dev/null)

            if [ "$major" = "3" ] && [ "$minor" -ge 8 ]; then
                python_cmd="$cmd"
                python_found=1
                log_info "Python 已安装: $version ($cmd)"
                break
            fi
        fi
    done

    if [ $python_found -eq 1 ]; then
        PYTHON_CMD="$python_cmd"
        return 0
    else
        log_warn "Python 3.8+ 未安装"
        PYTHON_CMD=""
        return 1
    fi
}

#===============================================================================
# 检测 pip
#===============================================================================
detect_pip() {
    if [ -z "$PYTHON_CMD" ]; then
        log_warn "Python 未安装，无法检测 pip"
        return 1
    fi

    if $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
        local version=$($PYTHON_CMD -m pip --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)
        log_info "pip 已安装: $version"
        return 0
    else
        log_warn "pip 未安装"
        return 1
    fi
}

#===============================================================================
# 检测 CUDA/GPU
#===============================================================================
detect_gpu() {
    local has_cuda=0
    local gpu_info=""

    if is_windows; then
        # Windows: 通过 nvidia-smi 检测
        if command_exists nvidia-smi; then
            gpu_info=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
            if [ -n "$gpu_info" ]; then
                has_cuda=1
            fi
        fi
    elif is_macos; then
        # Mac: Metal GPU (Apple Silicon)
        if system_profiler SPDisplaysDataType 2>/dev/null | grep -qi "metal\|apple"; then
            has_cuda=1
            gpu_info=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Chip|Model" | head -1 | xargs)
        fi
    else
        # Linux: 通过 nvidia-smi 或 vainfo 检测
        if command_exists nvidia-smi; then
            gpu_info=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
            if [ -n "$gpu_info" ]; then
                has_cuda=1
            fi
        elif command_exists vainfo; then
            # Intel/AMD GPU
            if vainfo 2>/dev/null | grep -qi "vaapi\|vulkan"; then
                has_cuda=1
                gpu_info=$(vainfo 2>/dev/null | head -1)
            fi
        fi
    fi

    if [ $has_cuda -eq 1 ]; then
        log_info "GPU 检测成功: $gpu_info"
        GPU_INFO="$gpu_info"
        HAS_GPU=1
        return 0
    else
        log_warn "未检测到兼容 GPU，将使用 CPU"
        GPU_INFO=""
        HAS_GPU=0
        return 1
    fi
}

#===============================================================================
# 检测 ExifTool
#===============================================================================
detect_exiftool() {
    if command_exists exiftool; then
        local version=$(exiftool -ver 2>/dev/null)
        log_info "ExifTool 已安装: $version"
        return 0
    else
        log_warn "ExifTool 未安装"
        return 1
    fi
}

#===============================================================================
# 检测网络连接
#===============================================================================
detect_network() {
    local connectivity=0
    local network_info=""

    # 检测 GitHub 连通性
    if check_connectivity "github.com"; then
        connectivity=$((connectivity | 1))
    fi

    # 检测 Gitee 连通性
    if check_connectivity "gitee.com"; then
        connectivity=$((connectivity | 2))
    fi

    # 检测 HuggingFace 连通性
    if check_connectivity "huggingface.co"; then
        connectivity=$((connectivity | 4))
    fi

    case $connectivity in
        0)  network_info="离线环境" ;;
        1)  network_info="仅 GitHub 可访问" ;;
        2)  network_info="仅 Gitee 可访问" ;;
        3)  network_info="GitHub + Gitee 可访问" ;;
        4)  network_info="仅 HuggingFace 可访问" ;;
        5)  network_info="GitHub + HuggingFace 可访问" ;;
        6)  network_info="Gitee + HuggingFace 可访问" ;;
        7)  network_info="完全连通" ;;
    esac

    log_info "网络状态: $network_info"
    NETWORK_STATUS=$connectivity
    return 0
}

#===============================================================================
# 检测 Docker (可选)
#===============================================================================
detect_docker() {
    if command_exists docker; then
        local version=$(docker --version 2>/dev/null)
        log_info "Docker 已安装: $version"
        HAS_DOCKER=1
        return 0
    else
        log_warn "Docker 未安装 (可选)"
        HAS_DOCKER=0
        return 1
    fi
}

#===============================================================================
# 检测系统资源
#===============================================================================
detect_system_resources() {
    local memory_mb=0
    local disk_gb=0

    # 检测内存
    if is_windows; then
        memory_mb=$(wmic OS Get TotalVisibleMemorySize 2>/dev/null | tail -1)
    elif is_macos; then
        memory_mb=$(($(sysctl -n hw.memsize 2>/dev/null) / 1024 / 1024))
    else
        if [ -f /proc/meminfo ]; then
            memory_mb=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print int($2/1024)}')
        elif command_exists free; then
            memory_mb=$(free -m 2>/dev/null | grep Mem | awk '{print $2}')
        fi
    fi

    # 检测可用磁盘空间 (项目目录)
    if is_windows; then
        disk_gb=$(wmic logicaldisk where "DeviceID='${PROJECT_ROOT:0:2}'" get FreeSpace 2>/dev/null | tail -1)
        disk_gb=$((disk_gb / 1024 / 1024 / 1024))
    else
        disk_gb=$(df -BG "${PROJECT_ROOT}" 2>/dev/null | tail -1 | awk '{print int($4)}' | tr -d 'G')
    fi

    if [ -z "$disk_gb" ] || [ "$disk_gb" -eq 0 ]; then
        disk_gb=$(df -BG . 2>/dev/null | tail -1 | awk '{print int($4)}' | tr -d 'G')
    fi

    SYSTEM_MEMORY=$memory_mb
    SYSTEM_DISK=$disk_gb

    log_info "系统内存: ${memory_mb}MB"
    log_info "可用磁盘: ${disk_gb}GB"

    # 建议
    if [ "$memory_mb" -lt 8000 ]; then
        log_warn "内存较小 (< 8GB)，BioCLIP 模型运行可能较慢"
    fi

    if [ "$disk_gb" -lt 20 ]; then
        log_warn "磁盘空间不足 (< 20GB)，模型和照片可能需要更多空间"
    fi
}

#===============================================================================
# 检测 CUDA 版本 (如果可用)
#===============================================================================
detect_cuda_version() {
    if [ $HAS_GPU -eq 0 ]; then
        CUDA_VERSION=""
        return 1
    fi

    if is_windows && command_exists nvidia-smi; then
        CUDA_VERSION=$(nvidia-smi 2>/dev/null | grep "CUDA Version" | awk '{print $9}')
    elif command_exists nvcc; then
        CUDA_VERSION=$(nvcc --version 2>/dev/null | grep "release" | awk '{print $5}' | tr -d ',')
    elif [ -f /usr/local/cuda/version.txt ]; then
        CUDA_VERSION=$(cat /usr/local/cuda/version.txt 2>/dev/null | awk '{print $3}')
    else
        CUDA_VERSION=""
    fi

    if [ -n "$CUDA_VERSION" ]; then
        log_info "CUDA 版本: $CUDA_VERSION"
        return 0
    else
        CUDA_VERSION=""
        return 1
    fi
}

#===============================================================================
# 完整环境检测
#===============================================================================
detect_environment() {
    log_step "开始环境检测..."

    local all_ok=1

    # 检测 Git
    detect_git
    [ $? -ne 0 ] && all_ok=0

    # 检测 Python
    detect_python
    [ $? -ne 0 ] && all_ok=0

    # 检测 pip (如果 Python 存在)
    [ -n "$PYTHON_CMD" ] && detect_pip

    # 检测 GPU
    detect_gpu
    detect_cuda_version

    # 检测 ExifTool
    detect_exiftool || log_warn "ExifTool 可稍后安装"

    # 检测网络
    detect_network

    # 检测系统资源
    detect_system_resources

    # 检测 Docker (可选)
    detect_docker

    echo ""
    if [ $all_ok -eq 1 ]; then
        log_success "基础环境检测完成，所有必需组件已安装"
        return 0
    else
        log_warn "部分必需组件缺失，建议运行安装功能"
        return 1
    fi
}

#===============================================================================
# 导出检测结果供其他脚本使用
#===============================================================================
export_detection_results() {
    export PYTHON_CMD
    export HAS_GPU
    export GPU_INFO
    export CUDA_VERSION
    export HAS_DOCKER
    export SYSTEM_MEMORY
    export SYSTEM_DISK
    export NETWORK_STATUS
}
