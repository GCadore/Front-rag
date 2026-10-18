import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
plt.rcParams["font.family"]="DejaVu Sans"
fig,ax=plt.subplots(figsize=(16,9),dpi=120); ax.set_xlim(0,16); ax.set_ylim(0,9); ax.axis("off")
def box(x,y,w,h,title,body,fc,ec):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0.02,rounding_size=0.18",fc=fc,ec=ec,lw=2.2))
    ax.text(x+w/2,y+h-0.32,title,ha="center",va="top",fontsize=15,weight="bold",color="#1b1b1b")
    ax.text(x+w/2,y+h-0.85,body,ha="center",va="top",fontsize=12,color="#333",linespacing=1.3)
def arrow(a,b,label=None,ls="-",lx=0,ly=0.22,rad=0):
    ax.add_patch(FancyArrowPatch(a,b,arrowstyle="-|>",mutation_scale=24,lw=2.2,color="#555",ls=ls,connectionstyle=f"arc3,rad={rad}"))
    if label: ax.text((a[0]+b[0])/2+lx,(a[1]+b[1])/2+ly,label,ha="center",fontsize=11.5,color="#444",style="italic")
ax.text(8,8.65,"Arquitetura: RAG para triagem de issues do Backstage",ha="center",fontsize=24,weight="bold")
# faixas
ax.add_patch(FancyBboxPatch((0.25,5.35),15.5,2.85,boxstyle="round,pad=0,rounding_size=0.2",fc="#f3f6fa",ec="#c9d3e0",lw=1.2))
ax.add_patch(FancyBboxPatch((0.25,0.2),15.5,4.9,boxstyle="round,pad=0,rounding_size=0.2",fc="#fbf7f1",ec="#e3d6c3",lw=1.2))
ax.text(0.45,7.95,"OFFLINE: preparação da base",fontsize=13,weight="bold",color="#4a6382")
ax.text(0.45,4.85,"ONLINE: triagem de uma issue nova",fontsize=13,weight="bold",color="#8a6a3d")
B="#dbe8f7";Be="#3b6ea8"; G="#e2f1df";Ge="#4b8b3b"; O="#fde9d4";Oe="#c47a2c"; P="#ece3f5";Pe="#7a52a8"
box(0.5,5.6,3.4,2.1,"Dados do GitHub","backstage/backstage\n7.381 issues · 12.112 PRs\n424 docs · 15 ADRs",B,Be)
box(4.4,5.6,3.4,2.1,"Coleta + limpeza","remove bots e templates\ncorte T = 22/04/2026\n(sem vazamento)",B,Be)
box(8.3,5.6,3.4,2.1,"Indexação (GPU)","embeddings BGE-M3\n+ BM25 (léxico), no Modal\nchunking por variante",B,Be)
box(12.2,5.6,3.4,2.1,"Modal Volume","Chroma (chunks):\nbase 39.180 · enxuto 28.813\nlógico 41.841\nbase+extras 107.928",G,Ge)
arrow((3.9,6.65),(4.4,6.65)); arrow((7.8,6.65),(8.3,6.65)); arrow((11.7,6.65),(12.2,6.65))
box(0.6,2.0,2.6,2.4,"Front Next.js","usuário cola\ntítulo + corpo\nda issue nova",O,Oe)
box(4.25,0.9,4.3,3.5,"Backend FastAPI · Modal L4","busca híbrida denso+BM25\nRRF (peso 0,8; k = 30)\nsplit 6 issues + 4 docs (lógico)\nlabels dos vizinhos (até 5)\n+ descrições dos labels\nmonta prompt com CONTEXTO [1..k]",O,Oe)
box(9.2,2.85,3.2,1.55,"LLM","Qwen3.5-9B\nvLLM no Modal (A10G)",P,Pe)
box(9.2,0.9,3.2,1.75,"Guardrails","schema JSON\nlabels permitidas\ncitações só do contexto",O,Oe)
box(12.95,0.9,2.7,3.5,"Saída (JSON)","labels + confiança\nrelated (issues/PRs)\ndocs\nexplicação com [n]\nneeds_more_info",G,Ge)
arrow((3.2,3.2),(4.25,3.2),"POST /triage",ly=0.15)
arrow((8.55,3.6),(9.2,3.6))
arrow((10.8,2.85),(10.8,2.65))
arrow((12.4,1.7),(12.95,1.7))
ax.plot([14.3,14.3,1.9],[0.9,0.5,0.5],color="#555",lw=2.2,ls="--")
arrow((1.9,0.5),(1.9,2.0),ls="--")
ax.text(8,0.58,"resposta exibida no front",ha="center",fontsize=11.5,color="#444",style="italic",bbox=dict(fc="#fbf7f1",ec="none",pad=1))
arrow((13.9,5.6),(6.4,4.4),"leitura dos índices",ls="--",lx=0.8,ly=0.12)
fig.savefig("/workspace/apresentacao/arquitetura.png",bbox_inches="tight",facecolor="white")
