#!/bin/bash
#===============================================================================
# WingScribe 一键部署脚本 - 软件安装模块
#===============================================================================

# 加载通用函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
source "${SCRIPT_DIR}/detect.sh"

#===============================================================================
# 安装 Git
#===============================================================================
install_git() {
    log_step "安装 Git..."

    if is_windows; then
        if command_exists winget; then
            run_command "winget install --id Git.Git -e --source winget" "Git (winget)" || return 1
        elif command_exists scoop; then
            run_command "scoop install git" "Git (scoop)" || return 1
        elif command_exists choco; then
            run_command "choco install git -y" "Git (choco)" || return 1
        else
            log_error "Windows 上请手动安装 Git 或安装 scoop/choco"
            log_info "下载地址: https://git-scm.com/download/win"
            return 1
        fi
    elif is_macos; then
        if command_exists brew; then
            run_command "brew install git" "Git (brew)" || return 1
        else
            log_error "请先安装 Homebrew: https://brew.sh"
            return 1
        fi
    else
        # Linux
        if command_exists apt-get; then
            sudo apt-get update && sudo apt-get install -y git
        elif command_exists yum; then
            sudo yum install -y git
        elif command_exists dnf; then
            sudo dnf install -y git
        elif command_exists pacman; then
            sudo pacman -S --noconfirm git
        elif command_exists zypper; then
            sudo zypper install -y git
        else
            log_error "无法自动安装 Git，请手动安装"
            return 1
        fi
    fi

    # 重新检测
    if detect_git; then
        log_success "Git 安装成功"
        return 0
    else
        log_error "Git 安装失败"
        return 1
    fi
}

#===============================================================================
# 安装 Python
#===============================================================================
install_python() {
    log_step "安装 Python 3.10+..."

    if is_windows; then
        if command_exists winget; then
            run_command "winget install --id Python.Python.3.11 -e --source winget" "Python 3.11 (winget)" || return 1
        elif command_exists scoop; then
            run_command "scoop install python311" "Python 3.11 (scoop)" || return 1
        elif command_exists choco; then
            run_command "choco install python311 -y" "Python 3.11 (choco)" || return 1
        else
            log_error "Windows 上请手动安装 Python"
            log_info "下载地址: https://www.python.org/downloads/"
            return 1
        fi
    elif is_macos; then
        if command_exists brew; then
            run_command "brew install python@3.11" "Python 3.11 (brew)" || return 1
            # 添加到 PATH
            echo 'export PATH="/opt/homebrew/opt/python@3.11/bin:$PATH"' >> ~/.zshrc 2>/dev/null || true
        else
            log_error "请先安装 Homebrew: https://brew.sh"
            return 1
        fi
    else
        # Linux
        if command_exists apt-get; then
            sudo apt-get update && sudo apt-get install -y python3.11 python3-pip python3-venv
        elif command_exists yum; then
            sudo yum install -y python3.11 python3-pip
        elif command_exists dnf; then
            sudo dnf install -y python3.11 python3-pip
        elif command_exists pacman; then
            sudo pacman -S --noconfirm python311 python-pip
        elif command_exists zypper; then
            sudo zypper install -y python311 python3-pip
        else
            log_error "无法自动安装 Python，请手动安装"
            return 1
        fi
    fi

    # 重新检测
    if detect_python; then
        log_success "Python 安装成功"
        return 0
    else
        log_error "Python 安装失败"
        return 1
    fi
}

#===============================================================================
# 安装 ExifTool
#===============================================================================
install_exiftool() {
    log_step "安装 ExifTool..."

    if is_windows; then
        if command_exists winget; then
            run_command "winget install --id PhilHarvey.ExifTool -e --source winget" "ExifTool (winget)" || return 1
        elif command_exists scoop; then
            run_command "scoop install exiftool" "ExifTool (scoop)" || return 1
        elif command_exists choco; then
            run_command "choco install exiftool -y" "ExifTool (choco)" || return 1
        else
            log_error "Windows 上请手动安装 ExifTool"
            log_info "下载地址: https://exiftool.org/"
            return 1
        fi
    elif is_macos; then
        if command_exists brew; then
            run_command "brew install exiftool" "ExifTool (brew)" || return 1
        else
            # Mac 内置可能已有
            if command_exists exiftool; then
                log_info "ExifTool 已内置"
                return 0
            fi
            log_error "请先安装 Homebrew: https://brew.sh"
            return 1
        fi
    else
        # Linux
        if command_exists apt-get; then
            sudo apt-get update && sudo apt-get install -y exiftool
        elif command_exists yum; then
            sudo yum install -y perl-Image-ExifTool
        elif command_exists dnf; then
            sudo dnf install -y perl-Image-ExifTool
        elif command_exists pacman; then
            sudo pacman -S --noconfirm perl-image-exiftool
        elif command_exists zypper; then
            sudo zypper install -y perl-Image-ExifTool
        else
            log_error "无法自动安装 ExifTool，请手动安装"
            return 1
        fi
    fi

    # 重新检测
    if detect_exiftool; then
        log_success "ExifTool 安装成功"
        return 0
    else
        log_error "ExifTool 安装失败"
        return 1
    fi
}

#===============================================================================
# 安装 Visual Studio Build Tools (Windows CUDA 支持)
#===============================================================================
install_vs_build_tools() {
    log_step "安装 Visual Studio Build Tools..."

    if is_windows && command_exists winget; then
        run_command "winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget" "VS Build Tools 2022" || return 1
    else
        log_error "请手动安装 Visual Studio Build Tools"
        log_info "下载地址: https://visualstudio.microsoft.com/visual-cpp-build-tools/"
        return 1
    fi
}

#===============================================================================
# 安装所有必需软件
#===============================================================================
install_all_dependencies() {
    log_step "安装所有必需依赖..."

    local failed=0

    # 检测并安装 Git
    if ! command_exists git; then
        install_git || failed=1
    fi

    # 检测并安装 Python
    if ! detect_python >/dev/null 2>&1; then
        install_python || failed=1
    fi

    # 检测并安装 ExifTool
    if ! command_exists exiftool; then
        install_exiftool || failed=1
    fi

    if [ $failed -eq 0 ]; then
        log_success "所有依赖安装完成"
        return 0
    else
        log_error "部分依赖安装失败"
        return 1
    fi
}

#===============================================================================
# 安装 CUDA (可选)
#===============================================================================
install_cuda() {
    if ! is_linux && ! is_windows; then
        log_warn "CUDA 仅支持 Linux 和 Windows"
        return 1
    fi

    log_step "安装 CUDA Toolkit..."

    if is_windows; then
        log_info "请从 NVIDIA 官网下载并安装 CUDA Toolkit"
        log_info "下载地址: https://developer.nvidia.com/cuda-downloads"
        return 1
    else
        # Linux CUDA 安装
        if command_exists apt-get; then
            # 添加 NVIDIA CUDA 仓库
            wget -O /tmp/cuda-keyring.deb https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
            sudo dpkg -i /tmp/cuda-keyring.deb
            sudo apt-get update
            sudo apt-get install -y cuda-toolkit-12-3
        elif command_exists yum; then
            sudo yum install -y cuda-toolkit-12-3
        else
            log_error "无法自动安装 CUDA，请手动安装"
            return 1
        fi
    fi
}

#===============================================================================
# 安装 Python 依赖
#===============================================================================
install_python_deps() {
    log_step "安装 Python 依赖..."

    if [ -z "$PYTHON_CMD" ]; then
        log_error "Python 未安装，无法安装依赖"
        return 1
    fi

    # 检查虚拟环境
    local venv_path="${PROJECT_ROOT}/venv"
    local pip_cmd="$PYTHON_CMD -m pip"

    # 配置 pip 镜像
    log_info "配置 pip 镜像源..."
    $pip_cmd config set global.index-url "$PIP_MIRROR" 2>/dev/null || true

    # 创建虚拟环境 (如果不存在)
    if [ ! -d "$venv_path" ]; then
        log_info "创建 Python 虚拟环境..."
        $PYTHON_CMD -m venv "$venv_path"
    fi

    # 激活虚拟环境
    if is_windows; then
        local pip_cmd="${venv_path}/Scripts/pip"
        local python_venv="${venv_path}/Scripts/python"
    else
        local pip_cmd="${venv_path}/bin/pip"
        local python_venv="${venv_path}/bin/python"
    fi

    # 安装依赖
    log_info "安装项目依赖..."
    $pip_cmd install --upgrade pip 2>/dev/null || true

    local requirements_file="${PROJECT_ROOT}/requirements.txt"
    if [ -f "$requirements_file" ]; then
        $pip_cmd install -r "$requirements_file" 2>&1 | while read line; do
            log_debug "$line"
        done

        if [ $? -eq 0 ]; then
            log_success "Python 依赖安装完成"
            return 0
        else
            log_error "Python 依赖安装失败"
            return 1
        fi
    else
        log_error "未找到 requirements.txt 文件"
        return 1
    fi
}
