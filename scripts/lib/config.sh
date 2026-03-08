#!/bin/bash
#===============================================================================
# WingScribe 一键部署脚本 - 配置向导模块
#===============================================================================

# 加载通用函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
source "${SCRIPT_DIR}/detect.sh"

# 初始化配置
init_config_dir

#===============================================================================
# 配置向导主函数
#===============================================================================
run_config_wizard() {
    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}⚙️  飞羽志配置向导${NC}"
    echo -e "${CYAN}├────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  此向导将帮助您配置必要的设置"
    echo -e "${CYAN}│${NC}  必填项用 ${GREEN}*[星号]${NC} 标记"
    echo -e "${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────┘${NC}"
    echo ""

    # 重新检测环境
    detect_environment

    echo ""

    # 1. 配置照片源目录
    config_source_dir

    # 2. 配置输出目录
    config_output_dir

    # 3. 配置处理设备
    config_device

    # 4. 配置代理 (可选)
    config_proxy

    # 5. 保存配置
    save_all_config

    # 6. 显示配置摘要
    show_config_summary
}

#===============================================================================
# 配置照片源目录
#===============================================================================
config_source_dir() {
    echo ""
    log_step "配置照片源目录"

    local default_dir=""
    local detected_dir=""

    # 尝试检测常见照片目录
    if is_windows; then
        detected_dir=$(cmd //c "echo %USERPROFILE%/Pictures" 2>/dev/null | tr -d '\r')
    elif is_macos; then
        detected_dir="$HOME/Pictures"
    else
        detected_dir="$HOME/图片"
    fi

    if [ -d "$detected_dir" ]; then
        default_dir="$detected_dir"
        log_info "检测到照片目录: $default_dir"
    fi

    echo ""
    echo -e "${GREEN}*[必填]${NC} 请输入您的鸟片照片所在目录路径"
    echo -e "${WHITE}提示:${NC} 目录结构建议: ${WHITE}年/日期_地点/${NC}"
    echo -e "${WHITE}示例:${NC} 2024/20240101_颐和园/*.jpg"
    echo ""

    while true; do
        local input
        if [ -n "$default_dir" ]; then
            input=$(ask_input "照片源目录" "$default_dir")
        else
            input=$(ask_input "照片源目录")
        fi

        input=$(trim "$input")
        input=$(echo "$input" | sed 's/["'\'']//g')  # 移除引号

        if [ -z "$input" ]; then
            log_error "目录不能为空"
            continue
        fi

        # 转换为绝对路径
        if [[ ! "$input" =~ ^/ ]] && [[ ! "$input" =~ ^[A-Za-z]: ]]; then
            input="$(pwd)/$input"
        fi

        if [ -d "$input" ]; then
            SOURCE_DIR="$input"
            save_config "SOURCE_DIR" "\"$input\""
            log_success "照片源目录: $SOURCE_DIR"
            break
        else
            log_error "目录不存在: $input"

            if ask_yes_no "是否创建此目录?" "y"; then
                ensure_dir "$input"
                if [ -d "$input" ]; then
                    SOURCE_DIR="$input"
                    save_config "SOURCE_DIR" "\"$input\""
                    log_success "目录已创建: $SOURCE_DIR"
                    break
                fi
            fi
        fi
    done
}

#===============================================================================
# 配置输出目录
#===============================================================================
config_output_dir() {
    echo ""
    log_step "配置输出目录"

    local default_dir="${PROJECT_ROOT}/data/processed"
    local parent_dir=$(dirname "$default_dir")

    echo ""
    echo -e "${GREEN}*[必填]${NC} 处理后的照片将保存到以下目录"
    echo ""

    while true; do
        local input=$(ask_input "输出目录" "$default_dir")
        input=$(trim "$input")
        input=$(echo "$input" | sed 's/["'\'']//g')

        if [ -z "$input" ]; then
            log_error "目录不能为空"
            continue
        fi

        # 转换为绝对路径
        if [[ ! "$input" =~ ^/ ]] && [[ ! "$input" =~ ^[A-Za-z]: ]]; then
            input="$(pwd)/$input"
        fi

        # 检查父目录是否可写
        if [ ! -d "$parent_dir" ]; then
            ensure_dir "$parent_dir"
        fi

        OUTPUT_DIR="$input"
        save_config "OUTPUT_DIR" "\"$input\""
        log_success "输出目录: $OUTPUT_DIR"
        break
    done
}

#===============================================================================
# 配置处理设备
#===============================================================================
config_device() {
    echo ""
    log_step "配置处理设备"

    # 检测 GPU
    detect_gpu

    echo ""
    if [ $HAS_GPU -eq 1 ]; then
        echo -e "${GREEN}*[建议]${NC} 检测到 GPU: ${WHITE}$GPU_INFO${NC}"
        echo "  使用 GPU 可以显著加速 AI 识别"
        echo ""
    else
        echo -e "${YELLOW}*[注意]${NC} 未检测到兼容的 GPU，将使用 CPU 进行处理"
        echo "  (如需使用 GPU，请确保已安装 CUDA 驱动)"
        echo ""
    fi

    local options=()
    local default_choice=1

    if [ $HAS_GPU -eq 1 ]; then
        options+=("自动检测 (推荐)")
        options+=("CUDA (GPU)")
        default_choice=1
    fi
    options+=("CPU (慢但稳定)")
    options+=("手动指定")

    menu_select "选择处理设备" "${options[@]}"
    local choice=$?

    case $choice in
        0)
            if [ $HAS_GPU -eq 1 ]; then
                DEVICE="auto"
            else
                DEVICE="cpu"
            fi
            ;;
        1)
            DEVICE="cuda"
            ;;
        2)
            DEVICE="cpu"
            ;;
        3)
            DEVICE=$(ask_input "请输入设备类型" "cuda")
            ;;
    esac

    save_config "DEVICE" "$DEVICE"
    log_success "处理设备: $DEVICE"
}

#===============================================================================
# 配置代理
#===============================================================================
config_proxy() {
    echo ""
    log_step "配置代理 (可选)"

    echo ""
    echo "如果您在国内可能无法直接访问 GitHub/HuggingFace，请配置代理"
    echo ""

    local current_proxy="$PROXY"
    if [ -z "$current_proxy" ]; then
        current_proxy="留空表示不使用代理"
    fi

    local input=$(ask_input "代理地址 (http://host:port)" "$current_proxy")
    input=$(trim "$input")

    if [ -n "$input" ] && [ "$input" != "留空表示不使用代理" ]; then
        PROXY="$input"
        save_config "PROXY" "\"$input\""
        log_success "代理已配置: $PROXY"
    else
        PROXY=""
        save_config "PROXY" "\"\""
        log_info "不使用代理"
    fi
}

#===============================================================================
# 保存所有配置
#===============================================================================
save_all_config() {
    echo ""
    log_step "保存配置..."

    # 标记为已配置
    save_config "CONFIGURED" "1"

    # 保存其他检测到的信息
    if [ -n "$PYTHON_CMD" ]; then
        save_config "PYTHON_CMD" "$PYTHON_CMD"
    fi

    if [ $HAS_GPU -eq 1 ]; then
        save_config "HAS_GPU" "1"
        save_config "GPU_INFO" "\"$GPU_INFO\""
    else
        save_config "HAS_GPU" "0"
    fi

    log_success "配置已保存到 $CONFIG_FILE"
}

#===============================================================================
# 显示配置摘要
#===============================================================================
show_config_summary() {
    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}📋 配置摘要${NC}"
    echo -e "${CYAN}├────────────────────────────────────────┤${NC}"

    echo -e "${CYAN}│${NC}  照片源目录:    $SOURCE_DIR"
    echo -e "${CYAN}│${NC}  输出目录:      $OUTPUT_DIR"
    echo -e "${CYAN}│${NC}  处理设备:      $DEVICE"

    if [ -n "$PROXY" ]; then
        echo -e "${CYAN}│${NC}  代理:          $PROXY"
    fi

    echo -e "${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}  ${GREEN}配置完成！${NC}"
    echo -e "${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}后续步骤:${NC}"
    echo -e "${CYAN}│${NC}  1. 运行 [安装依赖] 安装 Python 包"
    echo -e "${CYAN}│${NC}  2. 运行 [启动服务] 启动 Web 界面"
    echo -e "${CYAN}│${NC}  3. 在浏览器访问 http://localhost:8000"
    echo -e "${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────┘${NC}"
}

#===============================================================================
# 生成 settings.yaml
#===============================================================================
generate_settings_yaml() {
    local settings_file="${PROJECT_ROOT}/config/settings.yaml"

    log_step "生成配置文件..."

    # 备份现有配置
    if [ -f "$settings_file" ]; then
        backup_file "$settings_file"
    fi

    # 生成新配置
    # 计算相对于 base_dir 的输出目录
    local relative_output_dir="${OUTPUT_DIR#${SOURCE_DIR}/}"

    cat > "$settings_file" << EOF
# WingScribe 配置文件
# 由一键部署脚本自动生成
# 时间: $(date '+%Y-%m-%d %H:%M:%S')

paths:
  base_dir: "${SOURCE_DIR}"

  references_path: "data/references"

  sources:
    - path: "."
      recursive: true
      enabled: true

  output:
    root_dir: "${relative_output_dir}"
    structure_template: "{source_structure}/{filename}_{species_cn}_{confidence}"
    write_back_to_source: false

  db_path: "data/db/wingscribe.db"
  ioc_list_path: "data/references/Multiling IOC 15.1_d.xlsx"
  cn_taxonomy_path: "data/references/动物界-脊索动物门-2025-10626.xlsx"
  china_list: "config/dictionaries/china_bird_list.txt"
  foreign_list: "config/dictionaries/foreign_countries.txt"
  model_cache_dir: "data/models"

processing:
  device: "${DEVICE}"
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

  local:
    model_type: "bioclip-2"
    batch_size: 512
    inference_batch_size: 16

  api:
    url: "https://router.huggingface.co/models/imageomics/bioclip"
    key: ""

  dongniao:
    url: "https://ai.open.hhodata.com/api/v2/dongniao"
    key: ""

web:
  host: "0.0.0.0"
  port: 8000
EOF

    log_success "配置文件已生成: $settings_file"
}

#===============================================================================
# 生成 secrets.yaml
#===============================================================================
generate_secrets_yaml() {
    local secrets_file="${PROJECT_ROOT}/config/secrets.yaml"
    local secrets_example="${PROJECT_ROOT}/config/secrets.example.yaml"

    if [ -f "$secrets_file" ]; then
        log_info "secrets.yaml 已存在，跳过生成"
        return 0
    fi

    if [ -f "$secrets_example" ]; then
        cp "$secrets_example" "$secrets_file"
        log_success "secrets.yaml 已从示例生成"
        log_warn "请编辑 $secrets_file 添加 API Key"
    else
        cat > "$secrets_file" << 'EOF'
# WingScribe 密钥配置
# 由一键部署脚本自动生成
# 请根据需要填写以下 API Key

# HuggingFace API Key (用于在线识别模式)
hf_api_key: ""

# 东北鸟 API Key
dongniao_api_key: ""
EOF
        log_success "secrets.yaml 已生成"
        log_warn "请根据需要编辑此文件"
    fi
}
