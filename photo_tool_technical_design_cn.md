# 照片整理工具 — 技术设计文档

## 1. 技术栈概览

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 后端框架 | Python 3.11+ / FastAPI | 异步 Web 框架，提供 REST API + WebSocket |
| 前端框架 | Vue 3 + Vite + TypeScript | SPA 单页应用 |
| UI 组件库 | Naive UI | 功能丰富、TypeScript 友好、主题可定制 |
| 数据库 | SQLite（通过 SQLAlchemy） | 本地持久化，无需外部数据库服务 |
| 图像处理 | Pillow / OpenCV | 缩略图生成、格式转换、图像读取 |
| EXIF 处理 | piexif / exifread | EXIF 读取与写入 |
| 图像哈希 | imagehash | 感知哈希用于相似度检测 |
| 文件哈希 | hashlib (SHA-256) | 完全重复检测 |
| GPX 解析 | gpxpy | GPX 轨迹文件解析 |
| AI/ML | PyTorch + open_clip + CUDA | 本地 GPU 训练与推理，OpenCLIP 特征提取 |
| 文件删除 | send2trash | 移入系统回收站 |
| 异步任务 | asyncio + ThreadPoolExecutor | CPU 密集型任务放线程池，I/O 用 async |
| 实时通信 | WebSocket | 扫描/处理进度推送 |

---

## 2. 项目结构

```
image-pro/
├── backend/                        # Python 后端
│   ├── main.py                     # FastAPI 入口，启动 uvicorn
│   ├── config.py                   # 全局配置（数据库路径、模型路径等）
│   ├── database/
│   │   ├── models.py               # SQLAlchemy ORM 模型
│   │   ├── connection.py           # 数据库连接管理
│   │   └── migrations/             # 数据库迁移脚本
│   ├── api/
│   │   ├── tasks.py                # 任务管理 API
│   │   ├── scan.py                 # 文件扫描 API
│   │   ├── duplicates.py           # 重复/相似检测 API
│   │   ├── exif.py                 # EXIF/时间检查与修改 API
│   │   ├── organize.py             # 按年月整理 API
│   │   ├── gpx.py                  # GPX 匹配与 GPS 写入 API
│   │   ├── ai.py                   # AI 筛图 API
│   │   ├── logs.py                 # 操作日志 API
│   │   └── files.py                # 文件服务（缩略图、原图）
│   ├── services/
│   │   ├── scanner.py              # 文件扫描服务
│   │   ├── hasher.py               # 文件哈希 + 图像哈希服务
│   │   ├── duplicate_detector.py   # 重复/相似分组逻辑
│   │   ├── exif_service.py         # EXIF 读取/写入/异常检测
│   │   ├── time_service.py         # 时间分析与修正
│   │   ├── organizer.py            # 按年月整理/移动/重命名
│   │   ├── gpx_service.py          # GPX 解析与匹配
│   │   ├── ai_service.py           # AI 模型训练/推理/版本管理
│   │   ├── thumbnail.py            # 缩略图生成与缓存
│   │   └── operation_log.py        # 操作日志记录
│   ├── models/                     # AI 模型存储目录
│   │   ├── current/                # 当前使用的模型
│   │   └── history/                # 历史版本备份（最多15个）
│   └── requirements.txt
├── frontend/                       # Vue 3 前端
│   ├── src/
│   │   ├── App.vue
│   │   ├── main.ts
│   │   ├── router/
│   │   │   └── index.ts
│   │   ├── stores/                 # Pinia 状态管理
│   │   │   ├── task.ts             # 当前任务状态
│   │   │   └── app.ts              # 全局应用状态
│   │   ├── api/                    # 后端 API 调用封装
│   │   │   └── index.ts
│   │   ├── views/
│   │   │   ├── HomeView.vue        # 首页/任务列表
│   │   │   ├── ScanView.vue        # 扫描结果
│   │   │   ├── DuplicateView.vue   # 重复/相似检测
│   │   │   ├── ExifView.vue        # EXIF/时间检查
│   │   │   ├── OrganizeView.vue    # 按年月整理
│   │   │   ├── GpxView.vue         # GPX 匹配
│   │   │   ├── AiFilterView.vue    # AI 筛图
│   │   │   └── LogView.vue         # 操作日志
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── AppSidebar.vue  # 左侧导航
│   │   │   │   └── AppHeader.vue   # 顶部栏
│   │   │   ├── common/
│   │   │   │   ├── ImagePreview.vue     # 大图预览组件
│   │   │   │   ├── FileTable.vue        # 通用文件列表组件
│   │   │   │   ├── ProgressBar.vue      # 进度条
│   │   │   │   └── ConfirmDialog.vue    # 确认操作对话框
│   │   │   ├── scan/
│   │   │   ├── duplicate/
│   │   │   ├── exif/
│   │   │   ├── gpx/
│   │   │   └── ai/
│   │   └── utils/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── package.json
└── data/                           # 运行时数据（不入版本控制）
    ├── image_pro.db                # SQLite 数据库
    ├── thumbnails/                 # 缩略图缓存
    └── models/                     # AI 模型文件
```

---

## 3. 整体 UI 布局

```
┌──────────────────────────────────────────────────────────────────┐
│  顶部栏：当前任务名称 / 文件夹路径 / 任务切换                        │
├────────────┬─────────────────────────────────────────────────────┤
│            │                                                     │
│  左侧导航   │              主内容区                                │
│            │                                                     │
│  ┌──────┐  │  根据当前选中模块动态切换：                            │
│  │ 概览  │  │                                                     │
│  ├──────┤  │  - 扫描结果（统计图表）                                │
│  │ 查重  │  │  - 重复/相似分组（卡片/列表）                         │
│  ├──────┤  │  - EXIF/时间检查（表格+警告）                         │
│  │ 时间  │  │  - 年月整理预览（目录树预览）                          │
│  ├──────┤  │  - GPX 匹配结果（地图+列表）                          │
│  │ GPS  │  │  - AI 筛图（左表右图）                                │
│  ├──────┤  │  - 操作日志（时间线/表格）                             │
│  │ AI   │  │                                                     │
│  ├──────┤  │                                                     │
│  │ 日志  │  │                                                     │
│  └──────┘  │                                                     │
│            │                                                     │
├────────────┴─────────────────────────────────────────────────────┤
│  底部状态栏：处理进度 / 文件统计摘要 / GPU 状态                      │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 首页 / 任务管理

- 展示所有已创建的任务列表（卡片形式）
- 每张卡片显示：文件夹路径、文件数量、创建时间、处理状态
- 支持新建任务（选择文件夹）、删除任务
- 点击任务卡片进入该任务的工作区

### 3.2 导航结构

进入某个任务后，左侧导航固定显示该任务的所有功能模块。用户可自由跳转，不强制顺序。

---

## 4. 数据库设计概要

### 4.1 核心表

```sql
-- 任务表
tasks (
    id              INTEGER PRIMARY KEY,
    folder_path     TEXT NOT NULL,          -- 目标文件夹路径
    name            TEXT,                   -- 任务名称（可选，默认用文件夹名）
    status          TEXT DEFAULT 'created', -- created / scanning / ready / completed
    file_count      INTEGER DEFAULT 0,
    image_count     INTEGER DEFAULT 0,
    video_count     INTEGER DEFAULT 0,
    other_count     INTEGER DEFAULT 0,
    created_at      DATETIME,
    updated_at      DATETIME
)

-- 文件表（每次扫描填充）
files (
    id              INTEGER PRIMARY KEY,
    task_id         INTEGER REFERENCES tasks(id),
    file_path       TEXT NOT NULL,           -- 文件完整路径
    relative_path   TEXT NOT NULL,           -- 相对于任务文件夹的路径
    file_name       TEXT NOT NULL,
    extension       TEXT,
    file_size       INTEGER,
    file_type       TEXT,                    -- image / video / other
    mime_type       TEXT,
    sha256          TEXT,                    -- 完整文件 SHA-256 哈希
    xxhash_partial  TEXT,                    -- 快速哈希（前8KB+尾8KB，用于预筛）
    dhash           TEXT,                    -- dHash 感知哈希（仅图片，64bit十六进制）
    hash_version    INTEGER DEFAULT 1,       -- 哈希算法版本号（算法变更时可强制重算）
    clip_feature    BLOB,                    -- OpenCLIP ViT-H/14 特征向量（1024维 float32，仅图片）
    has_exif        BOOLEAN DEFAULT FALSE,
    exif_time       DATETIME,               -- EXIF 拍摄时间
    file_created    DATETIME,               -- 文件创建时间
    file_modified   DATETIME,               -- 文件修改时间
    best_time       DATETIME,               -- 软件推断的最佳时间
    time_source     TEXT,                    -- exif / filename / file_created / file_modified / manual
    time_anomaly    TEXT,                    -- 时间异常类型描述（如有）
    has_gps         BOOLEAN DEFAULT FALSE,
    gps_lat         REAL,
    gps_lng         REAL,
    thumbnail_path  TEXT,                    -- 缩略图缓存路径
    created_at      DATETIME
)

-- 重复/相似分组表
duplicate_groups (
    id              INTEGER PRIMARY KEY,
    task_id         INTEGER REFERENCES tasks(id),
    group_type      TEXT,                    -- exact / similar
    similarity      REAL,                    -- 相似度分值
    file_count      INTEGER,
    recommended_keep_id INTEGER REFERENCES files(id)  -- 推荐保留的文件
)

-- 分组成员关系
duplicate_group_members (
    id              INTEGER PRIMARY KEY,
    group_id        INTEGER REFERENCES duplicate_groups(id),
    file_id         INTEGER REFERENCES files(id),
    is_recommended  BOOLEAN DEFAULT FALSE,   -- 是否为推荐保留项
    user_action     TEXT                     -- keep / delete / null(未决定)
)

-- GPX 匹配记录
gpx_matches (
    id              INTEGER PRIMARY KEY,
    task_id         INTEGER REFERENCES tasks(id),
    file_id         INTEGER REFERENCES files(id),
    gpx_file_path   TEXT,
    matched_lat     REAL,
    matched_lng     REAL,
    time_offset_sec INTEGER,                 -- 照片时间与最近轨迹点的偏差（秒）
    match_quality   TEXT,                    -- good / warning / no_match
    user_confirmed  BOOLEAN DEFAULT FALSE,
    original_has_gps BOOLEAN DEFAULT FALSE   -- 原本是否已有GPS
)

-- AI 标注表
ai_labels (
    id              INTEGER PRIMARY KEY,
    file_id         INTEGER REFERENCES files(id),
    task_id         INTEGER REFERENCES tasks(id),
    user_label      TEXT,                    -- keep / delete / null
    ai_prediction   TEXT,                    -- keep / delete / null
    ai_confidence   REAL,                    -- 0.0 ~ 1.0
    is_training_data BOOLEAN DEFAULT FALSE,  -- 是否为训练样本
    labeled_at      DATETIME
)

-- AI 模型版本表
ai_model_versions (
    id              INTEGER PRIMARY KEY,
    version         INTEGER,
    model_path      TEXT,
    training_samples INTEGER,
    accuracy        REAL,
    created_at      DATETIME
)

-- 操作日志表
operation_logs (
    id              INTEGER PRIMARY KEY,
    task_id         INTEGER,
    operation_type  TEXT,                    -- delete / move / rename / exif_write / gps_write / ai_label
    file_path       TEXT,
    target_path     TEXT,                    -- 目标路径（移动/重命名时）
    detail          TEXT,                    -- JSON 格式的变更详情
    created_at      DATETIME
)
```

---

## 5. 各模块技术方案

---

### 5.1 模块一：任务扫描与文件构成检查

#### 核心流程

```
用户选择文件夹 → 创建任务 → 递归扫描所有文件 → 识别文件类型 → 统计汇总 → 展示结果
```

#### 技术要点

| 环节 | 方案 |
|------|------|
| 递归遍历 | `os.walk()` 或 `pathlib.Path.rglob('*')` 无限递归 |
| 文件类型识别 | 优先按扩展名分类，对未知扩展名用 `python-magic` 读取 magic bytes |
| 异步扫描 | 扫描在 `ThreadPoolExecutor` 中执行，通过 WebSocket 推送进度 |
| 缩略图预生成 | 扫描完成后异步生成缩略图（Pillow `thumbnail()`），缓存到 `data/thumbnails/` |
| 结果存储 | 扫描到的每个文件写入 `files` 表 |

#### 前端展示

- 饼图/柱状图：文件类型分布（图片/视频/其他）
- 表格：按扩展名分类的详细统计
- 警告区：标记非媒体文件（zip、txt、nfo 等），高亮显示
- 进度条：扫描进行中的实时进度

---

### 5.2 模块二：重复与相似检测

#### 设计思路

直接对所有文件计算完整 SHA-256 非常耗时（受限于磁盘 I/O 和文件大小）。核心优化思路是 **逐级淘汰、由粗到精**：每一轮用更低成本的检测手段筛掉大量不可能重复的文件，只对极少数"幸存者"做昂贵的精确计算。

同时，"完全重复"和"相似检测"是两条独立流水线，可并行运行：

- **流水线 A（完全重复）**：面向所有文件（图片 + 视频），依靠文件字节级比较
- **流水线 B（相似检测）**：仅面向图片，依靠感知哈希的视觉比较

#### 流水线 A：完全重复检测（多阶段淘汰）

```
阶段 1: 按文件大小分组          → 淘汰 ~70% 独特大小的文件
    ↓
阶段 2: 快速哈希（首尾各 8KB）   → 淘汰 ~80% 同大小但内容不同的文件
    ↓
阶段 3: 完整哈希（SHA-256）      → 确认最终的完全重复组
```

| 阶段 | 做什么 | 成本 | 淘汰率 |
|------|--------|------|--------|
| **1. 文件大小分组** | 按 `file_size` 分组，大小唯一的文件直接排除 | O(1)，几乎为零 | ~70%（异构数据集），~30%（同相机同分辨率） |
| **2. 快速哈希** | 对同大小文件组，读取 **前 8KB + 末尾 8KB**，用 xxHash 计算摘要 | 每文件仅读 16KB | ~80% 的同大小文件在此被排除 |
| **3. 完整哈希** | 对快速哈希也相同的文件，计算完整 SHA-256 | 需读取整个文件 | 到此阶段通常仅剩原始文件数的 <5% |

**为什么用 xxHash 做快速哈希**：xxHash 比 SHA-256 快 3~5 倍，在非安全场景下足够可靠。快速哈希只用于淘汰，最终确认用 SHA-256。

**为什么读前 8KB + 末尾 8KB**：
- 图片文件头部通常包含不同的 EXIF 数据（即使视觉内容相同）
- 末尾数据因压缩和编码差异也往往不同
- 仅读头部会漏掉"头部相同但中部/尾部不同"的情况
- 16KB 的读取量在 NVMe SSD 上几乎不可感知

**性能估算（10,000 个文件）**：

| 阶段 | 需处理文件数 | I/O 量 | 耗时估算（NVMe SSD） |
|------|-------------|--------|---------------------|
| 文件大小分组 | 10,000 | 0（只读元数据） | < 1 秒 |
| 快速哈希 | ~3,000 | ~48 MB (3000 × 16KB) | < 1 秒 |
| 完整哈希 | ~200 | ~1 GB（假设平均 5MB/文件） | 2~3 秒 |
| **总计** | — | — | **< 5 秒** |

对比：直接对 10,000 个文件全量 SHA-256 → ~50 GB I/O → **30~60 秒**。

#### 流水线 B：相似图片检测（感知哈希）

```
阶段 1: 对所有图片计算 dHash（8×8，64bit）  → 每张 ~5-30ms
    ↓
阶段 2: 汉明距离比较 + Union-Find 聚类     → 分组
    ↓
阶段 3: 去除已在流水线 A 中标记为完全重复的组  → 输出相似组
```

| 环节 | 方案 | 说明 |
|------|------|------|
| 哈希算法 | **dHash（差异哈希）8×8** | 比 pHash 快 3~5 倍，对缩放/压缩变化的鲁棒性足够，是查重场景的最佳平衡点 |
| 哈希大小 | 64 bit | 业界标准，碰撞率极低，存储和比较成本最小 |
| 相似度比较 | **numpy 向量化汉明距离** | 10,000 张图片的 64bit 哈希两两比较，numpy XOR + popcount 仅需毫秒级 |
| 聚类算法 | **Union-Find（并查集）** | 将汉明距离 ≤ 阈值的图片对合并为组，O(n·α(n)) 近乎线性 |
| 相似度挡位 | 宽松: ≤ 4，标准: ≤ 8，严格: ≤ 12 | 汉明距离阈值，用户可切换 |

**为什么选 dHash 而非 pHash**：

| 对比项 | dHash | pHash |
|--------|-------|-------|
| 计算速度 | ~1-5 ms/张 | ~5-30 ms/张 |
| 缩放/压缩鲁棒性 | 好 | 最好 |
| 裁剪鲁棒性 | 一般 | 较好 |
| 实现复杂度 | 低（梯度比较） | 高（需要 DCT 变换） |
| 适合场景 | **查重/去重（推荐）** | 需要抗裁剪/旋转的高级场景 |

对于照片整理查重场景，同一张照片的不同版本通常只有分辨率/压缩率差异，dHash 完全胜任。

**性能估算（10,000 张图片）**：

| 阶段 | 耗时（单线程） | 耗时（12 进程并行） |
|------|---------------|-------------------|
| dHash 计算 | ~50 秒（含图片解码） | ~5 秒 |
| 汉明距离比较 | ~100 ms（numpy 向量化） | — |
| Union-Find 聚类 | < 10 ms | — |
| **总计** | — | **~6 秒** |

#### 多线程/多进程策略

两条流水线可并行启动，内部也分别并行化：

| 任务 | 执行器 | Worker 数 | 原因 |
|------|--------|----------|------|
| 文件大小分组 | 单线程 | 1 | 只读文件元数据，瞬间完成 |
| 快速哈希（xxHash） | `ThreadPoolExecutor` | 16 | hashlib / xxhash 释放 GIL，线程即可 |
| 完整哈希（SHA-256） | `ThreadPoolExecutor` | 16 | 同上，I/O + hashlib 均释放 GIL |
| dHash 计算 | `ProcessPoolExecutor` | 8~12 | Pillow 图像解码**不释放 GIL**，需多进程绕过 |
| 汉明距离 + Union-Find | 单线程 | 1 | numpy 向量化已足够快 |

> i7-13700K 有 8 个 P 核 + 8 个 E 核（24 线程）。I/O 密集型任务用 16 线程，CPU 密集型用 8~12 进程（P 核数量附近最优）。

#### 哈希缓存策略

参考 czkawka 的做法，计算过的哈希值持久化到数据库：

```
files 表新增字段:
    xxhash_partial  TEXT    -- 快速哈希（前8KB+尾8KB）
    sha256          TEXT    -- 完整 SHA-256
    dhash           TEXT    -- dHash 感知哈希
    hash_version    INTEGER -- 哈希版本号（算法变更时可强制重算）
```

- 每次扫描文件时，检查 `(file_path, file_size, file_modified)` 是否与缓存一致
- 如果一致，跳过哈希计算，直接复用缓存值
- 如果文件变更，清除旧缓存重新计算
- **二次扫描同一文件夹**时几乎零耗时

#### 完整检测流程图

```
                            所有文件（图片 + 视频）
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            流水线 A: 完全重复                  流水线 B: 相似检测
            （所有文件类型）                    （仅图片）
                    │                               │
        ┌───────────┤                     ┌─────────┤
        ▼           │                     ▼         │
   1.按文件大小分组  │               1.计算 dHash     │
   淘汰唯一大小     │               (ProcessPool     │
        │           │                8~12 workers)   │
        ▼           │                     │         │
   2.快速哈希       │                     ▼         │
   (首尾8KB+xxHash) │               2.numpy 向量化   │
   (ThreadPool 16)  │                汉明距离比较    │
        │           │                     │         │
        ▼           │                     ▼         │
   3.完整 SHA-256   │               3.Union-Find    │
   (ThreadPool 16)  │                聚类分组        │
        │           │                     │         │
        ▼           ▼                     ▼         ▼
   完全重复分组                       相似图片分组
        │                               │
        └───────────┬───────────────────┘
                    ▼
            合并结果，去重
            （相似组中排除已在完全重复组中的文件）
                    │
                    ▼
            为每组计算推荐保留项
            （分辨率 → 大小 → EXIF → 文件名 → 路径）
                    │
                    ▼
              展示给用户审查
```

#### 前端展示

- **概览面板**：检测进度（两条流水线各自的进度条）、统计数字（重复组数、相似组数、可释放空间）
- **分组卡片视图**：每组显示缩略图网格，推荐保留项带绿色标记，待删除项带红色淡化
- **对比视图**：选中某组后，左右/多列对比详细信息（分辨率、大小、路径、EXIF 时间、哈希值）
- **操作**：勾选保留/删除，支持批量操作（全部接受推荐 / 全部保留最大 / 手动逐组选）
- **筛选**：按组类型（完全重复/相似）、组内文件数量、可释放空间排序
- **相似度挡位切换**：顶部提供宽松/标准/严格切换，切换后重新计算分组（仅需重跑 Union-Find，不需重算哈希）

---

### 5.3 模块三：时间、EXIF 与按年月整理

#### 核心流程

```
读取每个文件的所有时间源 → 检测异常 → 推断最佳时间 → 展示异常列表
→ 用户确认 → 生成年月整理预览 → 用户确认 → 执行移动
```

#### 技术要点

| 环节 | 方案 |
|------|------|
| EXIF 读取 | `exifread` 读取，支持 JPG/TIFF/HEIC |
| EXIF 写入 | `piexif` 写入（JPG），其他格式通过 `exiftool` 命令行 |
| 时间来源 | EXIF DateTimeOriginal > EXIF DateTime > 文件名解析 > 文件修改时间 > 文件创建时间 |
| 异常检测规则 | 1. 无 EXIF → 标记<br>2. EXIF 时间与文件时间偏差 > 24h → 标记<br>3. 时间早于 2000 年或晚于当前 → 标记<br>4. 同批次内时间分布明显离群 → 标记 |
| 时区处理 | 统一 UTC+8，无时区信息时默认 +8 |
| 批量偏移 | 用户指定小时/分钟偏移量，批量修改选中文件的 EXIF 时间 |
| 年月整理 | 根据 best_time 生成目标路径 `YYYY/MM/filename`，预览后执行 `shutil.move()` |
| 文件冲突 | 目标路径已存在同名文件时，提示用户或自动添加 `-1` 后缀 |
| 重命名 | 可选按 `YYYYMMDD_HHMMSS.ext` 格式重命名 |

#### 前端展示

- 异常列表：Table 展示所有时间异常的文件，标记异常类型（无EXIF、时间冲突、离谱等）
- 时间轴预览：横向时间轴展示这批文件的时间分布，离群点高亮
- 整理预览：树状展示整理后的目录结构（`2024/03/` 下有哪些文件）
- 手动修改：选中文件后可手动输入时间
- 批量偏移：输入偏移小时数，预览修改结果
- 确认执行：所有操作先预览，确认后才执行

---

### 5.4 模块四：GPX 匹配与 GPS 补写

#### 核心流程

```
选择照片文件夹 + 选择 GPX 文件 → 解析 GPX 轨迹点 → 按时间匹配照片
→ 展示匹配结果 → 用户确认 → 写入 GPS EXIF
```

#### 技术要点

| 环节 | 方案 |
|------|------|
| GPX 解析 | `gpxpy` 解析 GPX/GPX XML，提取所有轨迹点 (time, lat, lng) |
| 时间对齐 | GPX 时间通常为 UTC，照片时间按 UTC+8，统一转换后匹配 |
| 匹配算法 | 对每张照片的拍摄时间，在 GPX 轨迹点中做二分查找找到最近点；如果两侧都有点，做线性插值 |
| 匹配质量 | 偏差 ≤ 5min → good（绿色）；> 5min → warning（黄色）；无匹配 → no_match（红色） |
| 多 GPX 文件 | 合并所有轨迹点，按时间排序；时间重叠段按用户指定的优先级决定使用哪个文件的点 |
| 已有 GPS | 检查文件是否已有 GPS EXIF，如有则单独标记提示用户 |
| GPS 写入 | 通过 `piexif` 写入 GPSInfo 字段（GPSLatitude, GPSLongitude, GPSLatitudeRef, GPSLongitudeRef） |

#### 前端展示

- 匹配概览：统计成功/警告/失败的数量和占比
- 匹配列表：Table 展示每张照片的匹配结果，颜色标记质量
- 地图预览（可选，后期）：在地图上展示轨迹线 + 照片标记点
- GPX 文件管理：支持添加多个 GPX 文件，拖拽排序优先级
- 已有 GPS 标记：单独列出已有 GPS 的照片，让用户选择跳过或覆盖
- 确认执行：预览所有将写入的 GPS 信息，确认后批量写入

---

### 5.5 模块五：AI 保留/删除建议

#### 设计思路

本模块的目标是学习用户的个人审美偏好，对未标注的图片给出"建议保留"或"建议删除"的二元判断。

核心架构为 **OpenCLIP 特征提取（冻结） + 轻量 MLP 二分类器（可训练）**：

- **OpenCLIP** 负责将每张图片编码为一个高维特征向量，该向量天然包含构图、光线、色调、风格、内容等审美相关信息
- **MLP 分类器** 负责在 OpenCLIP 特征空间中学习用户的个人审美偏好边界
- 两者解耦：特征提取一次计算并缓存，分类器可反复快速重训

输出始终为二元结果：**保留 / 删除**，附带置信度分数。

#### 为什么选 OpenCLIP

**OpenCLIP vs 原版 CLIP（OpenAI）**：

| 对比项 | OpenAI CLIP | OpenCLIP |
|--------|------------|---------|
| 训练数据 | 4 亿图文对（未公开） | LAION-2B（20 亿图文对，公开） |
| 开源程度 | 权重开源，训练代码未开源 | 完全开源（代码 + 权重 + 数据） |
| 可商用 | 限制较多 | 完全可商用 |
| 模型选择 | ViT-B/32, ViT-L/14 | ViT-B/32, ViT-L/14, ViT-H/14, ViT-bigG/14 |
| 性能 | 优秀 | 同等架构下性能相当或更优 |
| 社区支持 | 一般 | Hugging Face 完整集成，社区活跃 |

**OpenCLIP vs DINOv2（Meta）**：

| 对比项 | OpenCLIP | DINOv2 |
|--------|---------|--------|
| 训练方式 | 图文对比学习（理解语义概念） | 纯视觉自监督（不理解语义） |
| 理解"构图好坏" | ✅ 见过大量"good composition"等描述 | ❌ 只知道画面结构，不知好坏 |
| 理解"光线美感" | ✅ 见过"dramatic lighting"等描述 | ❌ 只知道亮度分布 |
| 理解"风格偏好" | ✅ 见过"cinematic"、"vintage"等描述 | ❌ 只知道视觉相似性 |
| 适合任务 | **审美判断、个人偏好学习** | 医学影像、精细视觉分类 |

**结论**：OpenCLIP 因为在海量图文对上训练，其特征空间天然编码了审美维度（构图、光线、风格、色调等）。用户只需要在这个空间中标注少量数据，MLP 就能学到个人偏好边界。DINOv2 虽然视觉细节捕捉能力强，但不具备审美理解能力，不适合本任务。

#### 模型选型

推荐模型：**OpenCLIP ViT-H/14**（`laion2b_s32b_b82k` 预训练权重）

| 模型 | 特征维度 | VRAM 占用 | 推理速度（4070 Ti Super） | 审美任务表现 |
|------|---------|----------|-------------------------|------------|
| ViT-B/32 | 512 维 | ~1 GB | ~200 img/s | 好（可用于 MVP） |
| ViT-L/14 | 768 维 | ~2 GB | ~80-120 img/s | 很好 |
| **ViT-H/14** | **1024 维** | **~4 GB** | **~50 img/s** | **最好（推荐）** |

推荐 ViT-H/14 的理由：
- 1024 维特征比 768 维准确率高 2-3%，在小数据量（200-500 张标注）时差距更明显
- VRAM 仅需 4 GB，4070 Ti Super（16GB）完全无压力
- 推理速度 ~50 img/s，10,000 张图约 3.5 分钟完成特征提取（一次性，结果缓存）
- 4TB 硬盘无需担心缓存空间

#### 核心流程

```
阶段 1: 特征提取（一次性，结果持久化缓存）
    │
    │  新图片进入任务 → OpenCLIP ViT-H/14 提取 1024 维特征向量 → 存入数据库
    │  已有缓存的图片直接跳过
    │  速度：~50 img/s（4070 Ti Super）
    │  VRAM：~4 GB
    │
阶段 2: 冷启动标注
    │
    │  首次使用：用户标注 200+ 张图片（保留/删除）
    │  界面提供高效的批量标注交互
    │  标注数据存入 ai_labels 表
    │
阶段 3: 训练 MLP 分类器
    │
    │  输入：用户已标注图片的特征向量 + 标签（保留/删除）
    │  模型：2 层 MLP (1024 → 256 → 1)，Sigmoid 输出
    │  损失函数：Focal Loss (γ=2)，自动适应类别不均衡
    │  训练数据：均衡采样（保留和删除各取等量样本）
    │  训练耗时：200 张 ~10 秒，2000 张 ~30 秒
    │  训练前自动备份当前模型
    │
阶段 4: 推理
    │
    │  对未标注图片：缓存的特征向量 → MLP → 保留概率 (0.0~1.0)
    │  概率 > 0.5 → 建议保留     概率 < 0.5 → 建议删除
    │  置信度 = |概率 - 0.5| × 2（归一化到 0~1）
    │  推理速度：特征已缓存时 > 10,000 img/s（纯 MLP 计算）
    │
阶段 5: 用户修正与反馈
    │
    │  用户审查 AI 建议 → 修正错误判断 → 修正数据入库
    │  用户可随时触发重新训练 → 模型更新
    │
    ↓
  持续循环：标注越多 → 模型越准 → 需要修正越少
```

#### MLP 分类器架构

```python
import torch.nn as nn

class AestheticClassifier(nn.Module):
    """基于 OpenCLIP 特征的二分类器"""
    def __init__(self, input_dim=1024):  # ViT-H/14 输出 1024 维
        super().__init__()
        self.classifier = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.ReLU(),
            nn.Dropout(0.3),        # 防止过拟合（小数据量时重要）
            nn.Linear(256, 1),
            nn.Sigmoid()             # 输出 0~1 的保留概率
        )

    def forward(self, features):
        return self.classifier(features)  # → 保留概率
```

#### Focal Loss

标准交叉熵在类别不均衡时会偏向多数类。Focal Loss 通过降低"容易分类的样本"的权重，让模型更关注"难分的边界样本"：

```python
class FocalLoss(nn.Module):
    def __init__(self, gamma=2.0):
        super().__init__()
        self.gamma = gamma

    def forward(self, pred, target):
        bce = nn.functional.binary_cross_entropy(pred, target, reduction='none')
        pt = torch.where(target == 1, pred, 1 - pred)  # 预测正确的概率
        focal_weight = (1 - pt) ** self.gamma           # 难分样本权重更高
        return (focal_weight * bce).mean()
```

无论训练数据中保留:删除的比例是 1:9 还是 8:2，Focal Loss + 均衡采样都能训出稳定的分类器。

#### 特征提取与缓存

```python
import open_clip
import torch

# 加载模型（一次性）
model, _, preprocess = open_clip.create_model_and_transforms(
    'ViT-H-14', pretrained='laion2b_s32b_b82k'
)
model = model.to('cuda').eval()

# 提取特征（批量）
@torch.no_grad()
def extract_features(image_paths: list[str], batch_size=32) -> dict[str, np.ndarray]:
    """批量提取 OpenCLIP 特征，返回 {path: feature_vector}"""
    results = {}
    for batch in chunked(image_paths, batch_size):
        images = torch.stack([preprocess(load_image(p)) for p in batch]).to('cuda')
        features = model.encode_image(images)         # → (batch, 1024)
        features = features / features.norm(dim=-1, keepdim=True)  # L2 归一化
        for path, feat in zip(batch, features.cpu().numpy()):
            results[path] = feat
    return results
```

特征提取后存入数据库 `files` 表的 `clip_feature` 字段（1024 维 float32 → 4096 字节/张图），后续所有训练和推理直接读缓存，不再调用 OpenCLIP 模型。

#### 不同类型内容的处理策略

所有训练数据统一训练一个全局模型。理由：

1. **用户的审美标准是一致的** — 无论图片来源如何，"喜欢/不喜欢"的判断标准来自同一个人
2. **CLIP 特征已包含内容信息** — 模型可以自动学到"我喜欢构图好的人像 + 色彩鲜艳的风景"这类复合偏好
3. **数据量最大化** — 所有标注汇聚在一起训练，模型更稳定
4. **简单可靠** — 不需要额外的分类步骤，没有"分类错误导致审美模型选错"的级联风险

#### 不同批次比例差异的处理

模型输出的是连续概率分数，不是硬编码的比例预设：

```
高质量写真集：大部分图片得分 > 0.5 → 自然保留多
低质量图片包：大部分图片得分 < 0.5 → 自然删除多
```

模型只回答"这张图是否匹配你的口味"，不关心当前批次的整体比例。比例是结果，不是输入。

#### 模型版本管理

```
data/models/
├── current/
│   └── classifier_v12.pt          # 当前使用的模型
├── history/
│   ├── classifier_v01.pt          # 历史版本（最多 15 个）
│   ├── classifier_v02.pt
│   ├── ...
│   └── classifier_v11.pt
└── metadata.json                   # 版本信息（训练样本数、准确率、时间）
```

- 每次训练前，自动将当前模型复制到 `history/`
- 最多保留 15 个版本，超过后循环覆盖最早的
- `metadata.json` 记录每个版本的训练样本数、验证准确率、训练时间
- 用户可在界面中查看版本列表、对比准确率、回滚到任意历史版本

#### 精度预期

| 标注量 | 预期准确率 | 用户体感 |
|--------|----------|---------|
| 200 张 | 75-85% | 大方向正确，约 1/5 需要修正 |
| 500 张 | 82-88% | 明显省力，多数判断正确 |
| 1000 张 | 85-92% | 只需关注少量边界案例 |
| 2000+ 张 | 88-95% | 接近自动化，偶尔微调 |

#### 资源占用

| 操作 | VRAM | 耗时（4070 Ti Super） |
|------|------|----------------------|
| OpenCLIP 模型加载 | ~2 GB | 3-5 秒（一次性） |
| 特征提取 10,000 张 | ~2.5 GB（含批量数据） | 1.5-2 分钟 |
| MLP 训练 2000 样本 | < 500 MB | 10-30 秒 |
| MLP 推理 10,000 张 | < 100 MB（特征已缓存） | < 1 秒 |

#### 前端展示

- **左右分栏布局**：
  - 左侧：Table 列表（缩略图、文件名、AI 建议、置信度、用户标记）
  - 右侧：选中图片的大图预览
- 操作逻辑参考 Windows 文件管理器：
  - 单击选中、Ctrl+单击多选、Shift+单击范围选
  - 右键菜单（标记保留/删除）
  - 键盘快捷键（方向键切换、K=保留、D=删除）
- 筛选栏：按 AI 建议、置信度区间、用户标记状态筛选
- 排序：按置信度排序（优先审查不确定的）
- 批量操作：全部接受 AI 建议 / 全部标记为保留 / 全部标记为删除
- 训练控制：
  - 标注进度显示（已标注 N 张 / 最低要求 200 张）
  - 训练按钮（标注达标后可用）
  - 训练进度和验证准确率实时展示
  - 模型版本列表与回滚操作

---

### 5.6 模块六：操作日志

#### 技术要点

| 环节 | 方案 |
|------|------|
| 记录方式 | 每次文件操作时，service 层统一调用 `operation_log.record()` 写入日志 |
| 存储 | `operation_logs` 表 |
| 详情字段 | JSON 格式存储变更前后的值（如 EXIF 修改前后的时间） |
| 查询 | 支持按任务、操作类型、时间范围筛选 |

#### 前端展示

- 时间线形式展示操作历史
- 支持按操作类型和任务筛选
- 展开查看每条日志的详细变更内容

---

## 6. 缩略图策略

缩略图是前端展示性能的关键。

| 项目 | 方案 |
|------|------|
| 生成时机 | 扫描完成后异步批量生成 |
| 尺寸 | 统一生成 300x300 像素（保持比例，填充） |
| 格式 | 统一转为 JPEG，质量 85 |
| 存储 | `data/thumbnails/{task_id}/{file_sha256_prefix}.jpg` |
| HEIC/WebP/AVIF | 通过 Pillow + pillow-heif 插件读取后转 JPEG 缩略图 |
| 视频缩略图 | 使用 OpenCV `VideoCapture` 提取第一帧 |
| 并发 | 多线程并行生成，通过 WebSocket 推送生成进度 |
| 前端加载 | 后端提供 `/api/files/thumbnail/{file_id}` 接口，前端懒加载 |

---

## 7. API 设计概要

### 7.1 任务管理

```
POST   /api/tasks                    创建任务（传入文件夹路径）
GET    /api/tasks                    获取所有任务列表
GET    /api/tasks/{id}               获取单个任务详情
DELETE /api/tasks/{id}               删除任务
```

### 7.2 文件扫描

```
POST   /api/tasks/{id}/scan          启动扫描（异步，通过 WebSocket 推送进度）
GET    /api/tasks/{id}/scan/status   获取扫描状态
GET    /api/tasks/{id}/files         获取文件列表（支持分页、筛选、排序）
GET    /api/tasks/{id}/scan/summary  获取文件类型统计
```

### 7.3 重复/相似检测

```
POST   /api/tasks/{id}/duplicates/detect     启动检测（异步）
GET    /api/tasks/{id}/duplicates/groups      获取分组列表
PUT    /api/tasks/{id}/duplicates/groups/{gid}/members/{mid}  标记保留/删除
POST   /api/tasks/{id}/duplicates/execute     确认后执行删除
```

### 7.4 EXIF/时间

```
GET    /api/tasks/{id}/exif/anomalies         获取时间异常列表
PUT    /api/files/{id}/exif/time              手动修改单个文件时间
POST   /api/tasks/{id}/exif/batch-offset      批量时间偏移
```

### 7.5 年月整理

```
POST   /api/tasks/{id}/organize/preview       生成整理预览
POST   /api/tasks/{id}/organize/execute        确认后执行整理
```

### 7.6 GPX

```
POST   /api/tasks/{id}/gpx/match              上传 GPX 并匹配
GET    /api/tasks/{id}/gpx/results             获取匹配结果
PUT    /api/tasks/{id}/gpx/results/{id}/action 设置跳过/覆盖
POST   /api/tasks/{id}/gpx/execute             确认后写入 GPS
```

### 7.7 AI 筛图

```
GET    /api/tasks/{id}/ai/status               获取 AI 模块状态（模型是否就绪、标注数量等）
GET    /api/tasks/{id}/ai/predictions          获取 AI 建议列表
PUT    /api/files/{id}/ai/label                用户标记 保留/删除
POST   /api/ai/train                           触发模型训练
GET    /api/ai/models                          获取模型版本列表
POST   /api/ai/models/{id}/rollback            回滚到指定版本
POST   /api/tasks/{id}/ai/execute              确认后执行删除
```

### 7.8 操作日志

```
GET    /api/logs                               获取操作日志（支持按任务、类型、时间筛选）
```

### 7.9 文件服务

```
GET    /api/files/{id}/thumbnail               获取缩略图
GET    /api/files/{id}/original                获取原图
```

### 7.10 WebSocket

```
WS     /ws/tasks/{id}/progress                 接收实时进度（扫描、检测、训练等）
```

---

## 8. 关键流程示意

### 8.1 用户典型工作流

```
1. 打开软件（浏览器访问 http://localhost:8000）
2. 点击"新建任务" → 选择文件夹 → 开始扫描
3. 扫描完成后查看文件构成，确认目录正确
4. 进入"查重"模块 → 等待检测完成 → 审查分组 → 确认删除冗余
5. 进入"时间"模块 → 查看异常 → 必要时手动修正/批量偏移
6. 进入"整理"模块 → 预览年月目录结构 → 确认执行移动
7. （如有GPX）进入"GPS"模块 → 选择 GPX 文件 → 审查匹配 → 确认写入
8. （如为下载图片）进入"AI"模块 → 标注冷启动数据 → 训练 → 审查建议 → 修正 → 确认删除
9. 任务完成，用户自行将整理好的文件备份到 NAS/网盘
```

### 8.2 确认执行机制

所有文件修改操作都遵循同一模式：

```
分析/检测 → 生成预览结果 → 用户审查 → 用户确认 → 后端执行 → 记录日志
                                ↑
                          用户可修改预览中的任何条目
```

---

## 9. 启动方式

开发阶段：

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev    # Vite dev server，代理 API 到 8000 端口
```

生产/日常使用阶段：

```bash
# 前端构建为静态文件
cd frontend && npm run build

# 后端直接 serve 静态文件 + API
cd backend
python main.py
# 自动打开浏览器访问 http://localhost:8000
```

后续可考虑用 PyInstaller 打包为单个 exe，一键启动。

---

## 10. 待实现时确认的细节

以下问题不影响整体架构，可在开发到对应模块时再决定：

1. EXIF 写入前是否自动备份原文件（还是只依赖操作日志记录变更前的值）
2. 相似度挡位的具体汉明距离阈值需实测调优
3. AI 冷启动最小样本量需根据实际训练效果确定（初步设 200）
4. 缩略图尺寸是否需要提供多规格（列表用小图、预览用中图）
5. 视频缩略图提取帧的具体策略（第一帧 vs 中间帧 vs 多帧）
6. LivePhoto（HEIC + MOV 配对文件）是否需要关联处理
7. 文件名时间戳解析的正则规则集（如 IMG_20240301_143022.jpg、Screenshot_2024-03-01 等）
