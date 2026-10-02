"""
Generate all_nodes.tsv (图节点表).
Format: ChEBI ID, Name, InChI Key, InChI Key Derived

构造逻辑:
  - 化合物集合 = terpene_only 所有 Substrate/Product ChEBI 去重, 去掉 GENERIC:*
  - Name        = chebi_full.tsv 的 Name
  - InChI Key   = ChEBI 官方 standard_inchi_key (structures.tsv.gz 里 default_structure=true
                  的那一行)。权威值, 也是对外发布的那一列。
  - InChI Key Derived = RDKit 从本行 SMILES 现算。SMILES 与写进 compound.smiles 的是同一份
                  (chebi_full.tsv 与 uniprotkb_terpene_compounds.tsv 实测 730/730 逐字节
                  相同), 所以它保证与库里的结构自洽。两列在 710 条可比数据里只在 2 条上分歧
                  (CHEBI:231826 / CHEBI:53643 —— ChEBI 自己的 smiles 与 standard_inchi
                  互相矛盾), 那两条两个键都能查到。留第二列就是为了不仲裁这 2 条。
  - 排序        = ChEBI ID 字符串升序 (与旧表一致)

第 4 个参数给一个已有的 all_nodes 文件时, 复用它里面的官方 InChI Key 列 (恢复/验证用)。
派生列**总是现算** —— 它是本地计算, 没有省的必要, 而"复用一个缺列的旧文件"会静默产出空列。

历史: 2026-10 之前 InChI Key 是拿 ChEBI ID 去问 PubChem 的 /compound/name/ 得来的。那是
**同义词模糊匹配**端点, 多个 ChEBI 号会折到同一个 CID —— 712 条有值的行里 27 条写进了别人
分子的键 (5 对撞车, 其中 4 条连连接层都不同)。那条网络路径已整体删除, 不要恢复。
"""
import csv
import gzip
import os
import sys

# 用法: python build_all_nodes.py [terpene_only] [chebi_full] [输出] [可选: 已有all_nodes复用它官方键]
TERPENE_INPUT = sys.argv[1] if len(sys.argv) > 1 else '../for_graph/uniprotkb_terpene_only.tsv'
CHEBI_INPUT = sys.argv[2] if len(sys.argv) > 2 else 'chebi_data/chebi_full.tsv'
OUTPUT = sys.argv[3] if len(sys.argv) > 3 else 'output_all_nodes.tsv'
REUSE = sys.argv[4] if len(sys.argv) > 4 else ''

# structures.tsv.gz 与 chebi_full.tsv 同在 chebi_data/ —— 按输入路径推导, 不写死本机路径
STRUCTURES_FILE = os.path.join(os.path.dirname(os.path.abspath(CHEBI_INPUT)), 'structures.tsv.gz')

# 解析失败的化合物超过这个数就打印明细 (避免一屏刷不完, 又不会把问题藏起来)
MAX_REPORT_FAILED = 20


def _load_rdkit():
    """延迟导入: 走第 4 参数的恢复路径时不需要 rdkit。"""
    try:
        from rdkit import Chem, RDLogger
    except ImportError:
        sys.exit('算派生 InChI Key 需要 rdkit:  pip install rdkit\n'
                 '(若只想复用已有产物, 传第 4 个参数指向它)')
    # 解析告警很刷屏, 但失败不会漏 —— 下面按 None 计数并打印
    RDLogger.DisableLog('rdApp.*')
    return Chem


def load_official_keys(chebi_ids):
    """从 ChEBI 官方 structures.tsv.gz 取 default_structure 那一行的 standard_inchi_key。"""
    if not os.path.exists(STRUCTURES_FILE):
        sys.exit(f'缺少参考库: {STRUCTURES_FILE}\n'
                 f'先跑:  python {os.path.join(os.path.dirname(os.path.abspath(__file__)), "update_chebi_library.py")}')
    wanted = set(chebi_ids)
    keys = {}
    with gzip.open(STRUCTURES_FILE, 'rt', encoding='utf-8') as f:
        for row in csv.DictReader(f, delimiter='\t'):
            if row.get('default_structure') != 'true':
                continue
            acc = row.get('compound_id', '').strip()
            if not acc:
                continue
            # 这里是裸数字 (15377), 我们库里是 CHEBI:15377
            if not acc.startswith('CHEBI:'):
                acc = 'CHEBI:' + acc
            if acc not in wanted:
                continue
            key = row.get('standard_inchi_key', '').strip()
            if key:
                keys[acc] = key
    return keys


def reuse_official_keys(path):
    with open(path, 'r', encoding='utf-8') as f:
        return {r['ChEBI ID']: r['InChI Key'].strip()
                for r in csv.DictReader(f, delimiter='\t')
                if r.get('InChI Key', '').strip()}


def compute_derived_keys(chebi_ids, smiles_by_id):
    Chem = _load_rdkit()
    keys, failed = {}, []
    for cid in chebi_ids:
        smi = smiles_by_id.get(cid, '')
        mol = Chem.MolFromSmiles(smi) if smi else None
        if mol is None:
            # 无 SMILES 与解析不出来都归到这里: 都拿不到派生键, 都不该静默
            failed.append(cid)
            keys[cid] = ''
            continue
        keys[cid] = Chem.MolToInchiKey(mol) or ''
    return keys, failed


# ---- Step 1: 化合物集合 + 名称 + SMILES ----
comps, smiles = {}, {}
with open(TERPENE_INPUT, 'r', encoding='utf-8') as f:
    for r in csv.DictReader(f, delimiter='\t'):
        for c in (r['Substrate ChEBI'], r['Product ChEBI']):
            if c and not c.startswith('GENERIC'):
                comps.setdefault(c, '')
with open(CHEBI_INPUT, 'r', encoding='utf-8') as f:
    for r in csv.DictReader(f, delimiter='\t'):
        if r['ChEBI ID'] in comps:
            comps[r['ChEBI ID']] = r['Name']
            smiles[r['ChEBI ID']] = (r.get('SMILES') or '').strip()
chebi_ids = sorted(comps.keys())
print(f'Distinct non-GENERIC compounds: {len(chebi_ids)}')

# ---- Step 2a: 官方 InChI Key ----
if REUSE and os.path.exists(REUSE):
    official = reuse_official_keys(REUSE)
    print(f'Reused {len(official)} official InChI Keys from {REUSE}')
else:
    official = load_official_keys(chebi_ids)
    print(f'Official InChI Keys from {os.path.basename(STRUCTURES_FILE)}: {len(official)}/{len(chebi_ids)}')

# ---- Step 2b: 派生 InChI Key (RDKit, 本行 SMILES 现算) ----
derived, failed = compute_derived_keys(chebi_ids, smiles)
print(f'Derived InChI Keys: {sum(1 for k in derived.values() if k)}/{len(chebi_ids)}'
      f' (无 SMILES 或解析失败 {len(failed)})')
if failed:
    print('  解析不出来: ' + ', '.join(failed[:MAX_REPORT_FAILED])
          + (f' ... 另 {len(failed) - MAX_REPORT_FAILED} 个' if len(failed) > MAX_REPORT_FAILED else ''))

# 两列分歧的明细直接打出来 —— 正常就是那 2 条, 不是就该停下看
both = [c for c in chebi_ids if official.get(c) and derived.get(c)]
diff = [c for c in both if official[c] != derived[c]]
print(f'两列都有值 {len(both)} 条, 其中分歧 {len(diff)} 条' + (': ' + ', '.join(diff) if diff else ''))

# ---- Step 3: 输出 ----
fields = ['ChEBI ID', 'Name', 'InChI Key', 'InChI Key Derived']
with open(OUTPUT, 'w', encoding='utf-8', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(fields)
    for cid in chebi_ids:
        w.writerow([cid, comps[cid], official.get(cid, ''), derived.get(cid, '')])

print(f'Done! {len(chebi_ids)} rows -> {OUTPUT}')
