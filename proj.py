import io
import os
import asyncio
import pandas as pd
import plotly.express as px
import plotly.io as pio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse
from watchfiles import awatch 
import uvicorn
from contextlib import asynccontextmanager

# Definir caminho absoluto para evitar erros de localização no Windows
CSV_FILE = os.path.abspath("dados.csv")

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

def calcular_estatisticas_completas():
    if not os.path.exists(CSV_FILE): return None
    try:
        df = pd.read_csv(CSV_FILE)
        if 'tempo_minutos' not in df.columns: return None
        col = df['tempo_minutos'].dropna()
        rol = sorted(col.tolist())
        n = len(rol)
        if n == 0: return None
        
        soma = float(sum(rol))
        media = soma / n
        desvio = float(col.std()) if n > 1 else 0.0
        
        if n % 2 != 0:
            mediana = float(rol[n // 2])
            p_mediana = f"$$Md = {mediana}$$"
        else:
            v1, v2 = float(rol[n // 2 - 1]), float(rol[n // 2])
            mediana = (v1 + v2) / 2
            p_mediana = f"$$\\frac{{{v1} + {v2}}}{{2}} = {mediana}$$"
        
        contagem = col.value_counts()
        max_f = int(contagem.max())
        modas = [float(m) for m in contagem[contagem == max_f].index.tolist()]
        cv = (desvio / media * 100) if media > 0 else 0.0
        diff_p = (abs(media - mediana) / mediana * 100) if mediana > 0 else 0.0

        # ================== DISPERSÃO ==================
        df["indice"] = range(len(df))

        scatter_fig = px.scatter(
            df,
            x="indice",
            y="tempo_minutos",
            title="Diagrama de Dispersão (Tempo de Atendimento x Ordem de Registro)",
            labels={
                "indice": "Ordem de Registro",
                "tempo_minutos": "Tempo de Atendimento (minutos)"
            },
            template="plotly_white"
        )

        scatter_html = pio.to_html(scatter_fig, full_html=False)

        correlacao = df["indice"].corr(df["tempo_minutos"])

        if correlacao > 0.3:
            tendencia = "📈 Tendência Positiva"
        elif correlacao < -0.3:
            tendencia = "📉 Tendência Negativa"
        else:
            tendencia = "➖ Tendência Nula"
        # =======================================================

        # CONFIGURAÇÃO DO HISTOGRAMA COM SOBRESCRITA DIRETA DO EIXO
        hist_fig = px.histogram(
            df,
            x="tempo_minutos",
            title="Histograma (Frequência do Tempo de Atendimento)",
            text_auto=True,
            labels={
                "tempo_minutos": "Tempo de Atendimento (minutos)"
            },
            template="plotly_white"
        )
        # Força o nome do eixo Y para 'Quantidade' independente do que o Plotly decidir
        hist_fig.update_layout(yaxis_title="Quantidade")

        return {
            "m": {"media": round(media, 2), "mediana": round(mediana, 2), "moda": modas, "cv": round(cv, 2)},
            "passos": {
                "media": f"$$\\bar{{x}} = \\frac{{{soma}}}{{{n}}} = {media:.2f}$$",
                "mediana": p_mediana,
                "moda": f"Valores: **{modas}** ({max_f}x)",
                "cv": f"$$\\%CV = \\frac{{{desvio:.2f}}}{{{media:.2f}}} \\times 100 = {cv:.2f}\\%$$",
                "assimetria": f"$$Ass. = \\frac{{|{media:.2f} - {mediana:.2f}|}}{{{mediana:.2f}}} \\times 100 = {diff_p:.1f}\\%$$"
            },
            "analise": {"diff": round(diff_p, 1), "alerta": diff_p > 10},
            "tabela": col.value_counts().sort_index().reset_index().rename(
            columns={
                col.name: "Tempo de Atendimento (minutos)",
                0: "Quantidade",
                "count": "Quantidade"
            }
            ).to_html(index=False, classes='table-style'),


            "box": pio.to_html(
                px.box(
                    df,
                    y="tempo_minutos",
                    title="Boxplot (Distribuição do Tempo de Atendimento)",
                    labels={"tempo_minutos": "Tempo de Atendimento (minutos)"},
                    template="plotly_white"
                ),
                full_html=False
            ),

            "hist": pio.to_html(hist_fig, full_html=False),

            "scatter": scatter_html,
            "tendencia": tendencia
        }
    except Exception as e:
        print(f"Erro no processamento: {e}")
        return None

async def monitorar_arquivo():
    print(f"👀 Monitor de arquivo ativo em: {CSV_FILE}")
    pasta = os.path.dirname(CSV_FILE)
    async for changes in awatch(pasta, force_polling=True):
        for change, path in changes:
            if os.path.abspath(path) == CSV_FILE:
                await asyncio.sleep(0.5)
                print("🔔 Alteração detectada! Atualizando clientes...")
                data = calcular_estatisticas_completas()
                if data:
                    await manager.broadcast(data)
                    
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w") as f: f.write("tempo_minutos\n0")
    task = asyncio.create_task(monitorar_arquivo())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

def get_layout(conteudo_inicial=""):
    html_template = """
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>Dashboard SI - Final</title>
        <script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
        <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
        <style>
            body { font-family: 'Segoe UI', sans-serif; background: #f4f7f6; padding: 20px; }
            .container { max-width: 1200px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
            .metrics-container { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 25px; }
            .metric-card { background: #fff; border: 1px solid #dee2e6; border-top: 5px solid #3498db; padding: 15px; border-radius: 8px; text-align:center; }
            .math-step { font-size: 0.85em; color: #444; background: #f9f9f9; padding: 10px; border-radius: 4px; margin-top: 10px; min-height: 80px; display:flex; align-items:center; justify-content:center; flex-direction:column; }
            .table-style { width: 100%; border-collapse: collapse; }
            .table-style th { background: #3498db; color: white; padding: 10px; }
            .table-style td { border: 1px solid #eee; padding: 8px; text-align: center; }
            .row { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-top: 20px; }
            .alert-bar { padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center; border: 1px solid #ddd; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Dashboard Estatístico Consolidado (Real-Time)</h1>
            <p id="status">Conexão: 🟠 Aguardando...</p>
            <div style="border: 2px dashed #3498db; padding: 20px; text-align: center; border-radius: 10px; background: #f0f8ff; margin-bottom: 20px;">
                <form id="uploadForm">
                    <input type="file" id="fileInput" accept=".csv" required>
                    <button type="submit" style="cursor:pointer; padding: 8px 15px; background: #3498db; color: white; border: none; border-radius: 4px;">Atualizar CSV</button>
                </form>
            </div>
            <div id="dashboard-content">REPLACE_ME</div>
        </div>
        <script>
            const ws = new WebSocket("ws://" + window.location.host + "/ws");
            ws.onmessage = function(event) {
                const d = JSON.parse(event.data);
                document.getElementById('status').innerHTML = "Conexão: 🟢 Online";
                document.getElementById('status').style.color = "green";
                const cor = !d.analise.alerta ? "#d4edda" : "#fff3cd";
                const msg = d.analise.alerta ? "⚠️ Diferença > 10%. Dados Heterogêneos." : "✅ Dados Equilibrados (" + d.analise.diff + "%).";
                
                document.getElementById('dashboard-content').innerHTML = `
                    <div class="metrics-container">
                        <div class="metric-card"><b>MÉDIA</b><br><span style="font-size:24px;">${d.m.media}</span><div class="math-step">${d.passos.media}</div></div>
                        <div class="metric-card"><b>MEDIANA</b><br><span style="font-size:24px;">${d.m.mediana}</span><div class="math-step">${d.passos.mediana}</div></div>
                        <div class="metric-card"><b>MODA</b><br><span style="font-size:24px;">${d.m.moda}</span><div class="math-step">${d.passos.moda}</div></div>
                        <div class="metric-card"><b>CV (%)</b><br><span style="font-size:24px;">${d.m.cv}%</span><div class="math-step">${d.passos.cv}</div></div>
                    </div>
                    <div class="alert-bar" style="background: ${cor};"><b>Cálculo da Assimetria:</b> ${d.passos.assimetria}<hr>${msg}</div>
                    <div class="row"><div><h3>Tabela de Frequência</h3>${d.tabela}</div><div>${d.box}</div></div>
                    <div style="margin-top:30px;">${d.hist}</div>

                    <div style="margin-top:30px;">
                        <h3>Diagrama de Dispersão</h3>
                        <p><b>Análise:</b> ${d.tendencia}</p>
                        ${d.scatter}
                    </div>
                `;
                MathJax.typesetPromise();
                const scripts = document.getElementById('dashboard-content').querySelectorAll("script");
                scripts.forEach(old => { const n = document.createElement("script"); n.text = old.text; old.parentNode.replaceChild(n, old); });
            };
            document.getElementById('uploadForm').onsubmit = async (e) => {
                e.preventDefault();
                const fd = new FormData(); fd.append("file", document.getElementById('fileInput').files[0]);
                await fetch("/upload", { method: "POST", body: fd });
            };
        </script>
    </body>
    </html>
    """
    return html_template.replace("REPLACE_ME", conteudo_inicial)

@app.get("/", response_class=HTMLResponse)
async def home():
    return get_layout("<p style='text-align:center;'>Aguardando dados...</p>")

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    contents = await file.read()
    with open(CSV_FILE, "wb") as f: f.write(contents)
    data = calcular_estatisticas_completas()
    if data: await manager.broadcast(data)
    return {"status": "ok"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        data = calcular_estatisticas_completas()
        if data: await websocket.send_json(data)
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(websocket)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)