# 数据库协议（Database Protocol）

> 本页的中文版。英文版见 [`database-protocol.md`](database-protocol.md),两版内容保持一致。

本页说明我们的萜类酶数据库**怎么建的、里面有什么、怎么跑起来**,以及界面上那个溶解度分数
**到底是什么意思**。写这么细,是为了让第三方——评委,或者后来的队伍——能自己判断我们的数据
是否可信、整条建库流程能否复现。

两条贯穿全文的约定:

- **文中路径都相对仓库根目录**。§9 的命令除非特别说明,一律在仓库根目录执行。
- **尖括号里的都是占位符**。`<数据盘>` 的意思是「你自己选一块盘」。我们不对目录位置做任何约定,
  只约定它**不能落在哪里**(见 §3.2)。

> 文中的规模与行数都是**实测快照**,会随 UniProt 更新而变(最近一次实测是 2026-09-20)。
> 稳定的部分是结构性的那些:表结构、流程、依赖。

---

## 1. 系统总览

本数据库不是单个 Web 应用,而是**四段式流水线 + 一个只读 Web 应用**。各段之间不通过代码耦合,
只通过磁盘上的 TSV 文件交接。

```
        UniProt / Rhea / ChEBI / DDBJ          （外部数据源,见 §4）
                    │
                    ▼
    ① update_tool/   采集 + 加工
                    │  产出:for_*/ 下按来源分段的 TSV
                    ▼
    ② etl/           灌库(6 步,约 41 分钟)
                    │  产出:MySQL 15 张表
                    ▼
    ③ backend/       只读 FastAPI  ──►  ④ frontend/  React 单页应用
```

| 段 | 目录 | 职责 | 可否重跑 |
|---|---|---|---|
| ① 采集加工 | `update_tool/` | 调外部 API,产出 TSV | 可重跑;联网步骤约 3 小时 |
| ② 灌库 | `etl/` | TSV → MySQL | 可重跑,幂等 |
| ③ 后端 | `backend/` | 只读查询 + BLAST | 无状态 |
| ④ 前端 | `frontend/` | 图谱与检索界面 | 无状态 |

**设计约束。** ①→② 之间的唯一契约是 `for_*/` 下那批分段 TSV。ETL 只从 `etl/sources.py` 这一个
入口读它们,文件不齐时**直接报错退出**——绝不静默跳过。原因是风险不对称:多读一个来源只是白费
时间,少读一个来源是**静默丢数据**,而这种缺陷的表征恰恰是「一切看起来都正常」。

---

## 2. 仓库布局

整个目录树分三类:**流水线与应用**(跑数据库需要的)、**交接数据**、**开发期产物**(我们自己建库
时用的,跑任何东西都不需要)。

### 2.1 流水线与应用

| 路径 | 内容 |
|---|---|
| `update_tool/` | 第①段——采集脚本(`download_*`、`fetch_*`)、加工脚本(`build_*`),以及 `run_all.py`、`update_database.py`、`source_registry.py`。说明见 `update_tool/WORKFLOW.md`。 |
| `for_*/` | 第①、②段之间的交接 TSV——见 §2.2 |
| `etl/` | 第②段——`etl_run.py` 与六个阶段模块 |
| `sql/schema.sql` | 建表语句的唯一真相源 |
| `backend/` | 第③段——FastAPI 服务;BLAST+ 在 `blast_bin/`(**不在本仓库**,见 §3.4),BLAST 工作目录在 `blast_work/`,生成的导出文件在 `app/downloads/` |
| `frontend/` | 第④段——React + Vite 单页应用 |
| `tools/` | `fix_mysql_timestamp_defaults.sql`——一次性的表结构修补 |
| `docs/` | 本协议 |
| `README.md` | 运维手册:环境要求、部署顺序、起服务命令,以及 MySQL / uvicorn 的坑 |
| `LICENSE`、`LICENSE-DATA`、`NOTICE` | 两个许可的全文,以及第三方署名声明——见 §12 |

### 2.2 交接数据(`for_*/`)

这四个目录是第①段与第②段之间**唯一的契约**,也是 ETL 唯一的输入。每个目录里,带 `.<来源>.tsv`
后缀的是按来源分段的文件,不带后缀的 `.tsv` 是两段的合并表。

| 目录 | 内容 |
|---|---|
| `for_enzyme_detail/` | `uniprotkb_master.{swiss_prot,trembl,}.tsv`,以及 `child_tables/`——七张子表(名称、Rhea 链接、参考文献、序列链接、GO、异构体、溶解度分数) |
| `for_enzyme_reation_card/` | `uniprotkb_enzyme_merged.*`、`uniprotkb_rhea_summary.*` |
| `for_compound_card/` | `uniprotkb_terpene_compounds.tsv` |
| `for_graph/` | `all_nodes.tsv`、`uniprotkb_terpene_only.*`、`uniprotkb_terpene_pairs.tsv` |

> ⚠️ 目录名 `for_enzyme_reation_card` **上游就拼错了**("reation" 应为 "reaction"),而
> `etl_edges.py` 与 `etl_enzymes.py` 就是按这个拼法去读的。**不要**只改目录名而不改这两处。

### 2.3 开发期产物

下面这些是我们**建库和验证**时用的。**跑流水线或 Web 应用都不需要**,也不计入 §3.1 的磁盘数字。

**它们也都不在本仓库里。** 这一节记的是我们工作区里有什么,不是仓库跟踪了哪些文件——下面每一组
都被 `.gitignore` 排除。之所以还留着这一节,是因为本页引用的那些测量数字就是这些脚本跑出来的;
哪怕不随仓库分发,读者也该知道它们是什么。

| 组 | 数量 | 是什么 |
|---|---|---|
| 根目录 `_*.py` | 24 | 调试期间随手写的探针与测量脚本——A/B 抓取、索引与前缀检查、ETL 接缝探针、图谱与检索集探针、性能跑分。没有任何代码 import 它们。 |
| 根目录 `_*.json` | 9 | 上述探针写出的测量快照(前后对照、缓冲池对比)。 |
| 根目录 `_*.ps1` | 4 | **MySQL 配置脚本**——`_move_mysql_datadir.ps1`、`_mysql_tmpdir.ps1`、`_mysql_buffer_pool.ps1`、`_drop_old_datadir.ps1`。唯一一组**确实有运维用途**、而非随手丢掉的:它们在本机就是 §9 的第 0 步。但仍不在仓库里——它们写死了那台机器的盘符、MySQL 安装路径和服务名,而 `_drop_old_datadir.ps1` 会不可逆地删掉一个数据目录。§9 已把这三件事完整写成步骤,不依赖这一组里的任何东西。 |
| `_db_backup/`、`_dbbackup/`、`_pre_merge_backup_<时间戳>/` | — | 数据库转储,**合计约 1.2 GB** |
| `_mysql_move.log`、`mysqldata_copy.log` | — | MySQL 目录搬移的日志 |
| `ge60.json`、`graph_full.json`、`group_edges.json`、`st_600.json`、`st_2000.json` | 5 | 更多测量输出(这几个只是碰巧没有下划线前缀) |
| `uniprotkb_terpene_parsed.{swiss_prot,trembl}.tsv` | 2 | **UniProt 原始下载文件**。ETL **不读**它们——ETL 只读 `for_*/`。 |
| `icon.png` | 1 | 站点图标 |

`update_tool/` 下还有自己的几个工作目录——`_src/`(暂存)、`_merged/`(合并暂存)、`_sandbox/`
(`IGEM_DATA_DIR` 指向的沙箱树,§3.5)、`_t/`、`_deploy_backup/`——以及 `chebi_data/`
(含 `curation_overrides.tsv`)和 `child_tables/`。

这些在本机上我们特意没有清理掉:探针和它们抓下来的输出,正是我们验证流水线的方式。
它们不属于我们对外发布的内容。

---

## 3. 环境

### 3.1 运行时与硬件

| 项 | 要求 | 说明 |
|---|---|---|
| Python | **3.10+** | 我们的构建环境实测为 3.11 |
| MySQL | **8.0+** | InnoDB,字符集统一 utf8mb4 |
| Node.js | **≥ 20** | 仅前端需要 |
| NCBI BLAST+ | `blastp` / `makeblastdb` 可执行文件 | 见 §3.4 |
| 磁盘 | 运行 **≥ 6 GB**;全量重建建议预留 **~25 GB** | 见下表 |

**磁盘占用实测。** 稳态运行与全量重建是两个数量级,规划容量时不要混用:

| 场景 | 占用 | 构成 |
|---|---|---|
| **稳态运行**(库建好、不再重建) | **约 5 GB** | MySQL 数据文件 2.7 GB + undo/系统表空间约 1.6 GB + `for_*` 产出 0.4 GB + BLAST 二进制与索引 0.6 GB + 前端 `dist` 0.1 GB |
| **全量重建峰值** | **约 10–12 GB** | 上述稳态 + 中间产物 `_src/` 0.6 GB + MySQL 临时文件数 GB + 每轮 binlog 约 1.3 GB |

两个容易被高估或低估的点:

- **binlog 是累积项,不是稳态需求。** 我们开发机的 MySQL 数据目录当前占 **19 GB**,其中
  **12 GB 是 binlog**——那是几十轮 ETL 攒下来的。全新安装没有这部分,`PURGE BINARY LOGS`
  可以回收。只按「目录有多大」估容量会严重高估。
- **重建期间必须留出临时文件空间。** 全量 ETL 的临时文件落在 `tmpdir`(见下),峰值可达数 GB;
  空间不足时 ETL 不会优雅退出,而是跑到一半崩溃。

库内部占用高度集中:`search_index` 一张表就占 2.0 GB(约占库的 75%),其次是
`gene_sequence_link` 0.32 GB、`evidence` 与 `enzyme` 各 0.12 GB;其余十一张表合计不足 0.2 GB。

### 3.2 MySQL 配置

有两项**必须显式设置**,不能依赖默认值:

```ini
datadir=<数据盘>/mysql-data       # 例:Windows 为 D:/mysql-data,Linux 为 /data/mysql-data
tmpdir=<数据盘>/mysql-data/tmp    # 必须显式指定,见下
innodb_buffer_pool_size=2G
innodb_buffer_pool_instances=1
```

**唯一的硬性要求是「两者都不落在系统盘」**,而不是落在某个具体盘。原因有两条:

- `tmpdir` 不显式配置时,MySQL 会把临时文件放进系统盘的用户临时目录。全量 ETL 会产生数 GB
  临时文件,系统盘写满后 ETL 会跑到一半以 `OS errno 28 - No space left on device` 崩溃。
- 全量 ETL 每轮还会产生约 4 GB binlog。binlog 的路径跟 `datadir` 走(`log-bin` 配的是相对路径),
  所以 `datadir` 换到数据盘后 binlog 增长也落在数据盘——这正是要的效果。

> 在 Windows 上如果 `datadir` 原本在系统盘,搬移需要管理员权限,且要同时改 `my.ini` 与目录 ACL。
> 建议在**装完 MySQL 后立刻设置**,比事后搬移省事得多。

### 3.3 Python 依赖

采集段与查询段**刻意使用两套不同的数据库驱动链**(同步 / 异步):

| 位置 | 依赖 |
|---|---|
| `backend/requirements.txt` | `fastapi`、`uvicorn[standard]`、`sqlalchemy[asyncio]`、**`aiomysql`**、`pydantic` v2、`pydantic-settings`、`python-dotenv`、`httpx`、`openpyxl` |
| `etl/requirements.txt` | `pandas`、`sqlalchemy`、**`pymysql`** |
| `update_tool/` | 使用 `requests` 等库,但**仓库内未提供 requirements.txt** |

> **复现已知缺口。** `update_tool/` 没有声明依赖文件,而 `fetch_rhea.py` 等脚本直接 `import requests`。
> 第三方从零复现时需自行 `pip install requests`,否则 §9 的第 4 步会中断。

### 3.4 外部程序:NCBI BLAST+

序列同源检索不是调用远程服务,而是**调用本地 NCBI BLAST+ 子进程**。需要从 NCBI 下载 BLAST+、
解压,再把可执行文件所在目录告诉后端。**这个目录因机器而异,必须显式指定:**

- 默认值是相对后端启动目录的 `blast_bin/`(我们的启动方式是从 `backend/` 目录启动,所以默认落在
  `backend/blast_bin/`)。
- 换成任意位置都行,用 `IGEM_BLAST_BIN_DIR` 指向它即可;文件缺失时后端会明确报错,不会静默失败。
- 可执行文件**不在本仓库里**。一份 BLAST+ 构建约 375 MB,且绑死在一个平台上——所以该带走的是
  下载地址,不是二进制本身,请下载对应自己系统的版本。两种布局都支持:解压后的 NCBI 归档
  (可执行文件在嵌套的 `bin/` 里),以及扁平的目录。

工作目录(FASTA 与 `makeblastdb` 产物)默认是相对启动目录的 `blast_work/`,可用
`IGEM_BLAST_WORK_DIR` 覆盖。

- subject 库 = 所有有序列的酶 + 序列与其 canonical 序列不同的异构体。
- `makeblastdb` 只格式化一次,之后按 subject 集合的签名(范围 + ID + 长度)缓存复用。

> **路径含非 ASCII 字符时要注意。** BLAST+ 的索引库无法写入含非 ASCII 字符的路径。若工作目录的
> 最终路径含非 ASCII 字符(例如 Windows 用户名是中文),后端会**自动改用系统临时目录**,功能不受
> 影响,但索引缓存无法跨重启复用。

### 3.5 配置与环境变量

后端所有配置项经 `pydantic-settings` 使用 **`IGEM_`** 前缀(`backend/app/config.py`),
从 `backend/.env` 或环境变量读取:

| 变量 | 默认值 | 含义 |
|---|---|---|
| `IGEM_DB_HOST` | `localhost` | MySQL 主机 |
| `IGEM_DB_PORT` | `3306` | MySQL 端口 |
| `IGEM_DB_USER` | `root` | MySQL 用户 |
| `IGEM_DB_PASSWORD` | *(空)* | MySQL 密码 |
| `IGEM_DB_NAME` | `igem_terpene` | 数据库名 |
| `IGEM_BLAST_BIN_DIR` | `blast_bin` | BLAST+ 可执行文件目录 |
| `IGEM_BLAST_WORK_DIR` | `blast_work` | BLAST+ 工作目录 |

ETL 读的是**同一套 `IGEM_DB_*` 变量名**,但有自己的配置(`etl/config.py`),而且和后端不同——
**它只读环境变量,从不读 `.env`**。ETL 另有一个 `IGEM_DATA_DIR`,指向另一份 `for_*/` 目录,用于
**沙箱验证**:在改动真实数据库之前,先在独立的库上验证「幂等」「编号不变」这类不变量。

> ⚠️ **绝不要把真实凭据提交进仓库。** `backend/.env` 里是明文数据库密码。它必须写进 `.gitignore`,
> 且不得随仓库一起发布。

---

## 4. 数据来源

### 4.1 主源:UniProt

通过 `rest.uniprot.org` 的 REST 接口下载,**检索词只有一个:`(terpene)`**。

单一检索词是刻意的设计,不是简化。若拆成「已审阅 / 未审阅各下一次」,两次下载就落在**两个不同的
时间窗**;跨窗口发生的条目升级或降级,会让同一个条目同时落入两段,或被两段都漏掉。用单一检索词,
则整个数据集是**一个快照**,分段只在本地按 `Reviewed` 列切分。

| 分段 | 行数(2026-09-20) |
|---|---|
| `swiss_prot`(已审阅) | 1,535 |
| `trembl`(未审阅) | 94,334 |
| **合计** | **95,869** |

两段之和与 UniProt 报告的总数一致,一条不漏。

### 4.2 补充来源

原则是**只补导出文件里没有的内容**。能从 UniProt 导出列离线解析的就不额外打 API——离线解析的
可复现性也更好。

| 来源 | 接入方式 | 获取内容 |
|---|---|---|
| **Rhea** | SPARQL(`sparql.rhea-db.org`)+ RDF | 反应方程式、生理方向、EC 号、反应 SMILES |
| **ChEBI** | EBI FTP 平面文件(约 50 MB 压缩包) | 本地 SMILES / InChIKey 映射表,避免逐条查询 |
| **UniProt 导出列** | 离线解析,不打 API | GO 注释、异构体序列、参考文献(PubMed)、核酸编号 |
| **DDBJ** | `getentry.ddbj.nig.ac.jp` | 核酸序列链接 |
| **人工校订** | 仓库内 `update_tool/chebi_data/curation_overrides.tsv` | 对自动匹配结果的人工修正 |

外部链接(NCBI、EBI、PubChem、PubMed、DOI)仅用于生成跳转,不入库。

### 4.3 实测数据规模(2026-09-20)

| 项 | 数量 |
|---|---|
| 酶 | 95,869(1,535 Swiss-Prot + 94,334 TrEMBL) |
| 反应 | 714 |
| 化合物 | 734 |
| 酶–反应边 | 20,616 |
| 检索索引行 | 3,756,596 |

---

## 5. 灌库(TSV → MySQL)

### 5.1 入口与阶段

灌库程序是 `etl/etl_run.py`,在 `etl/` 目录内运行:

```bash
cd etl && python -u etl_run.py                      # 全量灌库
cd etl && python -u etl_run.py --source=swiss_prot  # 只重载单个来源
```

`-u` 用于关闭 Python 输出缓冲;不加它日志会积在内存里,看起来像卡住了。除此之外只接受 `--help`,
其它参数一律退出报错。**`etl/` 里没有 `--dry-run`**——dry run 只存在于上游采集器
`update_tool/update_database.py`(§9 第 6 步)。

六个阶段按固定顺序执行,前后另有维护动作:

| 阶段 | 模块 | 写入 |
|---|---|---|
| 0(前置) | `etl_edges.snapshot_edge_ids()` | 在内存里快照已存在的边编号 |
| 0(前置) | `etl_run.purge_source()` | 清掉目标来源的行,子表优先 |
| 1/6 | `etl_compounds` | `compound` |
| 2/6 | `etl_enzymes` | `enzyme`、`enzyme_id_map` |
| 3/6 | `etl_reactions` | `reaction`、`reaction_compound` |
| 4/6 | `etl_edges` | `enzyme_reaction_edge` |
| 5/6 | `etl_master` | `gene`、`gene_sequence_link`、`evidence`、`enzyme_go`、`enzyme_isoform`、`enzyme_solubility_score` |
| 6/6 | `etl_search_index` | `search_index` |

第 5 阶段内部也有顺序,而且顺序有意义:酶总表 → 基因信息 → 序列链接 → 证据 → GO 注释 →
**异构体 → 溶解度分数**。异构体必须排在溶解度之前,因为溶解度装载要用异构体编号去异构体表里
核对。

### 5.2 输入契约

装载只读磁盘上的 TSV,从不联网——唯一的例外是为了解析已退役登录号而做的一次 UniProt HTTP 302
查询(`etl_enzymes._resolve_redirect`)。

分段靠文件名后缀识别:`<相对路径>.<来源>.tsv`,由 `etl/sources.segmented_path()` 拼出。缺一段就是
硬报 `FileNotFoundError`。另有三张汇合表是不带后缀读的,不能按来源切开(见 §10)。

### 5.3 幂等与编号稳定

重跑在结构上是安全的:程序**按来源清空再重载**,而不是全表 truncate。

- **清理顺序是子表优先**:`search_index` → `enzyme_solubility_score`、`enzyme_isoform`、
  `enzyme_go`、`evidence`、`gene_sequence_link`、`gene` → `enzyme_reaction_edge` → `enzyme`。
- **`enzyme_id` 永不回收。** 编号来自 `enzyme_id_map`,它记录每个 UniProt 登录号首次拿到的编号,
  且从不删除行——条目消失时只打 `retired_at` 标记。把回收的编号分配给别的条目,会让所有用过该
  编号的外部链接静默指向错误的酶(§10)。
- **`edge_id` 会被复用**,做法是在清理**之前**先快照已有的边编号。

已经踩过并记录下来的坑:

- **清理与装载不在同一个事务里。** 中途崩溃会留下可恢复的半程状态,重跑一遍即可。
- **`--source=<s>` 模式下,`reaction` 只插入、不更新**,因为同一条 Rhea 反应在不同分段里的方向可能
  不同。该模式还会跳过 `retired_at` 维护与退役登录号解析——这两件事都需要全量视图才能做对。
- **upsert 辅助函数返回的是输入行数,不是实际写入行数。** 重跑时日志打出同样的行数、而实际
  "0 new rows",是预期且正确的。
- **`search_index` 的行是选择性清理的。** 只有带 `enzyme_id` 的行才随来源一起删。不带 `enzyme_id`
  的是化合物/实体级行,与来源无关(同一个化合物就是同一个化合物,不因为来自哪一段而变),所以它们
  走单独的 upsert。若把这类行也按来源清,它们**永远匹配不上删除条件,每刷新一次就重复累积一份**。

---

## 6. 表结构

`sql/schema.sql` 负责建库并建 **15 张表**。它是建表语句的唯一真相源——灌库程序在运行时从这个文件
里抽取各条 `CREATE TABLE`。**不要手工建表。**

| 表 | 内容 |
|---|---|
| `enzyme` | 酶总表:UniProt ID、序列、来源类型(swiss_prot / trembl) |
| `compound` | 化合物:SMILES / InChI / InChIKey / ChEBI ID |
| `reaction` | 反应:Rhea ID、方程式、方向、EC 号 |
| `reaction_compound` | 底物 / 产物链接,带 `role` |
| `enzyme_reaction_edge` | 酶–反应边(图谱主体) |
| `gene` / `gene_sequence_link` | 基因与核酸序列链接 |
| `enzyme_go` / `enzyme_isoform` / `evidence` | GO 注释、异构体、证据 |
| `enzyme_solubility_score` | 溶解度模型分数——见 §8 |
| `pathway_cache` | 后端运行期缓存,ETL 从不碰它 |
| `search_index` | 检索索引(实测 3,756,596 行) |
| `enzyme_id_map` / `enzyme_alias_map` | 编号稳定性表,见 §10 |

**必须有的索引:** `search_index` 上的 `idx_search_index_value_prefix (field_value(64))`。缺了它检索会
慢约 **500 倍**。这就是建表必须走 `sql/schema.sql` 的原因。

并非所有表都由灌库程序写入。`enzyme_alias_map` 对 ETL 而言是**只读**的——整个仓库里没有一条针对它
的 `INSERT`,它由外部填充。`pathway_cache` 由建表语句创建,但只在后端运行时使用。

---

## 7. 起 Web 服务

仓库里**没有一键启动脚本**。服务要在两个终端里分别起,且 MySQL 必须先起来。

**后端**(在 `backend/` 目录,需提供数据库密码):

```bash
uvicorn app.main:app --port 8000
```

接口文档随后在 `http://localhost:8000/docs`。所有接口都在 `/api/v1` 前缀下,响应统一为
`{success, data, meta?, error?}` 信封格式。

路由分组:`metadata`、`graph`、`search`、`structure_search`、`enzymes`、`compounds`、`reactions`、
`blast`、`download`、`assets`。

**前端**(在 `frontend/` 目录):

```bash
npm install
npm run dev        # 开发服务器,默认 http://localhost:5173
npm run build      # tsc -b && vite build  →  dist/
```

前端以相对路径请求 `/api/v1`,依赖代理:开发时 Vite 把 `/api` 代理到 `VITE_BACKEND`
(默认 `http://127.0.0.1:8000`);生产环境需要给 `dist/` 配一条 `/api/` 代理规则和 SPA 回退
(`try_files ... /index.html`)。

> **重启 MySQL 之后必须重启后端。** 连接池里的连接会全部失效,不重启的话每个请求都返回 500。

### 7.1 化学信息学:一个有意的取舍

**本地不使用 RDKit、OpenBabel 或 Indigo。** 取而代之:

- 结构式 = **预生成的 SVG**(`/assets/compounds/{chebi_id}/structure.svg`、
  `/assets/reactions/{rhea_id}/atom-map.svg`)。
- 结构检索 = **InChIKey 精确匹配**(浏览器端 Ketcher 编辑器计算 InChIKey → `GET /api/v1/ketcher/search`),
  **不是子结构搜索**。

即:我们的结构检索能命中「同一个化合物」,但不能命中「结构相似的化合物」。引用这项功能时请注意这
一边界。

---

## 8. 溶解度分数

单独写这一节,是因为这个数字是界面上最容易被误读的一个。

### 8.1 它是什么、不是什么

**它是模型参考分,不是可溶性标签,也不是校准过的概率。** 具体来说:

- 库里**没有任何可溶性标签**,所以任何阈值都无法在本库上拟合或验证。套在这些分数上的阈值是**外来的
  假设**,不是本工作的结论。
- 基准集的阈值不可迁移。三个基准集各自的最优阈值在库里圈出的比例差 **28 倍**
  (0.35 圈中 27.7%,0.71 圈中 1.0%)。
- 因此界面上一律称它为**模型参考分**,从不写「可溶」。

### 8.2 出处与入库路径

分数由开源工具 **DeepSolNet** 使用其原始权重计算得出。在此之上,DeepSolNet 需要蛋白语言模型
**ESM C 300M**(两者的许可见 §12.2)。

**产分那一次运行不在本仓库里。** 仓库里有的是产出的逐酶分数表,已转换成与其他子表一致的形态:

```
for_enzyme_detail/child_tables/uniprotkb_solubility_score.tsv          (合并表,无 Source 列)
for_enzyme_detail/child_tables/uniprotkb_solubility_score.swiss_prot.tsv
for_enzyme_detail/child_tables/uniprotkb_solubility_score.trembl.tsv
```

装载程序读取的列:

| # | 列 | 含义 |
|---|---|---|
| 1 | `Entry` | UniProt 登录号,连接键 |
| 2 | `Isoform_ID` | 空 = canonical 行;否则为异构体登录号(如 `P0DI77-2`) |
| 3 | `DeepSolNet Score` | [0, 1] 连续值,**未经阈值处理** |
| 4 | `Membrane` | `membrane` / `non-membrane` / `unannotated`——见 §8.3 |
| 5 | `Membrane Evidence` | UniProt 原始注释文本,任何判定都可复核 |
| 6 | `Sequence Length` | 残基数,供分层与 QA |
| 7 | `Source` | `swiss_prot` / `trembl`(仅分段表有) |

装载程序(`etl_master.load_solubility_scores`)在第 5 阶段的最后一步读这些文件,写入
`enzyme_solubility_score`:

| 列 | 类型 | 说明 |
|---|---|---|
| `solubility_record_id` | 主键 | |
| `enzyme_id` | 外键 → `enzyme` | 经 `uniprot_id` 解析得到 |
| `isoform_id` | 可空 | NULL = canonical 行 |
| `deep_solnet_score` | `DECIMAL(7,6)` | 模型原始输出 |
| `membrane` | `VARCHAR(20)` | 三态,见 §8.3 |
| `membrane_evidence` | `VARCHAR(1024)` | |
| `sequence_length` | | |

入库时有过滤:canonical 行一律保留;异构体行**仅当该异构体的序列与其 canonical 序列不同**时才保留。
分数解析失败、或找不到对应酶的行会被跳过并计数。

> **关于文件格式。** 这些表文件**没有注释行**——ETL 用 `csv.DictReader` 读它们,`#` 开头的行会被
> 当成数据。所以模型出处写进了**列名**(`DeepSolNet Score`)而不是文件头。取值一律 ASCII 英文小写
> 连字符,与库里已有的枚举同风格。

### 8.3 三态膜蛋白:`unannotated` 不等于 `non-membrane`

来自 UniProt 的 `ft_transmem` + `cc_subcellular_location`:

| 值 | 判据 | 占比 |
|---|---|---|
| `membrane` | `TRANSMEM` 非空,或 `SUBCELLULAR LOCATION` 含 "membrane" | 18.06% |
| `non-membrane` | 有 SL 注释、无 `TRANSMEM`、SL 不含 "membrane" | 1.35% |
| `unannotated` | 两者皆空——**UniProt 没有说** | 80.59% |

这一列是**高精度低召回**:标出来的可信,但覆盖不到两成。剩下八成无法判定,**不能当可溶读**。

### 8.4 分数分布

| 统计量 | 值 |
|---|---|
| 最小 | 0.0112 |
| 中位 | 0.2754 |
| 最大 | 0.9914 |
| 0.5 所在百分位 | **第 92.5 百分位** |

0.5 落在第 92.5 百分位,是「这个原始数字不能当概率读」最清楚的一个论据。

---

## 9. 完整复现七步

共 7 步。换一批全新数据重建时按此执行;只刷新单一来源则只需重跑第 4、6、7 步。

**下表命令均假定当前目录是仓库根目录**(第 7 步会自行切到 `etl/`)。第 3、4、5 步需要联网。

| 步 | 命令 | 耗时(实测) |
|---|---|---|
| 0 | 配置 MySQL 的 `datadir` / `tmpdir` / 缓冲池(§3.2) | 每台机器一次 |
| 1 | `mysql -u root -p < sql/schema.sql` | 秒级 |
| 2 | 安装 §3.3 的三套依赖 | 数分钟 |
| 3 | `python update_tool/download_uniprot.py` | 几分钟 |
| 4 | `python update_tool/run_all.py --source=swiss_prot`<br>`python update_tool/run_all.py --source=trembl` | 约 9 分钟<br>约 2.5–3 小时 |
| 5 | `python update_tool/run_all.py --merge` | 几分钟 |
| 6 | `python update_tool/update_database.py --source=swiss_prot --dry-run`<br>(对 `trembl`、`--merge` 各再来一次,确认报告后去掉 `--dry-run` 真跑) | 秒级 |
| 7 | `cd etl && python -u etl_run.py` | 约 41 分钟 |

要点:

- 第 4 步两个来源**互不覆盖**,顺序无所谓,但都必须跑完才能进第 5 步(`--merge` 会检查)。
- 第 5 步的 3 张汇合表(底物-产物对 / 化合物 / 图节点)**不能按来源切开**:一对底物→产物天然由两个
  来源的酶共享。
- 第 6 步是**三条命令,不是一条**。覆盖前会自动备份到带时间戳的备份目录。
- 第 7 步的 `-u` 用于关闭 Python 输出缓冲,理由同上。
- **第 6、7 步读取连接信息的方式不同。** ETL 只读环境变量、不读 `.env`,所以第 7 步前必须在当前
  shell 里 `export IGEM_DB_PASSWORD=...`(Windows cmd 用 `set`);后端则可以从 `backend/.env` 读取。
- 命令里的 `python` 指你所用的解释器;若使用虚拟环境或 `python3`,请相应替换。
- **各步依赖不同:** 第 3–6 步跑的是 `update_tool/`(需 `requests` 等,见 §3.3 的缺口提示),
  第 7 步跑的是 `etl/requirements.txt`,启动 Web 服务才需要 `backend/requirements.txt`。

---

## 10. 不变量与设计取舍

下面几条是数据可信度的依据,也是设计上花力气最多的地方。

**酶编号永不回收。** `enzyme_id_map` 记录每个 UniProt 登录号首次获得的编号。条目从新版本数据中
消失时,只打 `retired_at` 标记,绝不删除该行。这张表刻意不加外键,也永不参与 `DELETE` /
`TRUNCATE`。若编号被回收再分配给别的条目,所有引用该编号的外部链接都会静默指向错误的酶。

**条目改号时编号接续。** UniProt 合并条目会把旧登录号降为 secondary。`enzyme_alias_map` 把编号接续
到同一生物学实体,避免同一个酶仅因为改号就被当成新酶重新发号。

**按来源分段替换,而非全表重建。** 数据更新以「来源」为最小替换单位。分段文件缺失时 ETL 硬报错,
理由见 §1 的风险不对称。

**动态列宽。** 部分列是「一酶多值」的列族(多个核酸编号、多个酶、多篇文献),其列数随数据增长。
程序按列头推导列宽而非写死上限——写死上限的后果不是报错,而是超出的部分**不存在**。

---

## 11. 已知限制

1. **结构检索是精确匹配,不支持子结构或相似性搜索**(§7.1)。
2. **`update_tool/` 缺少依赖声明文件**,从零复现需手动补装 `requests` 等库(§3.3)。
3. **重建耗时以小时计。** TrEMBL 段的联网步骤约 2.5–3 小时,且依赖外部 API 的可用性;网络步骤设有
   断点缓存,中断后可续跑。
4. **数据随 UniProt 版本漂移。** 本页规模数字是 2026-09-20 的快照,重新下载后条目数会变化。
5. **重启 MySQL 后必须重启后端**(§7),否则每个请求都返回 500。
6. **溶解度分数是模型参考分**,不是校准过的概率;本库中没有任何阈值经过标签验证(§8)。

---

## 12. 许可与署名

### 12.1 我们自己的代码与派生数据

我们自己的产出按「代码 / 数据」拆成两个许可:

| 部分 | 许可 | 全文 |
|---|---|---|
| 源代码——`backend/`、`frontend/`、`etl/`、`update_tool/`、`tools/`、`sql/` | **Apache License 2.0** | [`LICENSE`](../../LICENSE) |
| 派生的表——`for_*/`;以及文档——`docs/`、`.docx` 设计文档、`.png` 图片、JSON 数据文件 | **Creative Commons Attribution 4.0 International(CC BY 4.0)** | [`LICENSE-DATA`](../../LICENSE-DATA) |

用两个而不是一个,是因为这是两类不同的产出:代码用带明确专利授权的软件许可;数据用
**与上游数据源同一个**许可,这样从流水线这头到那头署名链条是连续的。

**在 CC BY 4.0 下,你可以共享和改编这些数据,包括商用**,条件是要给出适当的署名、链到
许可原文、并注明是否做过修改。上游各源要求的署名行集中记在 [`NOTICE`](../../NOTICE) ——
它同时也是我们自己的 CC BY 4.0 数据的署名声明。

若要使用本数据库,引用方式见 §12.4。

### 12.2 溶解度模型

这里涉及两个独立部件,上游条款各不相同。

**DeepSolNet**(打分工具)。其上游仓库在 README 里声明 MIT 许可,但**截至 2026-10-01 该仓库并不包含
`LICENSE` 文件**——GitHub 的 license API 对该仓库返回 404,仓库里也确实没有许可文件。声明的意向
明确是宽松的;缺的是**形式上的授权文本**,而非精神上的许可。我们在此如实记录,并不认为它构成使用
上的障碍。

**ESM C 300M**(DeepSolNet 所依赖的蛋白语言模型)。它最初由 EvolutionaryScale 以
**Cambrian Open License Agreement** 发布:允许商用,但带署名条件——须显著展示 "Built with ESM"、
衍生作品标题以 "ESM" 开头、NOTICE 中写指定声明。**但这已不是现状。** 该项目已转至
Chan Zuckerberg Biohub,模型现在改为 **MIT 许可且不再设门禁**:`Biohub/esm` 附有 MIT 的
`LICENSE.md`(Copyright 2026 Chan Zuckerberg Biohub, Inc.),其 README 写明 "These models are
available under the MIT license",Hugging Face 上的权重标为 `mit` 且 `gated: false`。旧的
`EvolutionaryScale/esmc-300m-2024-12` 模型仓库现在会重定向到 `biohub/esmc-300m-2024-12`。

网上仍有大量文档在讲 Cambrian 那套条款,DeepSolNet 的 README 也仍指向旧的下载地址。
**我们在 2026-10-01 直接对着上游源核对了当前条款**;若你要复用这条流水线,请自己再核一遍,
不要相信搜索结果。

剩下的是 Biohub 的 Acceptable Use Policy——模型 README 请求使用者遵守,内容包括禁止有害的生物/
化学用途,**不限制商用**。

### 12.3 上游数据源

| 来源 | 许可 |
|---|---|
| **UniProt** | CC BY 4.0(UniProt Consortium) |
| **Rhea** | CC BY 4.0(SIB / EMBL-EBI) |
| **ChEBI** | CC BY 4.0(EMBL-EBI) |
| **DDBJ**(经 INSDC) | **对使用与再分发均无限制。** 我们只存外链——见下 |
| **NCBI BLAST+** | NCBI 以公有领域软件分发。**本仓库不再分发它**——由使用者自行下载(§3.4) |

CC BY 4.0 附带署名要求:请注明相应的联盟/机构。具体署名行见 [`NOTICE`](../../NOTICE)。

**关于 DDBJ。** INSDC 的政策是:其成员库(DDBJ / ENA / GenBank)不对公开的核酸序列数据附加
使用限制;DDBJ 亦声明它不持有可用来限制使用或再分发的著作权。何况本库并不存 DDBJ 的记录 ——
只存登录号并据此生成外链(§4.2),所以无论如何都没有序列数据在本仓库被再分发。

### 12.4 如何引用我们

若使用本数据库,请引用本项目,以及 §13 列出的上游数据源。

---

## 13. 引用

- UniProt Consortium —— https://www.uniprot.org
- Rhea —— https://www.rhea-db.org
- ChEBI —— https://www.ebi.ac.uk/chebi
- DDBJ —— https://www.ddbj.nig.ac.jp
- NCBI BLAST+ —— https://www.ncbi.nlm.nih.gov
- ESM / ESMC —— https://github.com/Biohub/esm
- DeepSolNet —— https://github.com/wangxinglong1990/DeepSolNet

> **本节不构成法律意见。** 我们只是把上游条款在我们理解范围内的内容、按上述日期记录下来。
> 在依赖其中任何一条之前,请自行阅读许可原文。
