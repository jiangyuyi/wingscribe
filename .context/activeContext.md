# 活跃上下文 (Active Context)

## 当前任务

### 修复: Python venv 无法调用 GPU

**任务类型**: Bug修复
**开始日期**: 2026-02-23
**状态**: 🔄 待开始

---

## 任务详情

### 问题分析
在 Python venv 中无法正常调用显卡，始终回落到 CPU 执行：
1. 可能是 venv 中安装的 PyTorch 版本不支持 CUDA
2. 可能是 pip 安装时选择了 CPU 版本的 PyTorch
3. 需要检查 venv 中实际安装的 PyTorch 版本

### 排查计划
1. 检查系统全局 PyTorch GPU 支持情况
2. 检查 venv 中 PyTorch 版本和 CUDA 支持
3. 修复 deploy.ps1 中的 PyTorch 安装逻辑

---

## 当前状态

- CUDA 修复已完成并提交 (59a2213)
- deploy.ps1 路径问题已修复并提交 (48e9ff5)
- GPU venv 问题待排查

---

## 历史记录

### 2026-02-23
- **CUDA修复**: 已完成 - 提交: `59a2213`
- **deploy.ps1路径**: 已完成 - 提交: `48e9ff5`
- **Docker移除**: 完成 - 提交: `978befa`
