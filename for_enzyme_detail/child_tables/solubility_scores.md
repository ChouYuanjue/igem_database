# uniprotkb_solubility_score — 子表形态的得分表

由 `deliverables/enzyme_solubility_scores.tsv` 转换而来，格式照 `for_enzyme_detail/child_tables/`
里已有的六张子表。

## 三个文件

| 文件 | 行数 | 说明 |
|---|---:|---|
| `uniprotkb_solubility_score.swiss_prot.tsv` | 1,591 | 1,535 canonical + 56 isoform |
| `uniprotkb_solubility_score.trembl.tsv` | 94,334 | 全为 canonical（TrEMBL 无 isoform 注释）|
| `uniprotkb_solubility_score.tsv` | 95,925 | 合并表，**无 `Source` 列** |

`Source` 取值即 `source_registry.py` 的 `SOURCES = ('swiss_prot', 'trembl')`。分段判据同
`update_database.py:57`——「一行是否对应一个 UniProt 条目」，得分表满足，故三份齐出。
两份分段表各自是合并表按 `Source` 过滤的结果，行序保持原样。

## 列

    1  Entry               UniProt 登录号，子表统一的外键
    2  Isoform_ID          空 = canonical 行；否则为 isoform 登录号（如 P0DI77-2）
    3  DeepSolNet Score    [0,1] 连续值，**未经阈值处理**
    4  Membrane            membrane / non-membrane / unannotated（三态，见下）
    5  Membrane Evidence   UniProt 原始注释文本，可复核
    6  Sequence Length     残基数，供分层与 QA
    7  Source              swiss_prot / trembl（仅分段表有）

**没有注释行。** ETL 用 `pandas.read_csv` 读子表（`update_tool/` 那侧用的才是 `csv.DictReader`），
两者都不认注释行，`#` 开头会被当成数据行，所以模型出处写进了列名（`DeepSolNet Score`）而不是文件头。
UTF-8 无 BOM，CRLF，制表符分隔。

取值一律 ASCII 英文小写连字符，与库里已有的枚举同风格（`left-to-right`、`not specified`、
`journal article`）。合并态子表实测 0 个非 ASCII 字符，本表也一样——**源交付物
`enzyme_solubility_scores.tsv` 的 `membrane` 列仍是中文**，两处不一致是有意的：那份的读者是人，
这份的读者是 ETL 和前端。

## 连接

`Entry` ↔ `enzyme.uniprot_id`（DB 中有 UNIQUE 索引）。`enzyme_id`（`ENZ######`）由 ETL 的
`enzyme_id_map` 分配，不在本表内；`JOIN enzyme ON enzyme.uniprot_id = Entry` 即可补上。
`(Entry, Isoform_ID)` 唯一，可作主键；`Isoform_ID` 为空即 canonical 行。

## 三态膜蛋白：`unannotated` 不等于 `non-membrane`

来自 UniProt 的 `ft_transmem` + `cc_subcellular_location`。

| 值 | 判据 | 占比 |
|---|---|---:|
| `membrane` | `TRANSMEM` 非空，或 `SUBCELLULAR LOCATION` 含 "membrane" | 18.06% |
| `non-membrane` | 有 SL 注释、无 `TRANSMEM`、SL 不含 "membrane" | 1.35% |
| `unannotated` | 两者皆空 —— **UniProt 没有说** | 80.59% |

这一列是**高精度低召回**：标出来的可信，但覆盖不到两成。剩下八成无法判定，不能当可溶读。

## 分数怎么用

**这是模型参考分，不是可溶性标签，也不是校准过的概率。** 阈值不能在库上拟合或验证
（库里没有任何可溶性标签）。评估结论、分布漂移与外部验证的完整记录见
`../threshold_decision.md`。要点：

- 库分布：min 0.0112 / 中位 0.2754 / max 0.9914，**0.5 落在第 92.5 百分位**。
- 不要沿用基准集的阈值：三个基准集的最优阈值在库上标出的比例差 28 倍
  （0.35 → 27.7%，0.71 → 1.0%）。
- 面向用户展示时写「模型参考分」，不要写「可溶性」。
