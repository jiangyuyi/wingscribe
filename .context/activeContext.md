# 活跃上下文 (Active Context)

## 当前任务

### 修复: PyTorch 不支持 RTX 50 系列 (sm_120)

**任务类型**: Bug修复
**开始日期**: 2026-02-23
**状态**: 🔄 进行中

---

## 任务详情

### 问题分析
RTX 5060 Laptop GPU (sm_120) 不被当前 PyTorch 支持：
- PyTorch 稳定版最高支持 sm_90
- nightly 版本尝试中，仍未成功

### 修复尝试
1. 自动检测 RTX 50 系列 GPU
2. 使用 nightly 版本代替稳定版
3. nightly 从 cu121 改为 cu124
4. nightly 跳过 torchaudio

---

## 当前状态

- PyTorch RTX 50 问题排查中
- deploy.ps1 已添加自动检测和 nightly 安装逻辑

---

## 历史记录

### 2026-02-23
- **PyTorch安装**: 多次修复中 - 提交: `8cb47af`
- **GPU venv修复**: 已完成
- **CUDA修复**: 已完成
- **deploy.ps1路径**: 已完成
