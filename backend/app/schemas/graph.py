from typing import Optional, List

from app.schemas.common import CamelModel
from app.schemas.compound import CompoundCard
from app.schemas.enzyme import EnzymeCard


class FocusPoint(CamelModel):
    node_id: Optional[str] = None
    edge_id: Optional[str] = None
    pathway_id: Optional[str] = None


class ReactionEdge(CamelModel):
    edge_id: str
    edge_group_id: Optional[str] = None
    reaction_id: str
    enzyme_id: str
    source_compound_id: str
    target_compound_id: str
    label: str
    direction: str
    source_type: str
    review_status: str
    card: Optional[EnzymeCard] = None


class EdgeGroupItem(CamelModel):
    """Minimal per-sub-edge summary carried on a collapsed composite edge.

    Lets the client apply species/source-type filters and search highlights to
    the individual edges inside a composite without expanding it.
    """

    edge_id: str
    enzyme_id: str
    label: Optional[str] = None
    organism_name: Optional[str] = None
    source_type: Optional[str] = None
    review_status: Optional[str] = None
    # 客户端拿这两项做本地筛选（阈值 + 只看膜蛋白），所以要挂在**每条子边**上，
    # 而不是只在展开后的卡片上 —— 不展开的复合边也要能判显隐。
    deep_solnet_score: Optional[float] = None
    membrane: Optional[str] = None


class EdgeGroup(CamelModel):
    edge_group_id: str
    source_compound_id: str
    target_compound_id: str
    label: str
    count: int
    # `label` 里那个 N，即**不同的酶**个数。`count` 是记录数 —— 同一个酶用两条反应催化
    # 同一对化合物时会生成两条记录（一个 edge_id 一条）。全库 175 个组里有 11 个两者不等，
    # 最大的一组（FPP↔squalene）count=7093 而酶只有 3595。界面上那行 `enzyme*N` 要的是后者，
    # 但 `count` 不能跟着改：客户端拿「edgeIds.length >= count」当载荷是否被截断的判据
    # （`graphExperience.tsx` 的 `buildHomePairs`），也拿它当拼贴图的排序键。
    enzyme_count: int
    edge_ids: List[str] = []
    items: List[EdgeGroupItem] = []


class GraphPayload(CamelModel):
    nodes: List[CompoundCard] = []
    edges: List[ReactionEdge] = []
    edge_groups: List[EdgeGroup] = []
    highlighted_node_ids: List[str] = []
    highlighted_edge_ids: List[str] = []
    focus: Optional[FocusPoint] = None
    filters: Optional[dict] = None
