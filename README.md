# Image Pro — 本地照片整理工具

面向摄影师的本地离线照片整理工作台。以"任务"为单位处理文件夹，支持扫描、查重、时间修正、GPS 匹配、AI 筛图五大核心功能。所有破坏性操作均需用户二次确认，文件删除走系统回收站。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ / FastAPI + SQLAlchemy (async) + SQLite |
| 前端 | Vue 3 + TypeScript + Vite / Naive UI / Pinia |
| 图像处理 | Pillow、OpenCV、piexif、exifread、imagehash、xxhash |
| AI/ML | PyTorch + OpenCLIP (ViT-L/14)，本地 GPU 推理 |
| 实时通信 | WebSocket（长任务进度推送） |

目标平台：Windows（i7-13700K + RTX 4070 Ti Super）

---

## 快速启动

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev        # Vite dev server，代理 API 到 :8000
```

生产构建：`cd frontend && npm run build`，后端自动 serve `frontend/dist/`。

> **AI 筛图依赖**：需手动下载 CLIP 模型文件（约 2.5 GB）放到
> `backend/model/CLIP-ViT-L-14-laion2B-s32B-b82K/open_clip_pytorch_model.bin`，否则后端启动失败。

---

## 功能模块

### 1. 任务扫描

入口：侧边栏「扫描概览」

用户选择本地文件夹创建任务，后端递归扫描所有文件并分类（image / video / other）。

**实现要点**：
- 使用 `python-magic` 识别 MIME 类型，`pillow-heif` 支持 HEIC 格式
- 扫描过程通过 WebSocket 实时推送进度（已扫描数 / 总数）
- 扫描结果写入 `files` 表，记录路径、大小、修改时间、文件类型
- 同一任务重复扫描时，以 `(file_path, file_size, file_modified)` 为缓存键，跳过未变更文件

---

### 2. 查重检测

入口：侧边栏「查重检测」

两条并行流水线，分别处理精确重复和相似图片。

**Pipeline A — 精确查重**：
1. 按文件大小分组，过滤掉唯一大小的文件
2. 对候选文件计算 xxHash（首尾各 8 KB），再次分组
3. 对仍有碰撞的文件计算完整 SHA-256，确认精确重复

**Pipeline B — 相似图查重**：
1. 对所有图片计算 dHash（8×8，64-bit 感知哈希）
2. 用 numpy 批量计算汉明距离矩阵
3. Union-Find 聚类，阈值可选：宽松（≤4）/ 标准（≤8）/ 严格（≤12）

**推荐保留策略**（优先级从高到低）：分辨率 → 文件大小 → 有 EXIF → 标准文件名 → 路径最短

用户可对每个重复组内的文件标记「保留」或「删除」，确认后批量移入系统回收站（`send2trash`）。

---

### 3. EXIF / 时间修正

入口：侧边栏「时间/EXIF」

读取照片拍摄时间，检测时间异常，支持手动修正和批量偏移。

**时间来源优先级**：EXIF > 文件名解析 > 文件修改时间 > 文件创建时间

**异常类型**（可组合）：
- `no_exif`：无 EXIF 信息
- `future_time`：拍摄时间晚于当前时间
- `too_old`：拍摄时间早于 2000-01-01
- `exif_fs_mismatch`：EXIF 时间与文件系统时间偏差超过 24 小时

**实现要点**：
- `exifread` 读取 EXIF，`piexif` 写入 JPEG EXIF
- 文件名解析支持 `20230815_143022`、`2023-08-15T14:30:22` 等常见格式
- 所有时间以 UTC 存储，前端展示时加 8 小时转为 UTC+8
- 批量偏移：选中多个文件，输入小时/分钟偏移量，一键应用
- 单文件修正：日期时间选择器，修改后同步写入 JPEG 物理文件

---

### 4. GPX 地理匹配

入口：侧边栏「GPS 匹配」

将 GPX 轨迹文件与照片拍摄时间匹配，为照片打上 GPS 坐标。

**匹配算法**：
1. 用 `gpxpy` 解析 GPX 文件，提取轨迹点 `(UTC时间, 纬度, 经度)`
2. 支持多 GPX 文件合并（多设备、多天轨迹），按时间排序去重
3. 对每张照片的 `best_time`（UTC）做**二分查找**，找到前后两个轨迹点
4. 在两点之间做**线性插值**计算精确坐标
5. 时间偏差 ≤5 分钟标记为 `good`，>5 分钟标记为 `warning`

**两阶段操作**：
- **匹配阶段**：仅写数据库，用户可审查结果
- **写入阶段**：用户确认后，将坐标写入 JPEG EXIF（`piexif`），支持「仅补写无 GPS」和「覆盖所有」两种模式

**轨迹可视化**：纯 SVG 渲染，无外部地图依赖
- 蓝色折线绘制 GPX 轨迹（超过 2000 点时均匀降采样）
- 绿点（偏差良好）/ 橙点（偏差较大）标注照片位置
- 支持滚轮缩放、拖拽平移，hover 显示文件名和匹配详情
- 坐标点可点击跳转 Google Maps 验证

---

### 5. AI 筛图

入口：侧边栏「AI 筛图」

基于 OpenCLIP 特征 + 轻量分类器，学习用户的筛图偏好，批量预测「保留/删除」。

**工作流**：
1. **特征提取**：用 OpenCLIP ViT-L/14 提取每张图片的 768 维特征向量，缓存到数据库（`files.clip_feature`），重复运行跳过已提取文件
2. **手动标注**：用户对图片标记「保留」或「删除」，冷启动需约 200 个样本
3. **训练分类器**：2 层 MLP（768→256→1），使用 Focal Loss 处理类别不平衡，训练前自动备份旧模型
4. **批量预测**：对未标注图片打分（0~1 保留概率），展示置信度
5. **执行删除**：用户确认后，将预测为「删除」的文件移入回收站

**模型版本管理**：最多保留 15 个历史版本（循环覆盖），支持一键回滚。

---

## 数据库结构

SQLite，核心表：

| 表 | 说明 |
|---|---|
| `tasks` | 任务（文件夹路径、状态、文件统计） |
| `files` | 文件（哈希、EXIF、GPS、CLIP 特征、时间字段） |
| `duplicate_groups` / `duplicate_group_members` | 重复组及成员 |
| `gpx_matches` | GPX 匹配结果（坐标、偏差、质量） |
| `ai_labels` | AI 标注和预测结果 |
| `ai_model_versions` | 模型版本历史 |
| `operation_logs` | 所有文件操作记录（删除/移动/EXIF 写入/GPS 写入） |

运行时数据（数据库、缩略图、AI 模型）存放在 `data/` 目录，不纳入版本控制。

---

## 并发模型

- **I/O 密集型**（文件哈希）：`ThreadPoolExecutor(16)`，hashlib/xxhash 释放 GIL
- **CPU 密集型**（图像解码计算 dHash）：`ProcessPoolExecutor(8)`，绕过 GIL
- **AI 推理**：`ThreadPoolExecutor`，PyTorch CUDA 推理不阻塞事件循环
- **长任务进度**：`asyncio.create_task` 后台运行，WebSocket 推送进度事件

---

## 项目结构

```
image-pro/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 全局配置
│   ├── requirements.txt
│   ├── api/                 # 路由层（每模块一文件）
│   │   ├── tasks.py / scan.py / duplicates.py
│   │   ├── exif.py / gpx.py / ai.py
│   │   └── files.py / logs.py
│   ├── services/            # 业务逻辑层
│   │   ├── scanner.py / hasher.py / duplicate_detector.py
│   │   ├── exif_service.py / gpx_service.py / ai_service.py
│   │   └── thumbnail.py / operation_log.py / ws_manager.py
│   └── database/            # ORM 模型 + 连接管理
├── frontend/
│   └── src/
│       ├── views/           # 页面组件（每模块一个）
│       ├── components/      # 可复用组件（含 GpxTrackMap SVG）
│       ├── stores/          # Pinia 状态（task / app）
│       ├── api/             # axios 封装
│       └── router/          # Vue Router
└── data/                    # 运行时数据（不入版本控制）
    ├── image_pro.db
    ├── thumbnails/
    └── models/
```
