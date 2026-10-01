from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from typing import Optional

from app.database import Base


class EnzymeSolubilityScore(Base):
    """每酶的模型参考分 + 膜注释。

    粒度: `isoform_id IS NULL` 的行为 canonical 序列的分, 非空的行为该变体自己的分。

    ⚠️ **刻意不在 `Enzyme` 上加 relationship。** `Enzyme` 上已有的
    `lazy="selectin"` 关系正是 `_EnzymeRef` 存在的理由 —— 拉一次实体要额外几条 SQL,
    实测整实体 5.883s vs 列投影 0.482s(见 graph_service 模块 docstring)。
    本表只在明确需要分数的地方**按需单查**, 不做惰性加载。

    ⚠️ 读 canonical 分时一律带 `isoform_id IS NULL`。不带会连带变体行,
    一个酶在图上会出现两个分数。
    """

    __tablename__ = "enzyme_solubility_score"
    __table_args__ = (
        Index("idx_enzyme_solubility_score_enzyme", "enzyme_id"),
        Index("idx_enzyme_solubility_score_value", "deep_solnet_score"),
    )

    solubility_record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enzyme_id: Mapped[str] = mapped_column(String(20), ForeignKey("enzyme.enzyme_id"), nullable=False)
    isoform_id: Mapped[Optional[str]] = mapped_column(String(80))
    # DECIMAL(7,6): 源数据实测最长 8 字符、6 位小数, 用 float 会在往返中丢末位。
    deep_solnet_score: Mapped[Optional[float]] = mapped_column(Numeric(7, 6))
    membrane: Mapped[Optional[str]] = mapped_column(String(20))
    membrane_evidence: Mapped[Optional[str]] = mapped_column(String(1024))
    sequence_length: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
