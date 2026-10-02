"""聚合端点：一次调用同时拿到实体字段 + 其涉及化合物的结构图 URL。

装配逻辑全在 `app.services.entity_service` —— 本文件只做参数检查与信封包装。
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.schemas.bundle import BUNDLE_KINDS, BundleBatchData, BundleBatchRequest
from app.schemas.common import ApiResponse, ErrorDetail
from app.services.entity_service import (
    build_entity_bundle,
    build_entity_bundles,
    find_compound_id_by_inchikey,
)
from app.utils.chemistry import smiles_to_inchikey

router = APIRouter()


@router.get("/bundle/{kind}/{entity_id}")
async def get_entity_bundle(
    kind: str,
    entity_id: str,
    source_types: Optional[List[str]] = Query(
        None, description="仅 pathway 用：重建链时透传的来源筛选"
    ),
    review_statuses: Optional[List[str]] = Query(
        None, description="仅 pathway 用：重建链时透传的审核状态筛选"
    ),
    db: AsyncSession = Depends(get_db),
):
    """kind ∈ enzyme | compound | reaction | pathway。

    `pathway` 的 entityId 是 `PATH_A_B_C`（见 `pathway_service.parse_pathway_id`）。
    它不是表里的一行，而是**按这条链现算**出来的；id 本身不含筛选条件，所以如果当初
    是用带筛选的 `POST /search/pathways` 搜出来的，这里要把同样的筛选再传一遍。
    """
    # kind 故意不标 Literal: 否则 FastAPI 会返回非信封的 422,
    # 而本仓库的约定是 HTTP 200 + success:false (见 metadata / search 等路由)。
    if kind not in BUNDLE_KINDS:
        return ApiResponse(success=False, error={"code": "BAD_REQUEST", "message": f"Unknown kind {kind}"})

    bundle, error = await build_entity_bundle(
        db, kind, entity_id,
        source_types=source_types,
        review_statuses=review_statuses,
    )
    if bundle is None:
        return ApiResponse(success=False, error=error.model_dump(by_alias=True))
    return ApiResponse(data=bundle.model_dump(by_alias=True))


@router.post("/bundle/batch")
async def post_entity_bundles(
    payload: BundleBatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """按入参顺序逐条返回；某条查不到不让整个请求失败。

    每条只有 `{kind, entityId}`，所以 pathway 在这里一律按**不筛**重建。
    """
    results = await build_entity_bundles(db, [(i.kind, i.entity_id) for i in payload.items])
    found = sum(1 for r in results if r.found)
    data = BundleBatchData(items=results)
    return ApiResponse(
        data=data.model_dump(by_alias=True),
        meta={"total": len(results), "found": found, "missing": len(results) - found},
    )


@router.get("/bundle/compound")
async def get_compound_bundle_by_smiles(
    # 故意是 Optional 而不是 Query(...): 必填参数缺失时 FastAPI 返回**非信封的 422**,
    # 而本仓库的约定是 HTTP 200 + success:false —— 理由与下面 kind 那处完全相同。
    smiles: Optional[str] = Query(None, description="SMILES; resolved to a compound server-side with RDKit"),
    db: AsyncSession = Depends(get_db),
):
    """按 SMILES 取化合物 bundle —— 「我还不知道 compoundId」时的入口。

    单独一条路由, 而不是给 `/bundle/{kind}/{entity_id}` 加个参数: SMILES 含
    `/ \\ # + @ [ ]`, 其中 `/` 哪怕编码成 `%2F` 也会在路由匹配前被解码、把路径切断,
    所以它不能走路径段。这条只有两段, 与三段的那条不会撞。

    响应与 `GET /bundle/compound/{id}` **完全相同** —— SMILES 只是"怎么找到这个化合物"的
    另一种寻址方式, 不改变"找到之后返回什么"。调用方从 `data.entityId` 看解析结果。
    """
    raw = (smiles or "").strip()
    if not raw:
        return ApiResponse(success=False, error={"code": "BAD_REQUEST", "message": "SMILES is required"})

    # **不能 upper()**: SMILES 区分大小写, 芳香性的 c/n/o 与手性的 @ 大写之后会变成另一个分子
    # —— `c1ccccc1O`(苯酚) 静默变成 `C1CCCCC1O`(环己醇), RDKit 照样解析成功、不报错。
    key = smiles_to_inchikey(raw)
    if key is None:
        return ApiResponse(
            success=False,
            error=ErrorDetail(
                code="INVALID_SMILES",
                message="SMILES could not be parsed",
                details={"smiles": raw},
            ).model_dump(by_alias=True),
        )
    if not key:
        # 与上一条分开: SMILES 本身没写错, 是它描述了一个含 * 的 R 基/Markush 通式, 本来就没有
        # InChIKey。调用方要做的动作不同 —— 换一条 SMILES, 而不是去改语法。
        return ApiResponse(
            success=False,
            error=ErrorDetail(
                code="INCHIKEY_UNAVAILABLE",
                message="SMILES parsed but has no InChIKey (generic / R-group structure)",
                details={"smiles": raw},
            ).model_dump(by_alias=True),
        )

    compound_id = await find_compound_id_by_inchikey(db, key)
    if compound_id is None:
        return ApiResponse(
            success=False,
            error=ErrorDetail(
                code="NOT_FOUND",
                message=f"No compound with InChIKey {key}",
                details={"smiles": raw, "inchikey": key},
            ).model_dump(by_alias=True),
        )

    bundle, error = await build_entity_bundle(db, "compound", compound_id)
    if bundle is None:
        return ApiResponse(success=False, error=error.model_dump(by_alias=True))
    return ApiResponse(data=bundle.model_dump(by_alias=True))
