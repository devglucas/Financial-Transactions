"""Tabelas-resumo do fechamento e relatório em Markdown (output/relatorio.md)."""

from __future__ import annotations

import pandas as pd

from src.config import OUTPUT_DIR
from src.utils import configurar_logger, df_para_markdown, formatar_br, reais

log = configurar_logger("report")

ROTULO_SITUACAO = {
    "conciliado": "Conciliado", "pago_sem_baixa_no_erp": "Pago no banco, sem baixa no ERP",
    "pago_mas_cancelado_no_erp": "Pago no banco, mas cancelado no ERP",
    "baixado_sem_movimento_bancario": "Baixado no ERP, sem movimento no banco",
    "vencido_em_aberto": "Vencido em aberto", "a_vencer": "A vencer", "cancelado": "Cancelado",
}


def tabelas_resumo(res: dict) -> dict[str, pd.DataFrame]:
    mov, titulos, conc = res["movimentos"], res["titulos"], res["conciliacao"]

    conciliaveis = mov[mov["categoria"].isin(["recebimento", "pagamento"])]
    por_banco = conciliaveis.groupby("banco").agg(
        movimentos=("mov_id", "count"), conciliados=("situacao", lambda s: s.eq("conciliado").sum()),
        valor_total=("valor_centavos", lambda v: reais(v.abs().sum())))
    por_banco["taxa_conciliacao_pct"] = (por_banco["conciliados"] / por_banco["movimentos"] * 100).round(2)

    por_regra = conc.pivot_table(index="regra", columns="natureza_diferenca", values="mov_id", aggfunc="count",
                                 fill_value=0)
    por_regra["total"] = por_regra.sum(axis=1)
    por_regra["pct"] = (por_regra["total"] / por_regra["total"].sum() * 100).round(1)

    situacao = titulos.pivot_table(index="situacao", columns="tipo", values="valor_brl_centavos",
                                   aggfunc=["count", "sum"], fill_value=0)
    situacao.columns = [f"{'qtd' if a == 'count' else 'valor'}_{t.lower()}" for a, t in situacao.columns]
    for coluna in [c for c in situacao.columns if c.startswith("valor_")]:
        situacao[coluna] = reais(situacao[coluna].astype("float64"))
    situacao = situacao.rename(index=ROTULO_SITUACAO)

    encargos = (
        conc[conc["natureza_diferenca"] != "exato"]
        .groupby(["tipo", "natureza_diferenca"])
        .agg(ocorrencias=("mov_id", "count"), valor=("diferenca_centavos", lambda d: reais(d.sum())))
        .reset_index()
    )

    pendencias = titulos[titulos["situacao"].isin(["pago_sem_baixa_no_erp", "pago_mas_cancelado_no_erp",
                                                   "baixado_sem_movimento_bancario"])]
    pendencias = pendencias[["titulo_id", "tipo", "contraparte_id", "documento", "vencimento", "moeda",
                             "valor_centavos", "status_erp", "situacao", "explicacao"]].assign(
        valor=lambda d: reais(d["valor_centavos"].astype("float64"))).drop(columns="valor_centavos")

    anom = res["anomalias"]
    return {
        "conciliacao_por_banco": por_banco.reset_index(),
        "conciliacao_por_regra": por_regra.rename_axis(columns=None).reset_index(),
        "situacao_titulos": situacao.reset_index(),
        "encargos_e_descontos": encargos,
        "pendencias_erp": pendencias,
        "fila_auditoria": anom["fila_auditoria"],
        "alertas_auditoria": anom["alertas"],
        "benford": anom["benford"],
        "controle_trailer_gama": res["trailer"],
        "controle_saldo_corrido": res["resumo_saldos"],
        "lancamentos_faltando_no_extrato": res["perdidos"].assign(
            valor=lambda d: reais(d["valor_centavos"].astype("float64"))).drop(columns="valor_centavos"),
        **res["caixa"],
    }


def gerar_relatorio(res: dict, tabelas: dict, validacoes: pd.DataFrame, avaliacao: dict | None) -> None:
    saldo = res["caixa"]["saldo_diario"]
    fluxo = res["caixa"]["fluxo_mensal"]
    total_conc = tabelas["conciliacao_por_banco"]
    benford = res["anomalias"]["benford_resumo"]
    resumo = pd.DataFrame([
        ("Saldo consolidado em 01/01", f"R$ {formatar_br(float(saldo['consolidado'].iat[0]))}"),
        ("Saldo consolidado em 31/12", f"R$ {formatar_br(float(saldo['consolidado'].iat[-1]))}"),
        ("Entradas de caixa no ano", f"R$ {formatar_br(float(fluxo['entradas'].sum()))}"),
        ("Saídas de caixa no ano", f"R$ {formatar_br(float(fluxo['saidas'].sum()))}"),
        ("Movimentos conciliados", f"{formatar_br(int(total_conc['conciliados'].sum()))} de "
                                   f"{formatar_br(int(total_conc['movimentos'].sum()))}"),
        ("Lançamentos faltando nos extratos", formatar_br(len(res["perdidos"]))),
        ("Pagamentos na fila da auditoria", formatar_br(len(res["anomalias"]["fila_auditoria"]))),
        ("Lei de Benford (MAD)", f"{benford['mad']:.4f} - {benford['conformidade']}"),
    ], columns=["Indicador", "Valor"])

    partes = [
        "# Fechamento financeiro 2025\n", "_Gerado automaticamente por `python main.py`._\n",
        "## 1. Resumo\n", df_para_markdown(resumo) + "\n",
        "## 2. Controles dos extratos\n",
        "### Trailer do arquivo CNAB (Banco Gama)\n", df_para_markdown(res["trailer"], casas=0) + "\n",
        "### Saldo corrido\n", df_para_markdown(res["resumo_saldos"]) + "\n",
        "### Lançamentos faltando\n", df_para_markdown(tabelas["lancamentos_faltando_no_extrato"]) + "\n",
        "## 3. Conciliação bancária\n", "![Conciliação](charts/03_conciliacao_por_regra.png)\n",
        df_para_markdown(tabelas["conciliacao_por_banco"]) + "\n",
        df_para_markdown(tabelas["conciliacao_por_regra"]) + "\n",
        "### Situação dos títulos\n", df_para_markdown(tabelas["situacao_titulos"]) + "\n",
        "### Encargos, descontos e spread cambial\n", df_para_markdown(tabelas["encargos_e_descontos"]) + "\n",
        "### Pendências com o ERP\n", df_para_markdown(tabelas["pendencias_erp"]) + "\n",
        "## 4. Caixa\n", "![Saldo diário](charts/01_saldo_diario.png)\n", "![Fluxo mensal](charts/02_fluxo_mensal.png)\n",
        df_para_markdown(res["caixa"]["fluxo_mensal"]) + "\n",
        "### Atraso de recebimento\n", df_para_markdown(res["caixa"]["atraso_recebimentos"]) + "\n",
        "### Aging da carteira a receber em 31/12\n", "![Aging](charts/04_aging_recebiveis.png)\n",
        df_para_markdown(res["caixa"]["aging_recebiveis"]) + "\n",
        df_para_markdown(res["caixa"]["maiores_devedores"]) + "\n",
        "### Projeção de caixa (40 dias)\n", "![Projeção](charts/05_projecao_caixa.png)\n",
        "## 5. Auditoria de pagamentos\n", "![Alertas](charts/07_alertas_auditoria.png)\n",
        df_para_markdown(res["anomalias"]["fila_auditoria"]) + "\n",
        "### Lei de Benford\n", "![Benford](charts/06_benford.png)\n", df_para_markdown(res["anomalias"]["benford"]) + "\n",
    ]
    if avaliacao is not None:
        partes += ["## 6. Avaliação contra o gabarito\n"] + [
            f"### {nome.replace('avaliacao_', '').replace('_', ' ').capitalize()}\n" + df_para_markdown(df) + "\n"
            for nome, df in avaliacao.items()
        ]
    partes += ["## 7. Validações\n", df_para_markdown(validacoes) + "\n"]

    caminho = OUTPUT_DIR / "relatorio.md"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(partes), encoding="utf-8")
    log.info("relatório salvo em output/%s", caminho.name)
