"""SMILES → InChIKey 的服务端转换 (RDKit)。

RDKit 在这里**模块级导入**是有意的: 缺这个包时 import 本模块就失败, 而 main.py 挂载路由时会
import 到它, 于是 uvicorn 直接起不来。这是想要的失败方式 —— backend/requirements.txt 是安装
契约, 漏装应该在启动那几秒暴露, 而不是等第一个调用方提交 SMILES 时才变成那个端点的 500。
所以这里不放 try/except ImportError 的兜底。

口径与 update_tool/build_all_nodes.py 对齐: 同一个 rdkit, 同样关掉 RDLogger。
注意 compound.inchi_key_derived 那一列也是 RDKit 算的 —— 查询时算出的键要能匹配上它,
就得与当初产出它的 rdkit 同源。换版本的注意事项见 update_tool/requirements.txt。
"""
from typing import Optional

from rdkit import Chem, RDLogger

# RDKit 会把解析/InChI 诊断打到 stderr。关掉它不算"静默降级": 失败仍然通过返回值传出去
# (None 与 ""), 由调用方转成 API 错误码。先例见 update_tool/build_all_nodes.py。
RDLogger.DisableLog('rdApp.*')


def smiles_to_inchikey(smiles: str) -> Optional[str]:
    """把 SMILES 转成标准 InChIKey。

    三种返回值, 调用方必须区分:

    - ``None`` —— RDKit 根本解析不了这个输入 (语法错误、乱码)。
    - ``""``   —— 解析成功, 但算不出键。含 ``*`` 的 R 基 / Markush 通式走这一支:
      它不是坏 SMILES, 它本来就不是一个分子, 换任何转换器都一样。
    - 其余      —— 27 位 InChIKey (RDKit 返回的已经是大写)。

    注意空串在 RDKit 眼里是"合法分子", 同样落到 ``""`` 那一支。所以判空必须由调用方
    在**进这个函数之前**做, 否则 ``?smiles=`` 会被解释成"给了个通式"而不是"没给参数"。
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    return Chem.MolToInchiKey(mol) or ""
