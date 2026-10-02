"""实体字段装配 + 结构图 URL 解析。

详情端点（`/enzymes/{id}`、`/compounds/{id}/card`、`/reactions/{id}`）与
`/bundle/*` 聚合端点共用这里，路由层只做信封包装。

**为什么独立成 service**：`CompoundCard` 原先在后端有 4 处独立装配
（`routers/enzymes.py`、`routers/compounds.py`、`routers/reactions.py`、
`services/graph_service.py`），其中前两处静默漏传了
`formula` / `charge` / `inchi` / `description` —— pydantic 对缺省字段取 `None`
而不报错，于是酶详情页和反应详情页上的化合物卡片一直少这四个字段，没人发现。
收口到 `compound_to_card` 之后，这类漂移只有一个地方可改。

**批量的成本**：`load_enzyme_detail` 单条要发 `~8 + 2·R` 条查询（R = 反应数）——
酶、gene、4 次表存在性探测、sequence-links、evidence、edges，然后每条 edge 各
1 次 reaction + 1 次 reaction-compound。`build_entity_bundles` 只把 4 次探测抬到
循环外，**不做全量预取**：那要把 enzyme loader 改成一条大 JOIN 再在 Python 里分组，
等于重写，与"复用单条 loader"的目的相悖。代价由 `schemas.bundle.MAX_BATCH_ITEMS`
封顶，取舍是有意为之而非疏忽。
"""
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

from sqlalchemy import or_, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Compound,
    Enzyme,
    EnzymeGoTerm,
    EnzymeIsoform,
    EnzymeReactionEdge,
    EnzymeSolubilityScore,
    Evidence,
    Gene,
    GeneSequenceLink,
    Reaction,
    ReactionCompound,
)
from app.schemas.bundle import (
    BUNDLE_KINDS,
    BundleBatchResult,
    BundleData,
    CompoundBundle,
    CompoundImage,
    EnzymeBundle,
    PathwayBundle,
    ReactionBundle,
)
from app.schemas.common import ErrorDetail
from app.schemas.compound import CompoundCard
from app.schemas.enzyme import EnzymeDetail, EnzymeReactionItem, ExternalLink, GoTerm, IsoformSequence
from app.schemas.evidence import EvidenceItem
from app.schemas.gene import GeneSummary, SequenceLink
from app.schemas.reaction import ReactionDetail
from app.services.pathway_service import (
    PATHWAY_BAD_ID,
    PATHWAY_NOT_REACHABLE,
    PATHWAY_UNKNOWN_COMPOUND,
    load_pathway_by_chain,
    parse_pathway_id,
)
from app.utils.compound_card import compound_to_card as build_compound_card
from app.utils.compound_filters import displayable_compound_filters

# 缓存击穿串只此一处。它**归前端所有** —— 前端哪天 bump 到 v=5，这里还在发 v=4，
# 两边要一起改（前端三处：api.ts、graphExperience.tsx、components/StructureSearchDrawer.tsx）。
STRUCTURE_SUFFIX = "/structure.svg?v=4"
ASSET_PREFIX = "/api/v1/assets/compounds"


# --------------------------------------------------------------------------- 装配

def compound_to_card(c: Compound) -> CompoundCard:
    """见 `app.utils.compound_card` —— 这里只是 re-export，方便老调用点。"""
    return build_compound_card(c)


def _reaction_compound_cards(rows: Iterable[Tuple[ReactionCompound, Compound]]) -> Tuple[List[CompoundCard], List[CompoundCard]]:
    substrates: List[CompoundCard] = []
    products: List[CompoundCard] = []
    for rc, cpd in rows:
        card = compound_to_card(cpd)
        if rc.role.value == "substrate":
            substrates.append(card)
        else:
            products.append(card)
    return substrates, products


async def _fetch_reaction_compound_cards(
    db: AsyncSession, reaction_id: str
) -> Tuple[List[CompoundCard], List[CompoundCard]]:
    result = await db.execute(
        select(ReactionCompound, Compound)
        .join(Compound, ReactionCompound.compound_id == Compound.compound_id)
        .where(ReactionCompound.reaction_id == reaction_id)
        .where(*displayable_compound_filters())
    )
    return _reaction_compound_cards(result.all())


@dataclass(frozen=True)
class EnzymeTableFlags:
    """四张可选表是否存在。批处理时探测一次、循环内复用。"""

    gene_sequence_link: bool
    enzyme_go: bool
    enzyme_solubility_score: bool
    enzyme_isoform: bool


async def _table_exists(db: AsyncSession, table_name: str) -> bool:
    try:
        result = await db.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = :table_name"
            ),
            {"table_name": table_name},
        )
        return bool(result.scalar())
    except (ProgrammingError, OperationalError):
        # 注意：这会在批中途重置事务。批量全是读，回滚不丢东西，
        # 但别在写操作之后复用本模块。
        await db.rollback()
        return False


async def probe_enzyme_tables(db: AsyncSession) -> EnzymeTableFlags:
    return EnzymeTableFlags(
        gene_sequence_link=await _table_exists(db, "gene_sequence_link"),
        enzyme_go=await _table_exists(db, "enzyme_go"),
        enzyme_solubility_score=await _table_exists(db, "enzyme_solubility_score"),
        enzyme_isoform=await _table_exists(db, "enzyme_isoform"),
    )


async def _load_enzyme_detail_with_flags(
    db: AsyncSession, enzyme_id: str, flags: EnzymeTableFlags
) -> Optional[EnzymeDetail]:
    result = await db.execute(select(Enzyme).where(Enzyme.enzyme_id == enzyme_id))
    enz = result.scalar()
    if not enz:
        return None

    enzyme_values = {
        "enzyme_id": enz.enzyme_id,
        "primary_name": enz.primary_name,
        "secondary_names": enz.secondary_names or [],
        "uniprot_id": enz.uniprot_id,
        "organism_name": enz.organism_name,
        "sequence": enz.sequence,
        "length": enz.length,
        "mass": float(enz.mass) if enz.mass is not None else None,
        # 酶**自身**的来源/审核状态。与下面 reaction_items 里每一项的来源不是一回事:
        # 反应是共享的客观实体, etl_reactions 把所有 reaction 行都记成 swiss_prot
        # (见 schemas.EnzymeDetail 的说明)。取 .value 因为模型上是 ENUM。
        "source_type": enz.source_type.value if enz.source_type else None,
        "review_status": enz.review_status.value if enz.review_status else None,
    }

    # Gene
    gene_result = await db.execute(select(Gene).where(Gene.enzyme_id == enzyme_values["enzyme_id"]))
    gene = gene_result.scalar()
    gene_summary = None
    gene_ncbi_url = None
    if gene:
        gene_ncbi_url = gene.ncbi_url
        gene_summary = GeneSummary(
            gene_name=gene.gene_name,
            gene_record_id=str(gene.gene_id),
            genbank_id=gene.genbank_id,
            ncbi_url=gene.ncbi_url,
            ena_accession=gene.ena_accession,
            protein_accession=gene.protein_accession,
        )

    # Sequence links
    sequence_links = []
    if flags.gene_sequence_link:
        seq_link_result = await db.execute(
            select(GeneSequenceLink)
            .where(GeneSequenceLink.enzyme_id == enzyme_values["enzyme_id"])
            .order_by(GeneSequenceLink.link_category, GeneSequenceLink.sequence_link_id)
        )
        sequence_links = [
            SequenceLink(
                category=link.link_category,
                accession=link.accession,
                url=link.url,
                related_accession=link.related_accession,
                related_url=link.related_url,
            )
            for link in seq_link_result.scalars()
        ]

    # Evidence
    ev_result = await db.execute(select(Evidence).where(Evidence.enzyme_id == enzyme_values["enzyme_id"]))
    evidences = [
        EvidenceItem(
            doi=e.doi,
            pubmed_id=e.pubmed_id,
            title=e.title,
            authors=e.authors,
            journal=e.journal,
            volume=e.volume,
            pages=e.pages,
            publication_year=e.publication_year,
            reference_type=e.reference_type,
            positions=e.positions,
            url=e.url,
            source_description=e.source_description,
            review_status=e.review_status.value,
        ) for e in ev_result.scalars()
    ]

    go_terms = []
    if flags.enzyme_go:
        go_result = await db.execute(
            select(EnzymeGoTerm)
            .where(EnzymeGoTerm.enzyme_id == enzyme_values["enzyme_id"])
            .order_by(EnzymeGoTerm.go_record_id)
        )
        go_terms = [
            GoTerm(go_id=go.go_id, go_term=go.go_term, go_url=go.go_url)
            for go in go_result.scalars()
        ]

    # 模型参考分 + 膜注释。一次查询同时覆盖酶级(canonical)行与各变体行 ——
    # 表里 `isoform_id IS NULL` 的就是 canonical 序列的分。
    # 全库只有 30 条真变体有分, 所以 score_by_isoform 绝大多数时候是空的。
    enzyme_score = None
    enzyme_membrane = None
    score_by_isoform: dict = {}
    if flags.enzyme_solubility_score:
        sol_result = await db.execute(
            select(EnzymeSolubilityScore)
            .where(EnzymeSolubilityScore.enzyme_id == enzyme_values["enzyme_id"])
            .order_by(EnzymeSolubilityScore.solubility_record_id)
        )
        for sol in sol_result.scalars():
            score = float(sol.deep_solnet_score) if sol.deep_solnet_score is not None else None
            if sol.isoform_id is None:
                enzyme_score = score
                enzyme_membrane = sol.membrane
            else:
                score_by_isoform[sol.isoform_id] = score

    isoforms = []
    if flags.enzyme_isoform:
        isoform_result = await db.execute(
            select(EnzymeIsoform)
            .where(EnzymeIsoform.enzyme_id == enzyme_values["enzyme_id"])
            .order_by(EnzymeIsoform.isoform_record_id)
        )
        isoforms = [
            IsoformSequence(
                isoform_id=iso.isoform_id,
                isoform_length=iso.isoform_length,
                isoform_mass=iso.isoform_mass,
                canonical_sequence=iso.canonical_sequence,
                canonical_length=iso.canonical_length,
                canonical_mass=iso.canonical_mass,
                sequence=iso.sequence,
                # 按 isoform_id 直接组装, 不让前端做 id 匹配。
                deep_solnet_score=score_by_isoform.get(iso.isoform_id),
            )
            for iso in isoform_result.scalars()
        ]

    # Reactions
    edge_result = await db.execute(
        select(EnzymeReactionEdge).where(EnzymeReactionEdge.enzyme_id == enzyme_values["enzyme_id"])
    )
    edges = edge_result.scalars().all()
    reaction_items = []
    for edge in edges:
        rxn_result = await db.execute(
            select(Reaction).where(Reaction.reaction_id == edge.reaction_id)
        )
        rxn = rxn_result.scalar()
        if not rxn:
            continue

        substrates, products = await _fetch_reaction_compound_cards(db, rxn.reaction_id)

        reaction_items.append(EnzymeReactionItem(
            reaction_id=rxn.reaction_id,
            rhea_id=rxn.rhea_id,
            rhea_url=rxn.rhea_url,
            equation=rxn.equation,
            direction=rxn.direction.value,
            ec_number=rxn.ec_number,
            smiles=rxn.smiles,
            atom_map_image_url=rxn.atom_map_image_url,
            substrates=substrates,
            products=products,
            source_type=rxn.source_type.value if rxn.source_type else "swiss_prot",
            review_status=rxn.review_status.value if rxn.review_status else "official",
        ))

    # External links
    links = []
    if enzyme_values["uniprot_id"]:
        links.append(ExternalLink(label="UniProt", url=f"https://www.uniprot.org/uniprotkb/{enzyme_values['uniprot_id']}"))
    if gene_ncbi_url:
        links.append(ExternalLink(label="NCBI", url=gene_ncbi_url))

    return EnzymeDetail(
        enzyme_id=enzyme_values["enzyme_id"],
        database_code=enzyme_values["enzyme_id"],
        primary_name=enzyme_values["primary_name"],
        secondary_names=enzyme_values["secondary_names"],
        uniprot_id=enzyme_values["uniprot_id"],
        uniprot_url=f"https://www.uniprot.org/uniprotkb/{enzyme_values['uniprot_id']}" if enzyme_values["uniprot_id"] else None,
        organism_name=enzyme_values["organism_name"],
        sequence=enzyme_values["sequence"],
        length=enzyme_values["length"],
        mass=enzyme_values["mass"],
        source_type=enzyme_values["source_type"],
        review_status=enzyme_values["review_status"],
        deep_solnet_score=enzyme_score,
        membrane=enzyme_membrane,
        gene=gene_summary,
        sequence_links=sequence_links,
        go_terms=go_terms,
        isoforms=isoforms,
        reactions=reaction_items,
        evidence=evidences,
        links=links,
    )


async def load_enzyme_detail(
    db: AsyncSession,
    enzyme_id: str,
    flags: Optional[EnzymeTableFlags] = None,
) -> Optional[EnzymeDetail]:
    """None 表示酶不存在 —— 路由层翻译成 NOT_FOUND。"""
    if flags is None:
        flags = await probe_enzyme_tables(db)
    return await _load_enzyme_detail_with_flags(db, enzyme_id, flags)


async def load_compound_card(db: AsyncSession, compound_id: str) -> Optional[CompoundCard]:
    result = await db.execute(select(Compound).where(Compound.compound_id == compound_id))
    cpd = result.scalar()
    if not cpd:
        return None
    return compound_to_card(cpd)


async def load_reaction_detail(db: AsyncSession, reaction_id: str) -> Optional[ReactionDetail]:
    result = await db.execute(select(Reaction).where(Reaction.reaction_id == reaction_id))
    rxn = result.scalar()
    if not rxn:
        return None

    substrates, products = await _fetch_reaction_compound_cards(db, rxn.reaction_id)

    return ReactionDetail(
        reaction_id=rxn.reaction_id,
        rhea_id=rxn.rhea_id,
        rhea_url=rxn.rhea_url,
        equation=rxn.equation,
        direction=rxn.direction.value,
        ec_number=rxn.ec_number,
        smiles=rxn.smiles,
        atom_map_image_url=rxn.atom_map_image_url,
        substrates=substrates,
        products=products,
        source_type=rxn.source_type.value if rxn.source_type else "swiss_prot",
        review_status=rxn.review_status.value if rxn.review_status else "official",
    )


async def load_entity(db: AsyncSession, kind: str, entity_id: str):
    if kind == "enzyme":
        return await load_enzyme_detail(db, entity_id)
    if kind == "compound":
        return await load_compound_card(db, entity_id)
    if kind == "reaction":
        return await load_reaction_detail(db, entity_id)
    return None


async def find_compound_id_by_inchikey(db: AsyncSession, key: str) -> Optional[str]:
    """用一个 InChIKey 反查 compound_id, 找不到返回 None。

    匹配**跨两列**, 理由与 `routers/structure_search.py` 里那处相同: `inchi_key` 是 ChEBI
    官方值、`inchi_key_derived` 是 RDKit 从本行 smiles 现算的, 两者在 710 条可比数据里只差
    2 条 (`CHEBI:231826` / `CHEBI:53643`, ChEBI 自己那条记录自相矛盾)。只认一列会让
    "用另一种工具算出另一个键"的调用方查不到东西。

    今天**一个键最多命中一个化合物**(实测 710 条有键的化合物: 列内重复 0、跨列撞车 0),
    所以取第一条即可; 仍按 compound_id 排序, 好让结果在将来真出现重复时也是稳定的。
    """
    result = await db.execute(
        select(Compound.compound_id)
        .where(or_(Compound.inchi_key == key, Compound.inchi_key_derived == key))
        .order_by(Compound.compound_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


# --------------------------------------------------------------------------- 图片 URL

def compound_image_for_card(c: CompoundCard) -> CompoundImage:
    """逐字复刻前端三处 `compoundImageUrl`。

    `quote(key, safe="")` 把 `:` 编成 `%3A`，与 `encodeURIComponent` 的结果一致。
    两者只在 `!*'()` 上不同，而 ChEBI id 里不会出现这些字符。
    """
    key = c.chebi_id or c.compound_id
    if key and key.startswith("CHEBI:"):
        return CompoundImage(
            compound_id=c.compound_id,
            name=c.name,
            chebi_id=c.chebi_id,
            image_url=f"{ASSET_PREFIX}/{quote(key, safe='')}{STRUCTURE_SUFFIX}",
            source="chebi_proxy",
        )
    return CompoundImage(
        compound_id=c.compound_id,
        name=c.name,
        chebi_id=c.chebi_id,
        image_url=c.structure_image_url,
        source="database" if c.structure_image_url else "none",
    )


def _cards_of(kind: str, entity) -> List[CompoundCard]:
    if kind == "compound":
        return [entity]
    if kind == "reaction":
        return list(entity.substrates) + list(entity.products)
    cards: List[CompoundCard] = []
    for item in entity.reactions:
        cards.extend(item.substrates)
        cards.extend(item.products)
    return cards


def collect_images(kind: str, entity) -> List[CompoundImage]:
    """按 compoundId 去重，保持首次出现顺序。"""
    seen: Dict[str, CompoundImage] = {}
    for card in _cards_of(kind, entity):
        if card.compound_id not in seen:
            seen[card.compound_id] = compound_image_for_card(card)
    return list(seen.values())


async def _load_cards_for_ids(
    db: AsyncSession, compound_ids: Iterable[str]
) -> List[CompoundCard]:
    """按**给定顺序**取化合物卡片；查不到的跳过。

    pathway 卡片只带 `compoundIds`，没有内嵌 CompoundCard，所以要回表取一次。
    """
    ids = list(compound_ids)
    if not ids:
        return []
    result = await db.execute(select(Compound).where(Compound.compound_id.in_(ids)))
    by_id = {c.compound_id: compound_to_card(c) for c in result.scalars()}
    return [by_id[cid] for cid in ids if cid in by_id]


async def _images_for(db: AsyncSession, kind: str, entity) -> List[CompoundImage]:
    if kind == "pathway":
        # 链序 = 反应顺序，有意义，所以直接用它在链上的顺序，不走 collect_images。
        cards = await _load_cards_for_ids(db, entity.compound_ids)
        return [compound_image_for_card(c) for c in cards]
    return collect_images(kind, entity)


# --------------------------------------------------------------------------- bundle

def _wrap(kind: str, entity_id: str, entity, images: List[CompoundImage]) -> BundleData:
    if kind == "enzyme":
        return EnzymeBundle(entity_id=entity_id, entity=entity, images=images)
    if kind == "compound":
        return CompoundBundle(entity_id=entity_id, entity=entity, images=images)
    if kind == "pathway":
        return PathwayBundle(entity_id=entity_id, entity=entity, images=images)
    return ReactionBundle(entity_id=entity_id, entity=entity, images=images)


_KIND_LABEL = {
    "enzyme": "Enzyme",
    "compound": "Compound",
    "reaction": "Reaction",
    "pathway": "Pathway",
}

_PATHWAY_FAILURES = {
    PATHWAY_BAD_ID: ("BAD_REQUEST", "malformed pathway id"),
    PATHWAY_UNKNOWN_COMPOUND: ("NOT_FOUND", "pathway references an unknown compound"),
    PATHWAY_NOT_REACHABLE: (
        "NOT_FOUND",
        "pathway is not reachable under the current filters",
    ),
}


async def build_entity_bundle(
    db: AsyncSession,
    kind: str,
    entity_id: str,
    flags: Optional[EnzymeTableFlags] = None,
    source_types: Optional[List[str]] = None,
    review_statuses: Optional[List[str]] = None,
) -> Tuple[Optional[BundleData], Optional[ErrorDetail]]:
    """返回 `(bundle, error)`，两者恰有一个非 None。

    kind 非法 → BAD_REQUEST。pathway 走 `PATH_` id：id 只编码化合物链、**不编码筛选
    条件**，所以把 `source_types`/`review_statuses` 一并透传给 `load_pathway_by_chain`，
    否则拿到的 segment 未必是调用方当初看到的那组。
    """
    if kind not in BUNDLE_KINDS:
        return None, ErrorDetail(code="BAD_REQUEST", message=f"Unknown kind {kind}")

    if kind == "enzyme":
        entity = await load_enzyme_detail(db, entity_id, flags=flags)
    elif kind == "pathway":
        chain = parse_pathway_id(entity_id)
        if chain is None:
            return None, _pathway_error(PATHWAY_BAD_ID, entity_id)
        entity, failure = await load_pathway_by_chain(
            db, chain, source_types, review_statuses
        )
        if entity is None:
            return None, _pathway_error(failure, entity_id)
    else:
        entity = await load_entity(db, kind, entity_id)

    if entity is None:
        return None, ErrorDetail(
            code="NOT_FOUND",
            message=f"{_KIND_LABEL[kind]} {entity_id} not found",
        )
    return _wrap(kind, entity_id, entity, await _images_for(db, kind, entity)), None


def _pathway_error(failure: Optional[str], entity_id: str) -> ErrorDetail:
    code, message = _PATHWAY_FAILURES.get(failure or PATHWAY_NOT_REACHABLE, ("NOT_FOUND", "pathway unavailable"))
    return ErrorDetail(code=code, message=f"{message}: {entity_id}")


async def build_entity_bundles(
    db: AsyncSession,
    requests: List[Tuple[str, str]],
) -> List[BundleBatchResult]:
    """按入参顺序逐条返回；重复 id 复用上次的查询结果，但仍各出一条。

    `requests` 是 `[(kind, entity_id), ...]`，长度已由
    `BundleBatchRequest.items` 的 `max_length` 限制。
    """
    flags = await probe_enzyme_tables(db)
    cache: Dict[Tuple[str, str], BundleBatchResult] = {}
    results: List[BundleBatchResult] = []

    for kind, entity_id in requests:
        key = (kind, entity_id)
        if key in cache:
            results.append(cache[key])
            continue

        # 批量项只有 {kind, entityId}，放不下筛选条件 —— pathway 在这里一律按
        # 不筛重建，需要带筛选的走单条端点。
        bundle, error = await build_entity_bundle(db, kind, entity_id, flags=flags)
        if bundle is None:
            result = BundleBatchResult(
                kind=kind,
                entity_id=entity_id,
                found=False,
                error=error or ErrorDetail(code="NOT_FOUND", message=f"{entity_id} not found"),
            )
        else:
            result = BundleBatchResult(kind=kind, entity_id=entity_id, found=True, bundle=bundle)

        cache[key] = result
        results.append(result)

    return results
