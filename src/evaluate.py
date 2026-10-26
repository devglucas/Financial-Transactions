"""
Avaliação contra o gabarito (data/external).

Em uma empresa real, o equivalente é revisar uma amostra de conciliações e
alertas. Aqui o gabarito permite medir, para cada regra:
    precisão = acertos / o que a regra apontou
    recall   = acertos / o que deveria ter sido apontado
"""

from __future__ import annotations

import pandas as pd

from src.anomalies import z_robusto
from src.config import ARQUIVOS_GABARITO
from src.utils import configurar_logger

log = configurar_logger("evaluate")

NOMES_GABARITO = {"pagamento_fim_de_semana": "pagamento_fora_de_dia_util"}


def _metricas(previstos: set, reais: set) -> dict:
    acertos = len(previstos & reais)
    return {"apontados": len(previstos), "esperados": len(reais), "acertos": acertos,
            "precisao_pct": round(acertos / len(previstos) * 100, 2) if previstos else None,
            "recall_pct": round(acertos / len(reais) * 100, 2) if reais else None}


def avaliar_conciliacao(conciliacao: pd.DataFrame, gabarito: pd.DataFrame) -> pd.DataFrame:
    real = set(zip(gabarito["banco"] + ":" + gabarito["documento"], gabarito["titulo_id"]))
    linhas = [{"regra": regra, **_metricas(set(zip(grupo["mov_id"], grupo["titulo_id"])), real)}
              for regra, grupo in conciliacao.groupby("regra", sort=False)]
    linhas.append({"regra": "TOTAL", **_metricas(set(zip(conciliacao["mov_id"], conciliacao["titulo_id"])), real)})
    tabela = pd.DataFrame(linhas)
    tabela.loc[tabela["regra"] != "TOTAL", ["esperados", "recall_pct"]] = None  # recall só faz sentido no total
    return tabela


def avaliar_anomalias(alertas: pd.DataFrame, gabarito: pd.DataFrame) -> pd.DataFrame:
    gabarito = gabarito.assign(regra=gabarito["anomalia"].replace(NOMES_GABARITO))
    regras = sorted(set(gabarito["regra"]) | set(alertas["regra"]))
    return pd.DataFrame([
        {"regra": regra, **_metricas(set(alertas.loc[alertas["regra"] == regra, "titulo_id"]),
                                     set(gabarito.loc[gabarito["regra"] == regra, "titulo_id"]))}
        for regra in regras
    ])


def curva_limiar_atipico(pagamentos: pd.DataFrame, gabarito: pd.DataFrame,
                         limiares=(2.5, 3.0, 3.5, 4.0, 5.0)) -> pd.DataFrame:
    """Precisão x recall do valor atípico conforme o limiar do z robusto."""
    z = z_robusto(pagamentos)
    reais = set(gabarito.loc[gabarito["anomalia"] == "valor_atipico", "titulo_id"])
    return pd.DataFrame([{"limiar_z": limiar, **_metricas(set(pagamentos.loc[z > limiar, "titulo_id"]), reais)}
                         for limiar in limiares])


def avaliar_controles(perdidos: pd.DataFrame, removidas: pd.DataFrame) -> pd.DataFrame:
    """As quebras de saldo encontraram as linhas que foram removidas do extrato?"""
    quebras = perdidos[perdidos["origem"] == "quebra do saldo corrido"]
    removidas_centavos = set((removidas["valor"] * 100).round().astype("int64"))
    return pd.DataFrame([{"controle": "saldo corrido do Banco Alfa",
                          **_metricas(set(quebras["valor_centavos"]), removidas_centavos)}])


def avaliar(res: dict) -> dict[str, pd.DataFrame] | None:
    if not all(caminho.exists() for caminho in ARQUIVOS_GABARITO.values()):
        log.warning("gabarito não encontrado: avaliação ignorada")
        return None
    gab_conc = pd.read_csv(ARQUIVOS_GABARITO["conciliacao"], dtype="string")
    gab_anom = pd.read_csv(ARQUIVOS_GABARITO["anomalias"], dtype="string")
    removidas = pd.read_csv(ARQUIVOS_GABARITO["linhas_removidas"])

    conciliacao = avaliar_conciliacao(res["conciliacao"], gab_conc)
    anomalias = avaliar_anomalias(res["anomalias"]["alertas"], gab_anom)
    total = conciliacao.iloc[-1]
    log.info("conciliação: precisão %.2f%% | recall %.2f%%", total["precisao_pct"], total["recall_pct"])
    return {
        "avaliacao_conciliacao": conciliacao,
        "avaliacao_anomalias": anomalias,
        "avaliacao_limiar_atipico": curva_limiar_atipico(res["anomalias"]["pagamentos"], gab_anom),
        "avaliacao_controles": avaliar_controles(res["perdidos"], removidas),
    }
