# 活跃上下文 (Active Context)

## 当前任务

### 修复: Python venv 无法调用 GPU

**任务类型**: Bug修复
**开始日期**: 2026-02-23
**状态**: ✅ 已完成

---

## 任务详情

### 问题分析
在 Python venv 中无法正常调用显卡，始终回落到 CPU 执行：
- requirements.txt 中只写了 `torch`，pip 默认安装 CPU 版本

### 修复内容
- 检测系统 CUDA 版本
- 根据 CUDA 12.x/11.x 安装对应版本的 PyTorch
- 从 PyTorch 官方源安装 CUDA 版本

---

## 当前状态

- CUDA 修复已完成并提交 (59a2213)
- deploy.ps1 路径问题已修复并提交 (48e9ff5)
- GPU venv 问题已修复并提交 (3a01a8d)

---

## 历史记录

### 2026-02-23
- **GPU venv修复**: 已完成 - 提交: `3a01a8d`
- **CUDA修复**: 已完成 - 提交: `59a2213`
- **deploy.ps1路径**: 已完成 - 提交: `48e9ff5`
- **Docker移除**: 完成 - 提交: `978befa`
