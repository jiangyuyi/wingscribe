#!/bin/bash
#===============================================================================
# WingScribe 一键部署脚本 - 通用函数库
#===============================================================================

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# 日志级别
LOG_INFO=0
LOG_WARN=1
LOG_ERROR=2
LOG_DEBUG=3

# 配置文件路径
CONFIG_FILE=""
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

#===============================================================================
# 日志函数
#===============================================================================
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
    return 0
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    return 0
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
    return 0
}

log_debug() {
    if [ "${DEBUG:-0}" = "1" ]; then
        echo -e "${BLUE}[DEBUG]${NC} $1"
    fi
    return 0
}

log_step() {
    echo -e "${CYAN}[STEP]${NC} $1"
    return 0
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
    return 0
}

#===============================================================================
# 路径函数
#===============================================================================
get_os_type() {
    case "$(uname -s)" in
        Linux*)     echo "linux";;
        Darwin*)    echo "macos";;
        CYGWIN*|MINGW*|MSYS*) echo "windows";;
        *)          echo "unknown";;
    esac
}

is_windows() {
    [ "$(get_os_type)" = "windows" ]
}

is_macos() {
    [ "$(get_os_type)" = "macos" ]
}

is_linux() {
    [ "$(get_os_type)" = "linux" ]
}

get_home_dir() {
    if is_windows; then
        echo "$USERPROFILE"
    else
        echo "$HOME"
    fi
}

get_desktop_dir() {
    local home=$(get_home_dir)
    if is_windows; then
        echo "$home/Desktop"
    elif is_macos; then
        echo "$home/Desktop"
    else
        echo "$home/桌面"
    fi
}

#===============================================================================
# 文件操作函数
#===============================================================================
ensure_dir() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir" 2>/dev/null || mkdir -p "$dir"
    fi
}

backup_file() {
    local file="$1"
    if [ -f "$file" ]; then
        local backup="${file}.backup.$(date +%Y%m%d%H%M%S)"
        cp "$file" "$backup"
        log_debug "Backed up $file to $backup"
    fi
}

read_config() {
    local key="$1"
    local default="$2"
    if [ -f "$CONFIG_FILE" ]; then
        grep -E "^${key}=" "$CONFIG_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "$default"
    else
        echo "$default"
    fi
}

write_config() {
    local key="$1"
    local value="$2"
    echo "${key}=${value}" >> "$CONFIG_FILE"
}

#===============================================================================
# 命令执行函数
#===============================================================================
run_command() {
    local cmd="$1"
    local description="$2"
    local error_msg="${3:-Command failed}"

    log_debug "Running: $cmd"

    if eval "$cmd" > /dev/null 2>&1; then
        [ -n "$description" ] && log_success "$description"
        return 0
    else
        [ -n "$description" ] && log_error "$error_msg"
        return 1
    fi
}

run_command_output() {
    local cmd="$1"
    eval "$cmd" 2>/dev/null
}

command_exists() {
    local cmd="$1"
    command -v "$cmd" >/dev/null 2>&1
}

#===============================================================================
# 字符串函数
#===============================================================================
trim() {
    echo "$1" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

to_lower() {
    echo "$1" | tr '[:upper:]' '[:lower:]'
}

to_upper() {
    echo "$1" | tr '[:lower:]' '[:upper:]'
}

#===============================================================================
# 网络函数
#===============================================================================
check_connectivity() {
    local host="${1:-8.8.8.8}"
    if command_exists ping; then
        if is_windows; then
            ping -n 1 -w 1000 "$host" >/dev/null 2>&1
        else
            ping -c 1 -W 1 "$host" >/dev/null 2>&1
        fi
    else
        # Fallback: try curl/wget
        command_exists curl && curl -s --connect-timeout 2 "$host" >/dev/null 2>&1
    fi
}

#===============================================================================
# 版本比较函数
#===============================================================================
version_ge() {
    # Returns 0 if $1 >= $2
    [ "$1" = "$(echo -e "$1\n$2" | sort -V | tail -n1)" ]
}

#===============================================================================
# 下载函数
#===============================================================================
download_file() {
    local url="$1"
    local output="$2"
    local desc="${3:-Downloading}"

    if command_exists curl; then
        curl -L -o "$output" "$url" 2>/dev/null
    elif command_exists wget; then
        wget -q -O "$output" "$url" 2>/dev/null
    else
        log_error "No download tool available (curl or wget)"
        return 1
    fi
}

#===============================================================================
# 进度条函数
#===============================================================================
show_progress() {
    local current=$1
    local total=$2
    local prefix="${3:-Progress}"
    local width=40
    local percent=$((current * 100 / total))
    local filled=$((width * current / total))
    local empty=$((width - filled))

    printf "\r${prefix}: [%s%s] %d%%" \
        "$(printf '#%.0s' $(seq 1 $filled 2>/dev/null) 2>/dev/null)" \
        "$(printf '.%.0s' $(seq 1 $empty 2>/dev/null) 2>/dev/null)" \
        "$percent"
}

#===============================================================================
# 暂停函数
#===============================================================================
pause() {
    local message="${1:-按 Enter 继续...}"
    if is_windows; then
        echo -e "${YELLOW}$message${NC}"
        read -r
    else
        read -r -p "$(echo -e ${YELLOW}$message${NC}) "
    fi
}

#===============================================================================
# 初始化配置目录
#===============================================================================
init_config_dir() {
    local config_dir="${PROJECT_ROOT}/.deploy_config"
    ensure_dir "$config_dir"
    CONFIG_FILE="${config_dir}/config.sh"

    # 创建默认配置（如果不存在）
    if [ ! -f "$CONFIG_FILE" ]; then
        cat > "$CONFIG_FILE" << 'EOF'
# WingScribe 部署配置
# 此文件由部署脚本自动生成

# GitHub 镜像地址 (Gitee)
GITEE_MIRROR="https://gitee.com/jiangyuyi/wingscribe.git"

# GitHub 原始地址
GITHUB_ORIGIN="https://github.com/jiangyuyi/wingscribe.git"

# HuggingFace 镜像
HF_MIRROR="https://hf-mirror.com"

# PyPI 镜像
PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"

# 代理设置 (留空表示不使用)
PROXY=""

# Python 虚拟环境目录
VENV_DIR="${PROJECT_ROOT}/venv"

# 照片源目录
SOURCE_DIR=""

# 输出目录
OUTPUT_DIR=""

# 处理设备 (auto/cpu/cuda)
DEVICE="auto"

# 是否已配置
CONFIGURED=0
EOF
        chmod 644 "$CONFIG_FILE"
    fi

    # 加载配置
    source "$CONFIG_FILE"
}

#===============================================================================
# 保存配置
#===============================================================================
save_config() {
    local key="$1"
    local value="$2"

    if [ -f "$CONFIG_FILE" ]; then
        # 使用 sed 更新配置
        if grep -q "^${key}=" "$CONFIG_FILE"; then
            sed -i "s|^${key}=.*|${key}=${value}|" "$CONFIG_FILE"
        else
            echo "${key}=${value}" >> "$CONFIG_FILE"
        fi
    fi
}

#===============================================================================
# 询问用户输入
#===============================================================================
ask_input() {
    local prompt="$1"
    local default="${2:-}"
    local result

    if [ -n "$default" ]; then
        read -r -p "$(echo -e ${CYAN}${prompt}${NC} [${default}]: )" result
        echo "${result:-$default}"
    else
        read -r -p "$(echo -e ${CYAN}${prompt}${NC}: )" result
        echo "$result"
    fi
}

ask_yes_no() {
    local prompt="$1"
    local default="${2:-y}"

    while true; do
        local answer
        if [ "$default" = "y" ]; then
            read -r -p "$(echo -e ${CYAN}${prompt}${NC} [Y/n]: )" answer
        else
            read -r -p "$(echo -e ${CYAN}${prompt}${NC} [y/N]: )" answer
        fi

        answer=$(to_lower "$(trim "$answer")")
        [ -z "$answer" ] && answer="$default"

        case "$answer" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
        esac
    done
}

#===============================================================================
# 菜单选择
#===============================================================================
menu_select() {
    local title="$1"
    shift
    local options=("$@")
    local num_options=${#options[@]}
    local choice

    echo -e "${CYAN}┌────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}$title${NC}"
    echo -e "${CYAN}├────────────────────────────────────────┤${NC}"

    for i in "${!options[@]}"; do
        local idx=$((i + 1))
        local text="${options[$i]}"
        echo -e "${CYAN}│${NC}  [${idx}] $text"
    done

    echo -e "${CYAN}└────────────────────────────────────────┘${NC}"
    echo -e -n "${CYAN}> 请输入选项 (1-${num_options}): ${NC}"

    read -r choice

    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$num_options" ]; then
        return $((choice - 1))
    else
        log_error "无效选项"
        return 255
    fi
}
