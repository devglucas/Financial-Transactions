"""
Conciliação bancária: liga cada recebimento/pagamento do extrato ao título do ERP.

As regras rodam da mais confiável para a menos confiável; o que uma regra
concilia sai da disputa para as seguintes. Em cada regra, os pares candidatos
são ordenados do mais evidente ao menos evidente e escolhidos 1:1 (guloso).

| Regra                  | Liga quando...                                                     |
|------------------------|--------------------------------------------------------------------|
| referencia_documento   | o histórico cita o nosso número do boleto, a NF ou a invoice       |
| valor_exato            | mesmo valor em reais, sentido certo, perto do vencimento           |
| valor_aproximado_nome  | variação típica de juros/desconto e o histórico cita a contraparte |
| cambio_ptax            | título em moeda estrangeira: valor x PTAX do dia ± spread do banco |
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import (
    DATA_CORTE,
    DESCONTO_PONTUALIDADE,
    JANELA_DIAS_ANTES_VENCIMENTO,
    JANELA_DIAS_APOS_VENCIMENTO,
    JUROS_AO_MES,
    MULTA_ATRASO,
    TOLERANCIA_CAMBIO,
    VARIACAO_MAXIMA,
    VARIACAO_MINIMA,
)
from src.fx import cotacao_na_data, valor_em_reais
from src.utils import configurar_logger, emparelhar_um_para_um

log = configurar_logger("reconcile")

REGRAS = ["referencia_documento", "valor_exato", "valor_aproximado_nome", "cambio_ptax"]


# --------------------------------------------------------------------------- #
# Preparação
# --------------------------------------------------------------------------- #
def identificar_contraparte(historicos: pd.Series, contrapartes: pd.DataFrame) -> pd.Series:
    """
    Qual contraparte o histórico cita? Os bancos truncam o nome, então basta o
    começo dele (20 caracteres). Nomes mais longos são testados primeiro para
    'MERCADO SAO JORGE' não ser confundido com 'SUPERMERCADO SAO JORGE'.
    """
    resultado = pd.Series(pd.NA, index=historicos.index, dtype="string")
    for linha in contrapartes.assign(tam=contrapartes["nome_banco"].str.len()).sort_values("tam", ascending=False).itertuples():
        trecho = linha.nome_banco[:20]
        cita = historicos.str.contains(rf"\b{trecho}", regex=True, na=False) & resultado.isna()
        resultado[cita] = linha.contraparte_id
    return resultado


def preparar_movimentos(mov: pd.DataFrame, contrapartes: pd.DataFrame) -> pd.DataFrame:
    candidatos = mov[mov["categoria"].isin(["recebimento", "pagamento"])]
    h = candidatos["historico"]
    return candidatos.assign(
        sentido=np.sign(candidatos["valor_centavos"].astype("float64")).astype(int),
        valor_abs=candidatos["valor_centavos"].abs(),
        ref_nosso_numero=h.str.extract(r"LIQUIDACAO BOLETO (\d{9})", expand=False),
        ref_nf=h.str.extract(r"\bNF (\S+)", expand=False),
        ref_invoice=h.str.extract(r"(INV-\d{4}-\d{5})", expand=False),
        contraparte_citada=identificar_contraparte(h, contrapartes),
    )


def preparar_titulos(titulos: pd.DataFrame, ptax: pd.DataFrame) -> pd.DataFrame:
    return valor_em_reais(titulos, ptax).assign(sentido=titulos["tipo"].map({"RECEBER": 1, "PAGAR": -1}))


# --------------------------------------------------------------------------- #
# Regras
# --------------------------------------------------------------------------- #
def _metricas(pares: pd.DataFrame) -> pd.DataFrame:
    dias = (pares["data"] - pares["vencimento"]).dt.days
    variacao = pares["valor_abs"].astype("float64") / pares["valor_brl_centavos"].astype("float64") - 1
    return pares.assign(dias_do_vencimento=dias, variacao=variacao)


def _na_janela(pares: pd.DataFrame) -> pd.Series:
    return pares["dias_do_vencimento"].between(-JANELA_DIAS_ANTES_VENCIMENTO, JANELA_DIAS_APOS_VENCIMENTO)


def regra_referencia(m: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    por_boleto = m.merge(t.dropna(subset=["nosso_numero"]), left_on=["ref_nosso_numero", "sentido"],
                         right_on=["nosso_numero", "sentido"])
    por_invoice = m.merge(t, left_on=["ref_invoice", "sentido"], right_on=["documento", "sentido"])
    # NF se repete entre fornecedores: exige também a contraparte citada no histórico
    por_nf = m.merge(t, left_on=["ref_nf", "contraparte_citada", "sentido"],
                     right_on=["documento", "contraparte_id", "sentido"])
    pares = _metricas(pd.concat([por_boleto, por_invoice, por_nf], ignore_index=True))
    return pares.assign(ordem=pares["dias_do_vencimento"].abs())


def regra_valor_exato(m: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    brl = t[t["moeda"] == "BRL"]
    pares = _metricas(m.merge(brl, left_on=["valor_abs", "sentido"], right_on=["valor_brl_centavos", "sentido"]))
    pares = pares[_na_janela(pares)]
    # mesma contraparte citada desempata valores repetidos (ex.: aluguel todo mês)
    citada = (pares["contraparte_citada"] == pares["contraparte_id"]).fillna(False).astype(int)
    return pares.assign(ordem=pares["dias_do_vencimento"].abs() - citada * 1000)


def residuo_contratual(pares: pd.DataFrame) -> pd.Series:
    """
    Distância relativa entre o valor pago e o valor que as condições contratuais
    preveem para aquele dia: com multa + juros pro rata (atraso) ou com desconto
    (antecipação). Quanto menor, mais provável que o pagamento seja deste título.
    """
    atraso = pares["dias_do_vencimento"].clip(lower=0)
    com_encargos = 1 + MULTA_ATRASO + JUROS_AO_MES * atraso / 30
    esperado = np.where(pares["dias_do_vencimento"] > 0, com_encargos,
                        np.where(pares["variacao"] < 0, 1 - DESCONTO_PONTUALIDADE, 1.0))
    return (pares["variacao"] + 1 - esperado).abs()


def regra_valor_aproximado(m: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    brl = t[t["moeda"] == "BRL"]
    pares = _metricas(m.merge(brl, left_on=["contraparte_citada", "sentido"], right_on=["contraparte_id", "sentido"]))
    pares = pares[_na_janela(pares) & pares["variacao"].between(VARIACAO_MINIMA, VARIACAO_MAXIMA)]
    return pares.assign(ordem=residuo_contratual(pares))


def regra_cambio(m: pd.DataFrame, t: pd.DataFrame, ptax: pd.DataFrame) -> pd.DataFrame:
    estrangeiros = t[t["moeda"] != "BRL"].drop(columns=["ptax_venda", "data_cotacao"])
    pares = m.merge(estrangeiros, left_on=["contraparte_citada", "sentido"], right_on=["contraparte_id", "sentido"])
    pares = cotacao_na_data(pares, ptax, "data")  # PTAX do dia do pagamento, não do vencimento
    pares["valor_brl_centavos"] = (pares["valor_titulo_centavos"].astype("float64") * pares["ptax_venda"]).round().astype("Int64")
    pares = _metricas(pares)
    pares = pares[_na_janela(pares) & pares["variacao"].between(-TOLERANCIA_CAMBIO, TOLERANCIA_CAMBIO)]
    # o câmbio é fechado no vencimento: a data pesa mais que a variação (que é só o spread)
    return pares.assign(ordem=pares["dias_do_vencimento"].abs() + pares["variacao"].abs())


# --------------------------------------------------------------------------- #
def classificar_diferenca(conc: pd.DataFrame) -> pd.Series:
    diferenca = conc["diferenca_centavos"]
    condicoes = [
        diferenca.eq(0),
        conc["moeda"].ne("BRL"),
        (diferenca > 0) & (conc["dias_do_vencimento"] > 0),
        (diferenca < 0) & (conc["dias_do_vencimento"] <= 0),
    ]
    return pd.Series(np.select(condicoes, ["exato", "spread_cambial", "juros_e_multa", "desconto"], default="divergente"),
                     index=conc.index)


def conciliar(mov: pd.DataFrame, titulos: pd.DataFrame, contrapartes: pd.DataFrame, ptax: pd.DataFrame,
              perdidos: pd.DataFrame | None = None) -> dict:
    m_todos = preparar_movimentos(mov, contrapartes)
    t_todos = preparar_titulos(titulos, ptax)
    # nomes explícitos antes dos merges: evita colunas ambíguas valor_centavos_x / _y
    colunas_t = ["titulo_id", "tipo", "contraparte_id", "documento", "nosso_numero", "vencimento", "moeda",
                 "valor_centavos", "valor_brl_centavos", "ptax_venda", "data_cotacao", "sentido", "status_erp"]
    colunas_m = ["mov_id", "banco", "data", "historico", "valor_centavos", "valor_abs", "sentido",
                 "ref_nosso_numero", "ref_nf", "ref_invoice", "contraparte_citada"]
    m = m_todos[colunas_m].rename(columns={"valor_centavos": "valor_mov_centavos"})
    t = t_todos[colunas_t].rename(columns={"valor_centavos": "valor_titulo_centavos"})

    escolhidos = []
    for regra in REGRAS:
        livres_m = m[~m["mov_id"].isin([e for p in escolhidos for e in p["mov_id"]])]
        livres_t = t[~t["titulo_id"].isin([e for p in escolhidos for e in p["titulo_id"]])]
        candidatos = {
            "referencia_documento": lambda: regra_referencia(livres_m, livres_t),
            "valor_exato": lambda: regra_valor_exato(livres_m, livres_t),
            "valor_aproximado_nome": lambda: regra_valor_aproximado(livres_m, livres_t),
            "cambio_ptax": lambda: regra_cambio(livres_m, livres_t, ptax),
        }[regra]()
        pares = emparelhar_um_para_um(candidatos.sort_values("ordem", kind="stable"), "mov_id", "titulo_id")
        escolhidos.append(pares.assign(regra=regra))
        log.info("%-22s %5d pares", regra, len(pares))

    conc = pd.concat(escolhidos, ignore_index=True)
    conc["diferenca_centavos"] = (conc["valor_abs"] - conc["valor_brl_centavos"]).astype("Int64")
    conc["natureza_diferenca"] = classificar_diferenca(conc)
    conc = conc[["mov_id", "titulo_id", "regra", "banco", "data", "historico", "tipo", "contraparte_id", "documento",
                 "vencimento", "moeda", "valor_titulo_centavos", "valor_brl_centavos", "valor_abs", "diferenca_centavos",
                 "variacao", "dias_do_vencimento", "natureza_diferenca", "status_erp"]] \
        .rename(columns={"valor_abs": "valor_movimento_centavos"})

    resultado = situacao(mov, t_todos, conc)
    if perdidos is not None:
        resultado["titulos"] = explicar_por_lancamentos_perdidos(resultado["titulos"], perdidos)
    return {"conciliacao": conc, **resultado}


def situacao(mov: pd.DataFrame, titulos: pd.DataFrame, conc: pd.DataFrame) -> dict:
    """Status final de cada título e de cada movimento, cruzando com o status do ERP."""
    conciliado = titulos["titulo_id"].isin(conc["titulo_id"])
    erp = titulos["status_erp"]
    condicoes = [
        conciliado & erp.eq("CANCELADO"),
        conciliado & erp.eq("ABERTO"),
        conciliado,
        erp.eq("CANCELADO"),
        erp.eq("PAGO"),
        titulos["vencimento"] <= DATA_CORTE,
    ]
    escolhas = ["pago_mas_cancelado_no_erp", "pago_sem_baixa_no_erp", "conciliado", "cancelado",
                "baixado_sem_movimento_bancario", "vencido_em_aberto"]
    titulos = titulos.assign(situacao=np.select(condicoes, escolhas, default="a_vencer"))

    movimentos = mov.assign(situacao=np.select(
        [mov["mov_id"].isin(conc["mov_id"]), mov["categoria"].isin(["recebimento", "pagamento"])],
        ["conciliado", "sem_titulo_no_erp"], default="nao_se_aplica"))
    log.info("títulos: %s", titulos["situacao"].value_counts().to_dict())
    log.info("movimentos: %s", movimentos["situacao"].value_counts().to_dict())
    return {"titulos": titulos, "movimentos": movimentos}


def explicar_por_lancamentos_perdidos(titulos: pd.DataFrame, perdidos: pd.DataFrame) -> pd.DataFrame:
    """
    Título baixado no ERP sem movimento no banco pode ser um lançamento que sumiu
    do extrato. Se o valor (com encargos/desconto) e o sentido batem com um dos
    lançamentos perdidos revelados pelos controles, a pendência está explicada.
    """
    pendentes = titulos[titulos["situacao"] == "baixado_sem_movimento_bancario"].reset_index()
    perdidos = perdidos.reset_index(names="id_perdido").rename(
        columns={"valor_centavos": "valor_perdido_centavos", "banco": "banco_perdido"})
    candidatos = pendentes.merge(perdidos, how="cross")
    sentido_ok = np.sign(candidatos["valor_perdido_centavos"]) == candidatos["sentido"]
    variacao = candidatos["valor_perdido_centavos"].abs() / candidatos["valor_brl_centavos"].astype("float64") - 1
    dias = (candidatos["data_aproximada"] - candidatos["vencimento"]).dt.days
    data_ok = candidatos["data_aproximada"].isna() | dias.between(-JANELA_DIAS_ANTES_VENCIMENTO, JANELA_DIAS_APOS_VENCIMENTO)
    candidatos = candidatos[sentido_ok & variacao.between(VARIACAO_MINIMA, VARIACAO_MAXIMA) & data_ok]
    candidatos = candidatos.assign(ordem=variacao.abs())
    explicados = emparelhar_um_para_um(candidatos.sort_values("ordem"), "titulo_id", "id_perdido")
    explicacao = explicados.set_index("titulo_id")["origem"].map(lambda o: f"lançamento faltando no extrato ({o})")
    log.info("%d de %d títulos baixados sem movimento explicados por lançamentos perdidos",
             len(explicados), len(pendentes))
    return titulos.assign(explicacao=titulos["titulo_id"].map(explicacao))
