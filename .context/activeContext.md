# 活跃上下文 (Active Context)

## 当前任务

### 任务 24: 增强一键部署脚本 [已完成]
**状态**: ✅ 完成

**修改内容**:
- deploy.ps1: 添加 -Daemon/-d、-Stop/-s、-Status/-t、-Port/-p、-Bind/-b、-Force/-f 参数
- deploy.sh: 添加 -d/--daemon、-s/--stop、-t/--status、-f/--force、-p/--port、-b/--bind 参数
- 两脚本都支持后台启动、停止、状态查询功能
- PID 文件: .wingscribe.pid

---

### 任务 21.x 修复文件夹路径和UI问题 [已完成]
**状态**: ✅ 完成 (提交: `60baad9`)

**修复内容**:
- [X] 问题1: 返回正确的相对路径（包含source前缀）
- [X] 问题2: 排除回收站文件夹
- [X] 问题3: Tab按钮高亮颜色

---

### 任务 21.2 修复 Pipeline 执行后UI状态和刷新问题 [已完成]
**状态**: ✅ 完成 (提交: `475101b`)

**修复内容**:
- [X] 问题1: 修改日志检测，匹配 "Pipeline completed"
- [X] 问题2: 添加 loadStats() 刷新统计数据

---

### 任务 21.3 修复 Pipeline UI展示问题 [已完成]
**状态**: ✅ 完成 (提交: `9f0669d`)

**修复内容**:
- [X] 问题1: 第二次执行日志不显示 - 改为追加日志
- [X] 问题2: 文件夹模式不显示箭头
- [X] 问题3: history表格文件夹路径分行显示

---

### 任务 21.4 修复 Pipeline 路径生成问题 [已完成]
**状态**: ✅ 完成 (提交: `37346a0`)

**修复内容**:
- [X] 问题1&3: 修改 run_by_folders 使用正确的 source_root
- [X] 问题2: 随问题1一起修复（未再复现）

---

### 任务 21: Pipeline 执行页面增加按文件和文件夹执行功能 [已完成]
**状态**: ✅ 完成 (合并到 master 后生效)

**涉及文件**:
- src/metadata/ioc_manager.py
- src/pipeline_runner.py
- src/web/app.py
- src/web/templates/admin.html
- `src/metadata/ioc_manager.py`
- `src/pipeline_runner.py`
- `src/web/app.py`
- `src/web/templates/index.html`

---

## 已完成任务

### 1. HuggingFace 镜像下载问题
- 修改 `inference_local.py` 使用 lazy import
- 修改 `factory.py` 传递 hf_mirror 参数

### 2. Factory Reset 安全问题
- 添加保护逻辑，禁止删除源目录
- 修改确认对话框提示

### 3. 裁切图片路径重复修复
- 添加 `_normalize_source_structure()` 方法

### 4. Batch Processing 日志显示修复
- 添加调试和错误处理代码

### 5. 首页翻页按钮消失修复
- 在 index.html 模板中添加静态分页按钮

### 20. Linux 下原图切换无效问题
- 已完成并提交

### 22. 照片切换功能改用按钮切换
- 已完成并提交 (`adc318d`)

### 25. 物种分类列表性能优化
- **方案 A**: 为 photos 表添加索引，重写 get_taxonomy_tree() 使用单次 SQL 查询 (PR #7, 提交: 9cdad4c)
- **方案 C**: 添加预计算 species_stats 表和相关方法 (PR #8, 提交: 4228b10)

---

## 待处理任务

### 任务 23: 新增鸟种统计页面
- **目标**: 新增一个页面显示拍到过的鸟种统计信息
- **需求**:
  - 显示鸟种总数
  - 显示鸟种列表（类似当前侧边栏的展示方式）
  - 不显示照片数量
  - 支持点击后跳转到该鸟种的筛选页面
