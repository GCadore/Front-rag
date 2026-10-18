import json,collections,datetime as dt,re
import numpy as np
D="/workspace/backstage-rag/data_full"
T=dt.datetime(2026,4,22,tzinfo=dt.timezone.utc)
docs=[json.loads(l) for l in open(f"{D}/documents/documents.jsonl")]
S={}
S["documentos_indexados"]=collections.Counter(d["type"] for d in docs)
def ts(x):
    try: return dt.datetime.fromtimestamp(int(x),dt.timezone.utc)
    except: return dt.datetime.fromisoformat(str(x).replace("Z","+00:00"))
dates={t:[ts(d["created_at"]) for d in docs if d["type"]==t and d["created_at"]] for t in ("issue","pr")}
S["periodo"]={t:[min(v).date().isoformat(),max(v).date().isoformat()] for t,v in dates.items()}
# labels de issues indexadas
lab=collections.Counter(); nlab=0
for d in docs:
    if d["type"]!="issue": continue
    ls=[x for x in (d["labels"] or "").split("|") if x]; nlab+=bool(ls)
    for x in ls: lab[x]+=1
S["issues_com_label"]=nlab
S["top_labels"]={p:[(k,v) for k,v in lab.most_common() if k.startswith(p)][:10] for p in ("area:","type:","integration:")}
S["top15_labels_issue"]=[(k,v) for k,v in lab.most_common() if k.split(":")[0] in ("area","type","integration")][:15]
# tamanho do texto (palavras) por tipo
wl={t:np.array([len(d["text"].split()) for d in docs if d["type"]==t]) for t in ("issue","pr","doc","adr")}
S["palavras_por_documento"]={t:{"mediana":int(np.median(v)),"p10":int(np.percentile(v,10)),"p90":int(np.percentile(v,90)),"media":round(float(v.mean()),1)} for t,v in wl.items()}
# issues por mês, inclusive depois de T (bruto, dedupe por número; só issues de humanos não dá p/ saber no bruto -> todas)
raw={}
for l in open(f"{D}/raw/issues.jsonl"):
    x=json.loads(l)
    if "pull_request" in x: continue
    raw[x["number"]]=x
bot=lambda x: x["user"]["type"]=="Bot" or x["user"]["login"].endswith("[bot]")
S["issues_brutas"]=len(raw); S["issues_brutas_bots"]=sum(bot(x) for x in raw.values())
mon=collections.Counter(x["created_at"][:7] for x in raw.values() if not bot(x))
S["issues_por_mes"]=dict(sorted(mon.items()))
idx_mon=collections.Counter(d.strftime("%Y-%m") for d in dates["issue"])
S["issues_indexadas_por_mes"]=dict(sorted(idx_mon.items()))
S["limpeza"]=json.load(open(f"{D}/reports/clean_stats.json"))["stats"]
san=json.load(open(f"{D}/reports/sanity_report.json"))
S["chunks"]={"base":san["chunks"],"base_tokens":san["tokens"]}
def ctype(f):
    c=collections.Counter()
    for l in open(f): c[json.loads(l)["metadata"]["type"]]+=1
    return dict(c)
S["chunks"]["enxuto"]=ctype(f"{D}/index_lean/chunks.jsonl"); S["chunks"]["logico"]=ctype(f"{D}/index_logico/chunks.jsonl")
ids=json.load(open(f"{D}/addons/base_extras_bm25/bm25_ids.json"))
S["chunks"]["base_extras"]={**san["chunks"],"changelog":36252,"commit":20741,"review":11755}
S["chunks"]["base_extras_total_ids"]=len(ids)
ts_=[json.loads(l) for l in open(f"{D}/testset/testset.jsonl")]
v2=[json.loads(l) for l in open("/workspace/testes/testset_v3.jsonl")]
S["testset"]=json.load(open(f"{D}/reports/testset_stats.json"))["stats"]
gold=[g for r in ts_ if r["gold_doc_ids"] for g in r["gold_doc_ids"]]
S["gabarito"]={"issues_com_gabarito":sum(bool(r["gold_doc_ids"]) for r in ts_),"refs_total":len(gold),"refs_unicas":len(set(gold)),
  "por_tipo_unicas":collections.Counter(g.split("-")[0] for g in set(gold)),"docs_por_issue_media":round(len(gold)/82,2),
  "queries_com_ref_mascarada":sum("[ref]" in r["query"] for r in ts_),"refs_mascaradas_total":sum(r["query_masked_refs"] for r in ts_)}
S["testset_v2"]={"total":len(v2),"grupos":collections.Counter(r["v2_grupo"] for r in v2),"abertas":sum(r["state"]=="open" for r in v2)}
json.dump(S,open("/workspace/apresentacao/estatisticas_base.json","w"),ensure_ascii=False,indent=1,default=str)
print(json.dumps({k:S[k] for k in ["documentos_indexados","periodo","issues_com_label","palavras_por_documento","issues_brutas","gabarito","testset_v2"]},default=str,ensure_ascii=False,indent=0))
print(S["top15_labels_issue"])
