import json,matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import datetime as dt
S=json.load(open("/workspace/apresentacao/estatisticas_base.json"))
O="/workspace/apresentacao/"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":20,"axes.titlesize":28,"axes.labelsize":22,"axes.spines.top":False,"axes.spines.right":False,"axes.titleweight":"bold","axes.titlepad":18})
C={"issue":"#2E75B6","pr":"#ED7D31","doc":"#70AD47","adr":"#7030A0","changelog":"#A5A5A5","commit":"#FFC000","review":"#5B9BD5"}
PT={"issue":"Issues","pr":"PRs","doc":"Docs","adr":"ADRs","changelog":"Changelogs","commit":"Commits","review":"Reviews de PR"}
fmt=lambda n:f"{n:,}".replace(",",".")
# 1) top-15 labels
L=S["top15_labels_issue"][::-1]; col={"type":"#ED7D31","area":"#2E75B6","integration":"#70AD47"}
fig,ax=plt.subplots(figsize=(16,9),dpi=120)
ax.barh([k for k,_ in L],[v for _,v in L],color=[col[k.split(":")[0]] for k,_ in L])
for i,(k,v) in enumerate(L): ax.text(v+30,i,fmt(v),va="center",fontsize=17)
ax.set_title("Labels mais frequentes nas 7.381 issues indexadas"); ax.set_xlabel("issues com a label")
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=col["type"],label="type:"),Patch(color=col["area"],label="area:")],loc="lower right",frameon=False)
ax.tick_params(axis="y",labelsize=18); ax.set_xlim(0,max(v for _,v in L)*1.12)
ax.text(0.98,0.30,"integration: é rara:\na mais comum (github)\ntem só 25 issues",transform=ax.transAxes,ha="right",fontsize=17,color="#555")
fig.tight_layout(); fig.savefig(O+"grafico1_top15_labels.png"); plt.close(fig)
# 2) issues por mês com corte
m=S["issues_por_mes"]; xs=[dt.datetime.strptime(k,"%Y-%m") for k in m]; ys=list(m.values())
T=dt.datetime(2026,4,22)
fig,ax=plt.subplots(figsize=(16,9),dpi=120)
ax.bar(xs,ys,width=25,color=["#2E75B6" if x<dt.datetime(2026,4,1) else ("#9DC3E6" if x<dt.datetime(2026,5,1) else "#C00000") for x in xs])
ax.axvline(T,color="#C00000",lw=3,ls="--"); ax.text(T-dt.timedelta(days=15),max(ys)*1.06,"corte T = 22/04/2026",color="#C00000",fontsize=20,va="bottom",ha="right",fontweight="bold")
ax.text(dt.datetime(2021,1,1),max(ys)*0.97,"antes de T → índice (histórico)",fontsize=18,color="#2E75B6",va="top")
ax.text(T+dt.timedelta(days=200),max(ys)*0.75,"depois de T\n→ testset",fontsize=18,color="#C00000",va="top",ha="center")
ax.set_title("Issues abertas por mês no backstage/backstage"); ax.set_ylabel("issues criadas")
ax.xaxis.set_major_locator(mdates.YearLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.set_ylim(0,max(ys)*1.15); ax.set_xlim(dt.datetime(2019,12,1),dt.datetime(2027,6,1))
fig.text(0.99,0.01,f"Issues de pessoas ({fmt(S['issues_brutas']-S['issues_brutas_bots'])} de {fmt(S['issues_brutas'])}; sem {S['issues_brutas_bots']} de bots), fev/2020 a out/2026. Abr/2026 (azul-claro) tem dias antes e depois do corte.",ha="right",fontsize=14,color="#555")
fig.tight_layout(); fig.savefig(O+"grafico2_issues_por_mes.png"); plt.close(fig)
# 3) chunks por índice (empilhado)
ch=S["chunks"]; idx=[("base",ch["base"]),("enxuto\n(sem comentários)",ch["enxuto"]),("lógico\n(corte por estrutura)",ch["logico"]),("base + extras",ch["base_extras"])]
order=["issue","pr","doc","adr","review","commit","changelog"]
fig,ax=plt.subplots(figsize=(16,9),dpi=120)
left=[0]*len(idx)
for t in order:
    v=[d.get(t,0) for _,d in idx]
    if not any(v): continue
    ax.barh([n for n,_ in idx][::-1],v[::-1],left=left[::-1],color=C[t],label=PT[t])
    left=[a+b for a,b in zip(left,v)]
for i,(n,d) in enumerate(idx[::-1]): ax.text(sum(v for k,v in d.items())+1000,i,fmt(sum(d.values())),va="center",fontsize=20,fontweight="bold")
ax.set_title("Chunks por variante de índice"); ax.set_xlabel("chunks"); ax.set_xlim(0,128000)
ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x,_:fmt(int(x))))
ax.legend(loc="upper center",bbox_to_anchor=(0.45,-0.13),frameon=False,fontsize=17,ncol=7,handlelength=1.2,columnspacing=1.0)
fig.tight_layout(); fig.savefig(O+"grafico3_chunks_por_indice.png"); plt.close(fig)
# 4) mix de tipos: documentos x chunks (base)
dd=S["documentos_indexados"]; cc=ch["base"]
fig,axs=plt.subplots(1,2,figsize=(16,9),dpi=120)
for ax,data,title in ((axs[0],dd,f"Documentos ({fmt(sum(dd.values()))})"),(axs[1],cc,f"Chunks do índice base ({fmt(sum(cc.values()))})")):
    ks=["issue","pr","doc","adr"]; vs=[data[k] for k in ks]
    w,_=ax.pie(vs,colors=[C[k] for k in ks],startangle=90,counterclock=False,wedgeprops=dict(width=0.42,edgecolor="white"))
    ax.set_title(title,fontsize=24)
    tot=sum(vs)
    ax.legend(w,[f"{PT[k]}: {fmt(v)} ({100*v/tot:.1f}%)".replace(".",",",1) if False else f"{PT[k]}: {fmt(v)} ({str(round(100*v/tot,1)).replace('.',',')}%)" for k,v in zip(ks,vs)],loc="upper center",bbox_to_anchor=(0.5,0.02),frameon=False,fontsize=17)
fig.suptitle("Mix de fontes indexadas (antes de T)",fontsize=28,fontweight="bold")
fig.tight_layout(rect=(0,0.05,1,0.95)); fig.savefig(O+"grafico4_mix_tipos.png"); plt.close(fig)
print("ok")
