# 活跃上下文 (Active Context)

## 当前任务

### 任务 33: 安装包在全新机器上 venv 无法运行问题

**问题描述**:
- 在全新机器上安装 CPU 版本后运行 start_web.bat
- 报错: `No Python at 'C:\Users\jiang\AppData\Local\Programs\Python\Python311\python.exe'`
- 但在本地已配置环境的机器上不会报错

**根本原因**:
- 打包的 venv 中的 `pyvenv.cfg` 指向构建机器的绝对路径:
  ```
  home = C:\Users\jiang\AppData\Local\Programs\Python\Python311
  executable = C:\Users\jiang\AppData\Local\Programs\Python\Python311\python.exe
  ```
- 在全新机器上，这个路径不存在，导致 Python 无法启动

**修复方案**:
1. 打包时同时包含 venv 和 embeddable Python
2. start_web.bat 首次运行时检测 venv 是否有效
3. 如果无效，使用 embeddable Python 重新创建 venv

**已修改文件**:
- `installer/build.ps1` - 添加 -Version 参数支持
- `installer/compile.ps1` - 从 version.txt 读取版本号
- `installer/scripts/start_web.bat` - 添加 venv 检测和重建逻辑
- `installer/installer.iss` - 添加 venv 和 python 目录打包
- `installer/installer-gpu.iss` - 同上

**待验证**:
- 在全新机器上安装测试
- 确认 start_web.bat 能正确检测并重建 venv
- 确认 Web 服务能正常启动

**start_web.bat 修复逻辑**:
```batch
REM 检测 venv 是否有效
set "VENV_VALID=0"
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" --version >nul 2>&1
    if !errorlevel! equ 0 set "VENV_VALID=1"
)

REM 如果无效，删除并重建
if !VENV_VALID! equ 0 (
    rmdir /s /q "%APP_ROOT%\venv"
    "%EMBED_PYTHON%" -m venv "%APP_ROOT%\venv"
    xcopy /e /y "%APP_ROOT%\python\Lib\site-packages\*" "%APP_ROOT%\venv\Lib\site-packages\"
)
```

**当前状态**:
- 本地打包完成，安装包已生成在 `installer/Output/`
- 版本 1.0.0，CPU 和 GPU 两个版本
- 需要在全新机器上验证修复是否生效

---

## 历史任务

### 任务 24: 增强一键部署脚本 [已完成]
**状态**: ✅ 完成

**修改内容**:
- deploy.ps1: 添加 -Daemon/-d、-Stop/-s、-Status/-t、-Port/-p、-Bind/-b、-Force/-f 参数
- deploy.sh: 添加 -d/--daemon、-s/--stop、-t/--status、-f/--force、-p/--port、-b/--bind 参数
- 两脚本都支持后台启动、停止、状态查询功能
- PID 文件: .wingscribe.pid

---

### 任务 26: SQLite 数据库本地存储与定期备份 [已完成]
**状态**: ✅ 完成

**实现**:
- db_path 默认相对于运行目录，不设置时自动使用 `data/db/wingscribe.db`
- 支持绝对路径配置
- 创建备份脚本: `scripts/backup_db.ps1` (Windows) / `scripts/backup_db.sh` (Linux)

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
