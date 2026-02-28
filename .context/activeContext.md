# 活跃上下文 (Active Context)

## 当前任务

### 任务 21.x 修复文件夹路径和UI问题 [已完成]
**状态**: ✅ 完成 (提交: `60baad9`)

**修复内容**:
- [X] 问题1: 返回正确的相对路径（包含source前缀）
- [X] 问题2: 排除回收站文件夹
- [X] 问题3: Tab按钮高亮颜色

---

### 任务 21: Pipeline 执行页面增加按文件和文件夹执行功能 [已完成]
**状态**: ✅ 完成 (提交: `4e74213`)

**实现完成**:
- [X] 数据库: `get_all_hashes()` 批量查询接口
- [X] Pipeline: `existing_hashes` 参数和 `run_by_folders()` 方法
- [X] API: `/api/pipeline/folders` 和 `/api/pipeline/start_by_folders`
- [X] 前端: Tab 切换和文件夹树形选择组件
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
