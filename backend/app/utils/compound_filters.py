from app.models import Compound


EXCLUDED_COMMON_COMPOUND_IDS = {
    "CHEBI:15377",  # water
    "CHEBI:15378",  # proton
    "CHEBI:33019",  # diphosphate
    #
    # 以下是**氧化还原/能量/基团载体辅因子**。它们是全库连接度最高的一批化合物，
    # 而首页图是按度数 (边组的酶数 `count`) 挑节点的 —— 于是一屏 300 个点里有一大批
    # 是 NAD±/SAM/ATP 这类"每个萜类合成都绕不开、但本身不是萜"的分子，把 squalene、
    # lycopene、germacrene A 这些真正的主角挤出了画布。实测剔除后 19 个点换血，
    # 顶上来的全是萜类；边组 227 -> 175（丢掉的是辅因子自己之间的配对）。
    #
    # ⚠️ 刻意**不**收录途中的真化学 —— 排除这些会抹掉反应本身，而不只是去掉一个点：
    #   acetyl-CoA / acetoacetyl-CoA / HMG-CoA / mevalonate  (甲羟戊酸途径)
    #   IPP / DMAPP / GPP / FPP / GGPP                       (萜类前体)
    #   4-CDP-2-C-methyl-D-erythritol(+2-phosphate)          (MEP 途径)
    #   D-glyceraldehyde 3-phosphate                         (MEP 途径入口)
    # 判据是「它是不是萜类骨架的一部分」：是 → 留，只是搭便车的辅因子 → 收进来。
    "CHEBI:57540",  # NAD(1-)
    "CHEBI:57945",  # NADH(2-)
    "CHEBI:57783",  # NADPH(4-)
    "CHEBI:58437",  # deamido-NAD(2-)  (NAD 生物合成中间体)
    "CHEBI:30616",  # ATP(4-)
    "CHEBI:456216",  # ADP(3-)
    "CHEBI:58210",  # FMN(3-)
    "CHEBI:57618",  # FMNH2(2-)
    "CHEBI:87467",  # prenyl-FMNH2(2-)  (少数萜类合成酶的辅因子)
    "CHEBI:59789",  # S-adenosyl-L-methionine (SAM, 甲基供体)
    "CHEBI:57443",  # S-adenosylmethioninaminium  (SAM 的另一质子化态)
    "CHEBI:58533",  # S-methyl-5-thio-alpha-D-ribose 1-phosphate (MTA, SAM 副产物)
    "CHEBI:90779",  # S-substituted glutathione(1-)
    "CHEBI:16240",  # hydrogen peroxide
}


def displayable_compound_filters():
    """SQLAlchemy filters for curated compounds that should appear as graph nodes."""
    return [
        ~Compound.compound_id.in_(EXCLUDED_COMMON_COMPOUND_IDS),
        Compound.name != Compound.compound_id,
    ]
