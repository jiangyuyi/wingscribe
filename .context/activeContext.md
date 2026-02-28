# 活跃上下文 (Active Context)

## 当前任务

### 任务 21: Pipeline 执行页面增加按文件和文件夹执行功能 [待开始]
**状态**: 🔄 计划已确认，等待开始

**需求确认** (2026-02-28):
1. 新增独立的执行选择界面（树形多选）
2. 从配置的 sources 路径扫描文件夹结构
3. 选中文件夹后递归处理所有子文件夹
4. 只处理选中的文件/文件夹，忽略日期范围筛选器
5. 自动跳过库中已存在的文件

**性能优化 - 批量哈希查询**:
- 问题: 现有 `check_hash_exists()` 逐个文件查询数据库，10000文件需10000次SQL
- 优化: 添加 `get_all_hashes()` 批量查询接口，一次获取所有哈希到内存 Set
- 适用: 适合10万级以下文件库

**实现计划**:

#### 阶段 1: 后端 - 数据库优化
- [ ] `src/metadata/ioc_manager.py` - 添加 `get_all_hashes()` 方法

#### 阶段 2: 后端 - Pipeline 扩展
- [ ] `src/pipeline_runner.py` - 添加 `existing_hashes` 参数支持
- [ ] `src/pipeline_runner.py` - 添加 `scan_folders(paths, recursive)` 方法

#### 阶段 3: 后端 - 新增 API
- [ ] `src/web/app.py` - 添加 `/api/pipeline/folders` 获取文件夹树
- [ ] `src/web/app.py` - 添加 `/api/pipeline/start_by_folders` 执行API
- [ ] `src/web/app.py` - TaskManager 支持路径列表模式

#### 阶段 4: 前端 - 新增选择界面
- [ ] `src/web/templates/index.html` - 添加 Tab 切换（日期范围/文件文件夹）
- [ ] 添加文件夹树形选择组件
- [ ] 添加 JavaScript API 调用

**涉及文件**:
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

---

## 待处理任务

### 任务 23: 新增鸟种统计页面
- **目标**: 新增一个页面显示拍到过的鸟种统计信息
- **需求**:
  - 显示鸟种总数
  - 显示鸟种列表（类似当前侧边栏的展示方式）
  - 不显示照片数量
  - 支持点击后跳转到该鸟种的筛选页面
