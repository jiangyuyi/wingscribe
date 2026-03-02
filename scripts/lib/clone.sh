#!/bin/bash
#===============================================================================
# WingScribe 一键部署脚本 - 项目克隆模块
#===============================================================================

# 加载通用函数
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

# 初始化配置
init_config_dir

#===============================================================================
# 获取项目 URL
#===============================================================================
get_project_url() {
    # 优先使用 Gitee 镜像
    if [ -n "$GITEE_MIRROR" ]; then
        echo "$GITEE_MIRROR"
    else
        echo "$GITHUB_ORIGIN"
    fi
}

#===============================================================================
# 检测是否需要配置代理
#===============================================================================
check_proxy_config() {
    if [ -n "$PROXY" ]; then
        log_info "使用代理: $PROXY"
        export http_proxy="$PROXY"
        export https_proxy="$PROXY"
    fi
}

#===============================================================================
# 克隆项目
#===============================================================================
clone_project() {
    local target_dir="${1:-$PROJECT_ROOT}"
    local repo_url="$(get_project_url)"
    local branch="${2:-master}"

    log_step "克隆项目到 $target_dir"

    # 检查是否已存在
    if [ -d "${target_dir}/.git" ]; then
        log_info "项目已存在，检查更新..."

        # 尝试更新
        local current_url=$(git -C "$target_dir" remote get-url origin 2>/dev/null || echo "")
        log_debug "当前远程 URL: $current_url"

        # 如果远程 URL 不同，提示用户
        if [ "$current_url" != "$repo_url" ]; then
            log_warn "远程仓库 URL 不匹配"
            log_warn "当前: $current_url"
            log_warn "期望: $repo_url"

            if ask_yes_no "是否更新远程仓库地址?" "n"; then
                git -C "$target_dir" remote set-url origin "$repo_url"
                log_info "远程仓库地址已更新"
            fi
        fi

        # 记录是否原本是 GitHub
        local isGithub=false
        if [[ "$(git -C "$target_dir" remote get-url origin 2>/dev/null)" == *"github.com"* ]]; then
             isGithub=true
             # 如果是 GitHub，为了速度，先换成 Gitee（如果 repo_url 指向 Gitee）
             if [[ "$repo_url" == *"gitee.com"* ]]; then
                 log_info "Using Gitee mirror for fast update..."
                 git -C "$target_dir" remote set-url origin "$repo_url"
             fi
        fi

        # 拉取更新
        log_info "正在拉取更新..."
        git -C "$target_dir" pull origin "$branch" 2>/dev/null
        local pullStatus=$?

        # 如果原本是 GitHub，改回去
        if [ "$isGithub" = true ]; then
            log_info "Restoring remote to GitHub..."
            git -C "$target_dir" remote set-url origin "$GITHUB_ORIGIN" 2>/dev/null
        fi

        if [ $pullStatus -eq 0 ]; then
            log_success "项目已更新到最新版本"
            return 0
        else
            log_warn "拉取更新失败，可能有本地修改"
            return 1
        fi
    fi

    # 克隆新副本
    log_info "从 $repo_url 克隆..."

    if [ "$target_dir" = "$PROJECT_ROOT" ]; then
        # 在当前目录克隆 (需要处理空目录)
        if [ "$(ls -A "$target_dir" 2>/dev/null)" ]; then
            log_error "目标目录非空，请选择其他目录或清理"
            return 1
        fi
        git clone --depth 1 -b "$branch" "$repo_url" "$target_dir"
    else
        # 克隆到子目录
        ensure_dir "$(dirname "$target_dir")"
        git clone --depth 1 -b "$branch" "$repo_url" "$target_dir"
    fi

    if [ $? -eq 0 ] && [ -f "${target_dir}/settings.yaml" ]; then
        log_success "项目克隆成功"
        
        # 自动改回 GitHub
        if [[ "$repo_url" == *"gitee.com"* ]]; then
            log_info "Setting remote to GitHub..."
            git -C "$target_dir" remote set-url origin "$GITHUB_ORIGIN" 2>/dev/null
        fi
        
        return 0
    else
        log_error "项目克隆失败"
        return 1
    fi
}

#===============================================================================
# 使用 GitHub 代理克隆 (备用方案)
#===============================================================================
clone_with_gh_proxy() {
    local target_dir="${1:-$PROJECT_ROOT}"
    local repo_url="$GITHUB_ORIGIN"

    log_step "使用 GitHub 代理克隆..."

    # 常见的 GitHub 代理
    local proxies=(
        "https://ghproxy.com/"
        "https://ghproxy.net/"
        "https://pd.zwc365.com/"
        "https://mirror.ghproxy.com/"
    )

    for proxy in "${proxies[@]}"; do
        log_info "尝试代理: $proxy"

        if git clone --depth 1 -b master "${proxy}${repo_url}" "$target_dir" 2>/dev/null; then
            log_success "通过 $proxy 克隆成功"
            save_config "PROXY" "$proxy"
            return 0
        fi
    done

    log_error "所有代理均失败，请手动配置代理"
    return 1
}

#===============================================================================
# 切换到 GitHub 原始仓库 (用于开发者)
#===============================================================================
switch_to_github() {
    log_step "切换到 GitHub 原始仓库..."

    if [ ! -d "${PROJECT_ROOT}/.git" ]; then
        log_error "不是 Git 仓库"
        return 1
    fi

    if ask_yes_no "是否将远程仓库切换到 GitHub 原始地址?" "n"; then
        git -C "$PROJECT_ROOT" remote set-url origin "$GITHUB_ORIGIN"
        log_success "已切换到 GitHub 原始仓库"
        return 0
    fi

    return 1
}

#===============================================================================
# 下载模型文件
#===============================================================================
download_model() {
    local model_dir="${PROJECT_ROOT}/data/models"
    local model_cache_dir="${model_dir}/bioclip"

    log_step "下载 BioCLIP 模型..."

    # 确保目录存在
    ensure_dir "$model_cache_dir"

    # 使用 huggingface-cli 下载
    if command_exists huggingface-cli; then
        # 配置镜像
        export HF_ENDPOINT="$HF_MIRROR"

        log_info "从 HuggingFace 下载 BioCLIP 模型..."
        huggingface-cli download imageomics/bioclip --local-dir "$model_cache_dir"

        if [ $? -eq 0 ]; then
            log_success "模型下载完成"
            return 0
        fi
    fi

    # 备用: 使用 Python 下载
    log_info "使用 Python 下载模型..."

    if [ -n "$PYTHON_CMD" ]; then
        local python_script="
import os
from huggingface_hub import snapshot_download

HF_MIRROR = os.environ.get('HF_ENDPOINT', '${HF_MIRROR}')
os.environ['HF_ENDPOINT'] = HF_MIRROR

try:
    snapshot_download(
        repo_id='imageomics/bioclip',
        local_dir='${model_cache_dir}',
        resume_download=True
    )
    print('下载完成')
except Exception as e:
    print(f'下载失败: {e}')
    exit(1)
"

        $PYTHON_CMD -c "$python_script"
        if [ $? -eq 0 ]; then
            log_success "模型下载完成"
            return 0
        fi
    fi

    log_error "模型下载失败，请手动下载"
    log_info "模型下载地址: https://huggingface.co/imageomics/bioclip"
    return 1
}

#===============================================================================
# 下载参考数据 (IOC 鸟类分类表)
#===============================================================================
download_reference_data() {
    local ref_dir="${PROJECT_ROOT}/data/references"

    log_step "下载参考数据..."

    ensure_dir "$ref_dir"

    # 检查是否已有数据
    if [ -f "${ref_dir}/Multiling IOC 15.1_d.xlsx" ]; then
        log_info "参考数据已存在，跳过下载"
        return 0
    fi

    # 提示用户下载
    log_warn "需要下载 IOC 鸟类分类数据"
    log_info "请从以下地址下载并保存到 $ref_dir:"
    log_info "  - IOC World Bird List: https://www.worldbirdnames.org/"
    log_info "  - 直接下载: https://github.com/jiangyuyi/wingscribe/raw/master/data/references/"

    if ask_yes_no "是否尝试自动下载?" "n"; then
        local files=(
            "https://github.com/jiangyuyi/wingscribe/raw/master/data/references/Multiling%20IOC%2015.1_d.xlsx"
        )

        for url in "${files[@]}"; do
            local filename=$(basename "$url" | tr '%' ' ')
            local output="${ref_dir}/${filename}"

            log_info "下载 $filename..."

            if download_file "$url" "$output" "下载中"; then
                log_success "$filename 下载完成"
                return 0
            fi
        done
    fi

    log_warn "参考数据下载跳过，请手动处理"
    return 1
}

#===============================================================================
# 初始化子模块
#===============================================================================
init_submodules() {
    if [ -f "${PROJECT_ROOT}/.gitmodules" ]; then
        log_step "初始化子模块..."

        git submodule update --init --recursive

        if [ $? -eq 0 ]; then
            log_success "子模块初始化完成"
            return 0
        else
            log_warn "子模块初始化失败"
            return 1
        fi
    fi

    return 0
}

#===============================================================================
# 完整安装流程
#===============================================================================
full_install() {
    local failed=0

    # 1. 克隆/更新项目
    if ! clone_project; then
        if ask_yes_no "克隆失败，是否尝试使用代理?" "y"; then
            clone_with_gh_proxy || failed=1
        else
            failed=1
        fi
    fi

    # 2. 初始化子模块
    [ $failed -eq 0 ] && init_submodules

    # 3. 下载模型
    if [ $failed -eq 0 ]; then
        if ask_yes_no "是否下载 BioCLIP 模型 (约 500MB)?" "y"; then
            download_model || log_warn "模型下载失败，可以稍后手动下载"
        fi
    fi

    # 4. 下载参考数据
    if [ $failed -eq 0 ]; then
        download_reference_data || log_warn "参考数据缺失"
    fi

    if [ $failed -eq 0 ]; then
        log_success "项目初始化完成"
        return 0
    else
        log_error "部分步骤失败"
        return 1
    fi
}
