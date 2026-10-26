"""
Câmbio: valor em reais de operações em dólar e euro.

A PTAX só existe em dias úteis e o arquivo tem dias faltando. Um merge comum
por data perderia fins de semana, feriados e buracos. `merge_asof` busca, para
cada data, a ÚLTIMA cotação disponível até ela (direction="backward"), separada
por moeda (by="moeda") e com um limite de defasagem (tolerance).
"""

from __future__ import annotations

import pandas as pd

DEFASAGEM_MAXIMA = pd.Timedelta(days=7)


def cotacao_na_data(df: pd.DataFrame, ptax: pd.DataFrame, coluna_data: str) -> pd.DataFrame:
    """Acrescenta ptax_venda e data_cotacao a um DataFrame com colunas `moeda` e `coluna_data`."""
    estrangeiras = df["moeda"].ne("BRL") & df[coluna_data].notna()
    # merge_asof exige chaves do MESMO tipo (no pandas 3 há mais de um tipo de string)
    consulta = df.loc[estrangeiras, ["moeda", coluna_data]].astype({"moeda": "string"}).reset_index()
    consulta = consulta.sort_values(coluna_data)
    cotacoes = ptax[["data", "moeda", "venda"]].rename(columns={"data": "data_cotacao", "venda": "ptax_venda"})
    cotacoes = cotacoes.astype({"moeda": "string"})
    resultado = pd.merge_asof(
        consulta, cotacoes.sort_values("data_cotacao"), left_on=coluna_data, right_on="data_cotacao",
        by="moeda", direction="backward", tolerance=DEFASAGEM_MAXIMA,
    ).set_index("index")
    return df.assign(
        ptax_venda=resultado["ptax_venda"].reindex(df.index),
        data_cotacao=resultado["data_cotacao"].reindex(df.index),
    )


def valor_em_reais(titulos: pd.DataFrame, ptax: pd.DataFrame, coluna_data: str = "vencimento") -> pd.DataFrame:
    """Valor estimado do título em reais (centavos) pela PTAX de venda da data indicada."""
    df = cotacao_na_data(titulos, ptax, coluna_data)
    # centavos de dólar x (reais por dólar) = centavos de real
    em_reais = (df["valor_centavos"].astype("float64") * df["ptax_venda"]).round().astype("Int64")
    return df.assign(valor_brl_centavos=em_reais.where(df["moeda"].ne("BRL"), df["valor_centavos"]))
