"""
Fluxo de caixa e séries temporais.

- saldo diário por banco e consolidado (dias sem movimento repetem o saldo)
- fluxo mensal de entradas e saídas, por categoria (resample + pivot_table)
- fluxo líquido móvel de 30 dias (rolling com janela de tempo)
- atraso médio de recebimento por mês
- aging da carteira a receber na data de corte (pd.cut em faixas de atraso)
- projeção de caixa pelos títulos a vencer

Transferências entre contas próprias e estornos não são entrada nem saída de
caixa da empresa: ficam fora dos fluxos (mas entram no saldo de cada banco).
"""

from __future__ import annotations

import pandas as pd

from src.config import DATA_CORTE, DATA_INICIO
from src.utils import configurar_logger, reais

log = configurar_logger("cashflow")

FORA_DO_FLUXO = ["transferencia_interna", "estornado"]
FAIXAS_AGING = ([-float("inf"), 0, 30, 60, 90, float("inf")], ["a vencer", "1-30 dias", "31-60 dias", "61-90 dias", "90+ dias"])


def saldo_diario(movimentos: pd.DataFrame, aberturas: dict) -> pd.DataFrame:
    dias = pd.date_range(DATA_INICIO, DATA_CORTE, freq="D")
    variacao = (
        movimentos.pivot_table(index="data", columns="banco", values="valor_centavos", aggfunc="sum")
        .reindex(dias, fill_value=0).fillna(0)
    )
    saldo = variacao.cumsum() + pd.Series(aberturas)
    saldo["consolidado"] = saldo.sum(axis=1)
    return reais(saldo).rename_axis(index="data", columns=None).reset_index()


def fluxo_mensal(movimentos: pd.DataFrame) -> pd.DataFrame:
    caixa = movimentos[~movimentos["categoria"].isin(FORA_DO_FLUXO)].set_index("data")
    valor = caixa["valor_centavos"].astype("float64")
    mensal = pd.DataFrame({
        "entradas": valor.clip(lower=0).resample("ME").sum(),
        "saidas": -valor.clip(upper=0).resample("ME").sum(),
    })
    mensal["saldo_do_mes"] = mensal["entradas"] - mensal["saidas"]
    mensal["acumulado"] = mensal["saldo_do_mes"].cumsum()
    mensal = reais(mensal)
    mensal.index = mensal.index.to_period("M").astype(str)
    return mensal.rename_axis("mes").reset_index()


def fluxo_por_categoria(movimentos: pd.DataFrame) -> pd.DataFrame:
    caixa = movimentos[~movimentos["categoria"].isin(FORA_DO_FLUXO)]
    tabela = caixa.pivot_table(index=caixa["data"].dt.to_period("M").astype(str), columns="categoria",
                               values="valor_centavos", aggfunc="sum", fill_value=0)
    return reais(tabela).rename_axis(index="mes", columns=None).reset_index()


def fluxo_movel_30_dias(movimentos: pd.DataFrame) -> pd.DataFrame:
    caixa = movimentos[~movimentos["categoria"].isin(FORA_DO_FLUXO)]
    diario = (caixa.groupby("data")["valor_centavos"].sum().astype("float64")
              .reindex(pd.date_range(DATA_INICIO, DATA_CORTE, freq="D"), fill_value=0))
    # "30D" = janela de 30 dias corridos, não de 30 linhas
    return reais(pd.DataFrame({"liquido_dia": diario, "liquido_30_dias": diario.rolling("30D").sum()})) \
        .rename_axis("data").reset_index()


def atraso_recebimentos(conciliacao: pd.DataFrame) -> pd.DataFrame:
    receber = conciliacao[conciliacao["tipo"] == "RECEBER"]
    mensal = receber.groupby(receber["data"].dt.to_period("M").astype(str)).agg(
        recebimentos=("titulo_id", "count"),
        atraso_medio_dias=("dias_do_vencimento", lambda d: d.clip(lower=0).mean()),
        pct_pagos_em_atraso=("dias_do_vencimento", lambda d: (d > 0).mean() * 100),
        juros_recebidos=("diferenca_centavos", lambda d: reais(d.clip(lower=0).sum())),
    )
    return mensal.round(2).rename_axis("mes").reset_index()


def aging_recebiveis(titulos: pd.DataFrame) -> pd.DataFrame:
    abertos = titulos[(titulos["tipo"] == "RECEBER") & titulos["situacao"].isin(["vencido_em_aberto", "a_vencer"])]
    dias_atraso = (DATA_CORTE - abertos["vencimento"]).dt.days
    faixa = pd.cut(dias_atraso, bins=FAIXAS_AGING[0], labels=FAIXAS_AGING[1])
    aging = abertos.groupby(faixa, observed=False).agg(titulos=("titulo_id", "count"), valor=("valor_brl_centavos", "sum"))
    aging["valor"] = reais(aging["valor"].astype("float64"))
    aging["pct_valor"] = (aging["valor"] / aging["valor"].sum() * 100).round(1)
    return aging.rename_axis("faixa").reset_index()


def maiores_devedores(titulos: pd.DataFrame, contrapartes: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    vencidos = titulos[(titulos["tipo"] == "RECEBER") & (titulos["situacao"] == "vencido_em_aberto")]
    ranking = vencidos.groupby("contraparte_id").agg(
        titulos_vencidos=("titulo_id", "count"), valor_vencido=("valor_brl_centavos", "sum"),
        vencimento_mais_antigo=("vencimento", "min"))
    ranking["valor_vencido"] = reais(ranking["valor_vencido"].astype("float64"))
    ranking = ranking.join(contrapartes.set_index("contraparte_id")["nome"])
    return ranking.sort_values("valor_vencido", ascending=False).head(n).reset_index()


def projecao_caixa(titulos: pd.DataFrame, saldo_final: float, dias: int = 40) -> pd.DataFrame:
    """
    Saldo projetado a partir do saldo consolidado do corte, somando recebimentos
    e pagamentos previstos pelos títulos A VENCER. Vencidos em aberto ficam de
    fora: não há data provável para entrarem. O horizonte (40 dias) é o que a
    carteira já emitida cobre; além dele a projeção seria uma linha reta.
    """
    a_vencer = titulos[titulos["situacao"] == "a_vencer"]
    previsto = a_vencer.assign(valor=a_vencer["valor_brl_centavos"].astype("float64") * a_vencer["sentido"])
    datas = pd.date_range(DATA_CORTE + pd.Timedelta(days=1), periods=dias, freq="D")
    diario = previsto.pivot_table(index="vencimento", columns="tipo", values="valor", aggfunc="sum") \
        .reindex(datas, fill_value=0).fillna(0)
    diario = reais(diario).rename(columns={"RECEBER": "entradas_previstas", "PAGAR": "saidas_previstas"})
    diario["saldo_projetado"] = saldo_final + diario.sum(axis=1).cumsum()
    return diario.rename_axis(index="data", columns=None).reset_index()


def analisar_caixa(movimentos, aberturas, conciliacao, titulos, contrapartes) -> dict[str, pd.DataFrame]:
    saldo = saldo_diario(movimentos, aberturas)
    resultado = {
        "saldo_diario": saldo,
        "fluxo_mensal": fluxo_mensal(movimentos),
        "fluxo_por_categoria": fluxo_por_categoria(movimentos),
        "fluxo_movel_30_dias": fluxo_movel_30_dias(movimentos),
        "atraso_recebimentos": atraso_recebimentos(conciliacao),
        "aging_recebiveis": aging_recebiveis(titulos),
        "maiores_devedores": maiores_devedores(titulos, contrapartes),
        "projecao_caixa": projecao_caixa(titulos, float(saldo["consolidado"].iat[-1])),
    }
    log.info("saldo consolidado: R$ %.2f -> R$ %.2f", saldo["consolidado"].iat[0], saldo["consolidado"].iat[-1])
    return resultado
