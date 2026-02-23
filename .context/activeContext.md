# 活跃上下文 (Active Context)

## 当前任务

### 任务2: 修复物种列表分类显示问题

**任务类型**: Bug修复
**开始日期**: 2026-02-23
**状态**: 🔄 待开始

---

## 任务详情

### 1. 移除 Docker 相关功能 [已完成]
- [X] 删除 Dockerfile.cpu
- [X] 删除 Dockerfile.gpu
- [X] (不存在) Dockerfile.webui - 已移除
- [X] 删除 docker-compose.yml
- [X] (不存在) docker-compose.split.yml
- [X] 删除 docker-compose.remote.yml
- [X] (不存在) docker-compose.dev.yml
- [X] (不存在) docker-compose.split.dev.yml
- [X] 更新 scripts/deploy.sh - 移除Docker相关命令
- [X] 更新 CLAUDE.md（移除Docker引用）
- [X] 删除 nul 文件
- [X] 更新 progress.md

---

### 2. 修复物种列表分类显示问题 [待开始]
**问题**: 物种列表只显示拉丁名，不显示中文名

**排查步骤**:
1. 检查数据库中 taxonomy 表是否有中文名数据
2. 检查前端 `index.html` 渲染逻辑
3. 检查 `ioc_manager.py` 返回的数据结构

---

### 3. 升级 YOLO 到 v11 [待开始]
**目标**: 将 YOLOv8 升级到 YOLOv11

**修改文件**:
- `src/core/detector.py` - 更新模型名称和导入

---

### 4. 切换数据库到 MySQL [待开始]
**目标**: 从 SQLite 迁移到 MySQL，支持远程访问

**推荐**: MySQL 或 PostgreSQL

**修改文件**:
- `src/metadata/ioc_manager.py` - 修改数据库连接逻辑
- `config/settings.yaml` - 添加数据库配置项

---

### 5. 创建精简版 Docker (仅浏览) [待开始]
**目标**: 创建仅包含 Web 浏览功能的轻量级 Docker

**功能范围**:
- 照片浏览
- 分类筛选
- 物种搜索

---

## 当前状态

- 任务1已完成：Docker相关文件已删除
- 代码已提交到 GitHub

---

## 历史记录

### 2026-02-23
- **任务1完成**: 移除Docker相关功能
  - 删除 Dockerfile.cpu, Dockerfile.gpu
  - 删除 docker-compose.yml, docker-compose.remote.yml
  - 更新 deploy.sh 移除Docker命令
  - 更新 CLAUDE.md
- **代码回退**: 回退到 6bfd6be 版本
- **工作计划**: 制定5项重构任务
- **提交**: 0606f2d 回退代码到稳定版本并更新文档
