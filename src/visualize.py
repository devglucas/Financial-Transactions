"""
Visualizações do fechamento. Cada banco tem sempre a mesma cor; textos em
tinta neutra; paleta categórica com ordem fixa (validada para daltonismo).
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from src.config import CHARTS_DIR, ROOT_DIR  # noqa: E402
from src.utils import configurar_logger, formatar_br  # noqa: E402

log = configurar_logger("visualize")

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
CINZA, CINZA_ESCURO = "#b5b3ab", "#52514e"
TINTA, TINTA_2, TINTA_3 = "#0b0b0b", "#52514e", "#898781"
GRADE, EIXO, SUPERFICIE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
BANCOS = {"alfa": ("Banco Alfa (recebimentos)", SERIES[0]), "beta": ("Banco Beta (pagamentos)", SERIES[1]),
          "gama": ("Banco Gama (câmbio)", SERIES[2])}
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
    "axes.edgecolor": EIXO, "axes.labelcolor": TINTA_2, "axes.titlecolor": TINTA,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 24,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRADE, "grid.linewidth": 0.6,
    "xtick.color": TINTA_3, "ytick.color": TINTA_3, "xtick.labelsize": 9, "ytick.labelsize": 9,
    "text.color": TINTA, "legend.frameon": False, "legend.fontsize": 9, "font.family": "sans-serif",
})


def _milhoes(v, _=None) -> str:
    return f"R$ {v / 1e6:,.1f} mi".replace(".", ",")


def _milhoes_2(v, _=None) -> str:
    return f"R$ {v / 1e6:,.2f} mi".replace(".", ",")


def _mil(v, _=None) -> str:
    return f"R$ {v / 1e3:,.0f} mil".replace(",", ".")


def _subtitulo(ax, texto: str) -> None:
    # dois "$" no mesmo texto ativam o modo fórmula do matplotlib: o cifrão precisa de escape
    ax.text(0, 1.02, texto.replace("$", r"\$"), transform=ax.transAxes, fontsize=9, color=TINTA_2, va="bottom")


def _salvar(fig, nome: str) -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(CHARTS_DIR / nome, dpi=150)
    plt.close(fig)


def _rotulo_mes(ano_mes: str) -> str:
    return MESES[int(ano_mes[5:7]) - 1]


# --------------------------------------------------------------------------- #
def grafico_saldo(saldo: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.stackplot(saldo["data"], *[saldo[b] for b in BANCOS], labels=[r for r, _ in BANCOS.values()],
                 colors=[c for _, c in BANCOS.values()], edgecolor=SUPERFICIE, linewidth=0.6)
    ax.yaxis.set_major_formatter(FuncFormatter(_milhoes))
    ax.set_xlim(saldo["data"].iat[0], saldo["data"].iat[-1])
    # DateFormatter("%b") usa o idioma do sistema; os meses em português vêm da lista MESES
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: MESES[matplotlib.dates.num2date(v).month - 1]))
    ax.set_title("Saldo diário por banco")
    _subtitulo(ax, f"Consolidado: R$ {formatar_br(float(saldo['consolidado'].iat[0]))} em 01/01 → "
                   f"R$ {formatar_br(float(saldo['consolidado'].iat[-1]))} em 31/12")
    ax.legend(loc="upper left", ncol=3)
    _salvar(fig, "01_saldo_diario.png")


def grafico_fluxo_mensal(fluxo: pd.DataFrame) -> None:
    x = np.arange(len(fluxo))
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.bar(x - 0.2, fluxo["entradas"], width=0.38, color=SERIES[0], label="Entradas", zorder=2)
    ax.bar(x + 0.2, fluxo["saidas"], width=0.38, color=SERIES[1], label="Saídas", zorder=2)
    ax.plot(x, fluxo["saldo_do_mes"], color=CINZA_ESCURO, linewidth=2, marker="o", markersize=5,
            label="Saldo do mês (entradas − saídas)", zorder=3)
    ax.axhline(0, color=EIXO, linewidth=0.8)
    ax.set_xticks(x, [_rotulo_mes(m) for m in fluxo["mes"]])
    ax.yaxis.set_major_formatter(FuncFormatter(_milhoes))
    ax.set_title("Fluxo de caixa mensal")
    _subtitulo(ax, "Sem transferências entre contas próprias e estornos")
    ax.legend(loc="upper left", ncol=3)
    _salvar(fig, "02_fluxo_mensal.png")


def grafico_conciliacao(por_regra: pd.DataFrame) -> None:
    rotulos = {"referencia_documento": "Referência (boleto, NF, invoice)", "valor_exato": "Valor exato",
               "valor_aproximado_nome": "Valor aproximado + contraparte", "cambio_ptax": "Câmbio pela PTAX"}
    dados = por_regra.set_index("regra").reindex(list(rotulos)).dropna(subset=["total"]).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 4))
    barras = ax.barh([rotulos[r] for r in dados.index], dados["total"], color=SERIES[0], height=0.6, zorder=2)
    for barra, (total, pct) in zip(barras, zip(dados["total"], dados["pct"])):
        ax.text(barra.get_width(), barra.get_y() + barra.get_height() / 2,
                f"  {formatar_br(int(total))} ({formatar_br(float(pct), 1)}%)", va="center", fontsize=8.5, color=TINTA_2)
    ax.set_xlim(0, dados["total"].max() * 1.3)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_title("Movimentos conciliados por regra")
    _subtitulo(ax, "Regras aplicadas em ordem; o que uma concilia sai da disputa das seguintes")
    _salvar(fig, "03_conciliacao_por_regra.png")


def grafico_aging(aging: pd.DataFrame) -> None:
    cores = [SERIES[0]] + [SERIES[1]] * (len(aging) - 1)   # a vencer x vencido
    fig, ax = plt.subplots(figsize=(8, 4.2))
    barras = ax.bar(aging["faixa"].astype(str), aging["valor"], color=cores, width=0.6, zorder=2)
    for barra, (valor, qtd) in zip(barras, zip(aging["valor"], aging["titulos"])):
        ax.text(barra.get_x() + barra.get_width() / 2, barra.get_height(), f"{_mil(valor)}\n{qtd} títulos",
                ha="center", va="bottom", fontsize=8.5, color=TINTA_2)
    ax.set_ylim(0, aging["valor"].max() * 1.25)
    ax.yaxis.set_major_formatter(FuncFormatter(_mil))
    ax.set_title("Carteira a receber em 31/12 por faixa de atraso")
    _subtitulo(ax, "Azul: a vencer · laranja: vencido")
    _salvar(fig, "04_aging_recebiveis.png")


def grafico_projecao(projecao: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(projecao["data"], projecao["saldo_projetado"], color=SERIES[0], linewidth=2)
    ax.fill_between(projecao["data"], projecao["saldo_projetado"].min() * 0.98, projecao["saldo_projetado"],
                    color=SERIES[0], alpha=0.08)
    ax.yaxis.set_major_formatter(FuncFormatter(_milhoes_2))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m"))
    ax.set_title(f"Projeção de caixa consolidado: próximos {len(projecao)} dias")
    _subtitulo(ax, "Saldo de 31/12 + títulos a vencer (vencidos em aberto não entram)")
    _salvar(fig, "05_projecao_caixa.png")


def grafico_benford(benford: pd.DataFrame, resumo: dict) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.bar(benford["digito"], benford["observado_pct"], color=SERIES[0], width=0.6, label="Observado", zorder=2)
    ax.plot(benford["digito"], benford["esperado_pct"], color=SERIES[1], linewidth=2, marker="o", markersize=6,
            label="Esperado (Lei de Benford)", zorder=3)
    ax.set_xticks(benford["digito"])
    ax.set_xlabel("Primeiro dígito do valor pago")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_title("Primeiro dígito dos pagamentos x Lei de Benford")
    _subtitulo(ax, f"MAD = {resumo['mad']:.4f} ({resumo['conformidade']})")
    ax.legend(loc="upper right")
    _salvar(fig, "06_benford.png")


def grafico_alertas(alertas: pd.DataFrame) -> None:
    rotulos = {"pagamento_duplicado": "Pagamento duplicado", "titulo_cancelado_pago": "Título cancelado pago",
               "fracionamento": "Fracionamento abaixo da alçada", "fornecedor_novo": "Fornecedor recém-cadastrado",
               "valor_atipico": "Valor atípico (z robusto)", "pagamento_fora_de_dia_util": "Pago fora de dia útil"}
    resumo = alertas.groupby("regra").agg(qtd=("titulo_id", "count")).reindex(list(rotulos)).fillna(0).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8.5, 4))
    barras = ax.barh([rotulos[r] for r in resumo.index], resumo["qtd"], color=SERIES[0], height=0.6, zorder=2)
    for barra, qtd in zip(barras, resumo["qtd"]):
        ax.text(barra.get_width(), barra.get_y() + barra.get_height() / 2, f"  {int(qtd)}", va="center",
                fontsize=8.5, color=TINTA_2)
    ax.set_xlim(0, resumo["qtd"].max() * 1.2)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_title("Alertas da auditoria de pagamentos")
    _subtitulo(ax, "Quantidade de títulos sinalizados por regra")
    _salvar(fig, "07_alertas_auditoria.png")


def gerar_graficos(res: dict, tabelas: dict) -> None:
    caixa, anom = res["caixa"], res["anomalias"]
    grafico_saldo(caixa["saldo_diario"])
    grafico_fluxo_mensal(caixa["fluxo_mensal"])
    grafico_conciliacao(tabelas["conciliacao_por_regra"])
    grafico_aging(caixa["aging_recebiveis"])
    grafico_projecao(caixa["projecao_caixa"])
    grafico_benford(anom["benford"], anom["benford_resumo"])
    grafico_alertas(anom["alertas"])
    log.info("7 gráficos salvos em %s", CHARTS_DIR.relative_to(ROOT_DIR))
