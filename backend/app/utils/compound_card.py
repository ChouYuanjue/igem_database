"""全后端唯一的 12 字段 CompoundCard 装配器。

放在 `app/utils/` 而不是某个 service 里，是为了让所有 service 都能 import 它而不成环：
`entity_service` 要调 `pathway_service`，而 `pathway_service` 要调 `graph_service`，
如果 `graph_service` 再回头 import `entity_service` 就闭环了。这个模块只依赖 models 和
schemas，谁都能安全引用。

原先 `CompoundCard` 有 4 处独立装配（routers/enzymes.py、routers/compounds.py、
routers/reactions.py、services/graph_service.py），收口到这里之后只剩一份。
"""
from app.models import Compound
from app.schemas.compound import CompoundCard


def compound_to_card(c: Compound) -> CompoundCard:
    return CompoundCard(
        compound_id=c.compound_id,
        name=c.name,
        chebi_id=c.chebi_id,
        smiles=c.smiles,
        formula=c.formula,
        charge=float(c.charge) if c.charge else None,
        average_mass=float(c.average_mass) if c.average_mass else None,
        inchi=c.inchi,
        inchi_key=c.inchi_key,
        structure_image_url=c.structure_image_url,
        chebi_url=c.chebi_url,
        description=c.description,
    )
