"""`/bundle/*` 聚合端点的 schema。

判别键放在**外层信封**的 `kind` 上（`BundleData` 的 discriminated union），而不是
`entity` 字段上的 `Union[EnzymeDetail, CompoundCard, ReactionDetail]` —— 后者靠
pydantic smart union 运行时也能work，但语义上有歧义，且会把 `kind` 标记丢掉。

注：现有路由没有一个声明 `response_model`，`ApiResponse.data` 是 `Any`，所以
`/docs` 里 `data` 无论如何都是无类型的 —— 这里按运行时清晰度选，不考虑 OpenAPI 渲染。
想让形状出现在文档里就得把 `ApiResponse` 泛型化，超出本端点范围。
"""
from typing import Annotated, List, Literal, Optional, Union

from pydantic import Field

from app.schemas.common import CamelModel, ErrorDetail
from app.schemas.compound import CompoundCard
from app.schemas.enzyme import EnzymeDetail
from app.schemas.pathway import PathwayCard
from app.schemas.reaction import ReactionDetail

BUNDLE_KINDS = ("enzyme", "compound", "reaction", "pathway")

#: 一次批量最多几条。单条 enzyme 要发 `~8 + 2·R` 条查询且不做预取，
#: 50 条已经是几百条查询的量级；提高要连同 prefetch 一起考虑。
MAX_BATCH_ITEMS = 50

BundleKind = Literal["enzyme", "compound", "reaction", "pathway"]
ImageSource = Literal["chebi_proxy", "database", "none"]


class CompoundImage(CamelModel):
    compound_id: str
    name: str
    chebi_id: Optional[str] = None
    image_url: Optional[str] = None
    source: ImageSource = "none"


class EnzymeBundle(CamelModel):
    kind: Literal["enzyme"] = "enzyme"
    entity_id: str
    entity: EnzymeDetail
    images: List[CompoundImage] = Field(default_factory=list)


class CompoundBundle(CamelModel):
    kind: Literal["compound"] = "compound"
    entity_id: str
    entity: CompoundCard
    images: List[CompoundImage] = Field(default_factory=list)


class ReactionBundle(CamelModel):
    kind: Literal["reaction"] = "reaction"
    entity_id: str
    entity: ReactionDetail
    images: List[CompoundImage] = Field(default_factory=list)


class PathwayBundle(CamelModel):
    """`entityId` 是 `PATH_A_B_C` —— 一条化合物链，不是表里的一行。

    注意它**不是稳定主键**：id 指向的是一条可达性，ETL 重跑后某条边没了，同一个 id
    就会查不到。也别把它当"某一次搜索"的句柄 —— 筛选条件不在 id 里。
    """

    kind: Literal["pathway"] = "pathway"
    entity_id: str
    entity: PathwayCard
    images: List[CompoundImage] = Field(default_factory=list)


BundleData = Annotated[
    Union[EnzymeBundle, CompoundBundle, ReactionBundle, PathwayBundle],
    Field(discriminator="kind"),
]


class BundleBatchItem(CamelModel):
    # 故意是 str 而不是 BundleKind：单个非法 kind 只让那一条 found:false，
    # 不会把整个请求 422 掉。
    kind: str
    entity_id: str


class BundleBatchRequest(CamelModel):
    items: List[BundleBatchItem] = Field(..., min_length=1, max_length=MAX_BATCH_ITEMS)


class BundleBatchResult(CamelModel):
    kind: str
    entity_id: str
    found: bool
    bundle: Optional[BundleData] = None
    error: Optional[ErrorDetail] = None


class BundleBatchData(CamelModel):
    items: List[BundleBatchResult] = Field(default_factory=list)
