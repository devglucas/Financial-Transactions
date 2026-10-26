"""
Controles das fontes: antes de conciliar, provar que o extrato está completo.

1. Trailer do CNAB (Banco Gama): o arquivo traz no final a quantidade de
   registros e a soma de débitos e créditos. Se a soma do que lemos não bate,
   alguma linha se perdeu, e a diferença é o valor dela.
2. Saldo corrido (Alfa e Beta): saldo de abertura + soma acumulada dos
   movimentos deve reproduzir o saldo informado em cada linha. Quando a
   diferença "salta", há um lançamento faltando logo antes; o tamanho do salto
   é o valor do lançamento perdido.
"""

from __future__ import annotations

import pandas as pd

from src.utils import configurar_logger, reais

log = configurar_logger("checks")


def conferir_trailer(movimentos: pd.DataFrame, rejeitados: pd.DataFrame, trailer: dict) -> pd.DataFrame:
    gama = movimentos[movimentos["banco"] == "gama"]
    ilegiveis = (rejeitados["motivo_rejeicao"] == "valor_ilegivel_no_arquivo").sum()
    linhas = [
        ("quantidade de registros", trailer["quantidade"], len(gama) + ilegiveis),
        ("total de débitos (centavos)", trailer["debitos_centavos"], int(-gama.loc[gama["valor_centavos"] < 0, "valor_centavos"].sum())),
        ("total de créditos (centavos)", trailer["creditos_centavos"], int(gama.loc[gama["valor_centavos"] > 0, "valor_centavos"].sum())),
    ]
    resultado = pd.DataFrame(linhas, columns=["controle", "trailer", "lido"])
    resultado["diferenca"] = resultado["trailer"] - resultado["lido"]
    for linha in resultado.query("diferenca != 0").itertuples():
        log.warning("trailer Gama: %s difere em %s", linha.controle, f"{linha.diferenca:,}")
    return resultado


def conferir_saldo_corrido(movimentos: pd.DataFrame, aberturas: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devolve (quebras encontradas, resumo de saldos por banco)."""
    quebras, resumo = [], []
    for banco, mov in movimentos.sort_values(["banco", "sequencia"]).groupby("banco", sort=False):
        calculado = aberturas[banco] + mov["valor_centavos"].cumsum()
        resumo.append({"banco": banco, "saldo_abertura": reais(aberturas[banco]),
                       "saldo_final_calculado": reais(int(calculado.iat[-1])),
                       "saldo_final_informado": reais(mov["saldo_informado_centavos"].iat[-1])
                       if mov["saldo_informado_centavos"].notna().any() else None})
        if mov["saldo_informado_centavos"].isna().all():
            continue  # o banco não informa saldo (Gama): o controle é o trailer
        diferenca = (mov["saldo_informado_centavos"] - calculado).astype("int64")
        salto = diferenca.diff().fillna(diferenca.iloc[0])
        for i in salto[salto != 0].index:
            posicao = mov.index.get_loc(i)
            quebras.append({
                "banco": banco,
                "entre_data": mov["data"].iat[posicao - 1] if posicao > 0 else None,
                "e_data": mov.at[i, "data"],
                "antes_do_movimento": mov.at[i, "mov_id"],
                "valor_faltante": reais(int(salto[i])),
            })
    quebras, resumo = pd.DataFrame(quebras), pd.DataFrame(resumo)
    resumo["diferenca"] = resumo["saldo_final_informado"] - resumo["saldo_final_calculado"]
    log.info("saldo corrido: %d quebras (possíveis lançamentos faltando no extrato)", len(quebras))
    return quebras, resumo


def lancamentos_perdidos(quebras: pd.DataFrame, trailer: pd.DataFrame) -> pd.DataFrame:
    """Junta o que os dois controles revelaram: valor (com sinal) de cada lançamento que falta."""
    perdidos = []
    if not quebras.empty:
        perdidos.append(pd.DataFrame({
            "banco": quebras["banco"], "data_aproximada": quebras["e_data"],
            "valor_centavos": (quebras["valor_faltante"] * 100).round().astype("int64"),
            "origem": "quebra do saldo corrido",
        }))
    diferencas = trailer.set_index("controle")["diferenca"]
    for controle, sinal in [("total de débitos (centavos)", -1), ("total de créditos (centavos)", 1)]:
        if diferencas.get(controle, 0):
            perdidos.append(pd.DataFrame([{"banco": "gama", "data_aproximada": pd.NaT,
                                           "valor_centavos": sinal * int(diferencas[controle]),
                                           "origem": "diferença do trailer CNAB"}]))
    return pd.concat(perdidos, ignore_index=True) if perdidos else pd.DataFrame(
        columns=["banco", "data_aproximada", "valor_centavos", "origem"])
