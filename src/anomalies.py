"""
Detecção de anomalias em contas a pagar (auditoria contínua).

Cada regra gera alertas explicáveis; o score soma os pesos das regras que
dispararam e prioriza a fila de revisão da auditoria.

| Regra                        | Sinal de alerta                                                   | Peso |
|------------------------------|-------------------------------------------------------------------|------|
| pagamento_duplicado          | mesmo fornecedor e valor pagos de novo em até 7 dias              | 3    |
| titulo_cancelado_pago        | o ERP diz cancelado, mas o dinheiro saiu                          | 3    |
| fracionamento                | várias notas no mesmo dia, cada uma logo abaixo da alçada         | 2    |
| fornecedor_novo              | fornecedor cadastrado há menos de 30 dias recebendo valor alto    | 2    |
| valor_atipico                | z-score robusto (mediana/MAD) do log do valor acima de 3,5        | 2    |
| pagamento_fora_de_dia_util   | pago em fim de semana ou feriado, fora da rotina da tesouraria    | 1    |

Também calcula a aderência à Lei de Benford dos valores pagos.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import (
    ALCADA_APROVACAO,
    DIAS_FORNECEDOR_NOVO,
    DIAS_PAGAMENTO_DUPLICADO,
    FERIADOS,
    LIMIAR_Z_ROBUSTO,
    MINIMO_HISTORICO_FORNECEDOR,
    VALOR_FORNECEDOR_NOVO,
)
from src.utils import configurar_logger, reais

log = configurar_logger("anomalies")

PESOS = {"pagamento_duplicado": 3, "titulo_cancelado_pago": 3, "fracionamento": 2, "fornecedor_novo": 2,
         "valor_atipico": 2, "pagamento_fora_de_dia_util": 1}


def montar_pagamentos(conciliacao: pd.DataFrame, titulos: pd.DataFrame, contrapartes: pd.DataFrame) -> pd.DataFrame:
    """Títulos a pagar que saíram do banco, com data/valor do pagamento e o cadastro do fornecedor."""
    pagos = conciliacao[conciliacao["tipo"] == "PAGAR"][["titulo_id", "mov_id", "banco", "data", "valor_movimento_centavos"]]
    return (
        pagos.merge(titulos[["titulo_id", "contraparte_id", "documento", "valor_brl_centavos", "situacao"]], on="titulo_id")
        .merge(contrapartes[["contraparte_id", "nome", "categoria", "data_cadastro"]], on="contraparte_id")
        .rename(columns={"data": "data_pagamento", "valor_brl_centavos": "valor_centavos"})
    )


# --------------------------------------------------------------------------- #
# Regras: cada uma devolve (titulo_id, detalhe) dos títulos sinalizados
# --------------------------------------------------------------------------- #
def regra_duplicado(p: pd.DataFrame) -> pd.DataFrame:
    pares = p.merge(p, on=["contraparte_id", "valor_centavos"], suffixes=("", "_anterior"))
    dias = (pares["data_pagamento"] - pares["data_pagamento_anterior"]).dt.days
    # o mais recente do par é o suspeito; empate de data desempata pelo id
    posterior = (dias > 0) | ((dias == 0) & (pares["titulo_id"] > pares["titulo_id_anterior"]))
    pares = pares[posterior & dias.le(DIAS_PAGAMENTO_DUPLICADO)]
    detalhe = ("mesmo valor do título " + pares["titulo_id_anterior"] + " (doc " + pares["documento_anterior"]
               + ") pago " + dias[pares.index].astype(str) + " dia(s) antes")
    return pd.DataFrame({"titulo_id": pares["titulo_id"], "detalhe": detalhe}).drop_duplicates("titulo_id")


def regra_cancelado_pago(p: pd.DataFrame) -> pd.DataFrame:
    sinalizados = p[p["situacao"] == "pago_mas_cancelado_no_erp"]
    return pd.DataFrame({"titulo_id": sinalizados["titulo_id"], "detalhe": "título cancelado no ERP com pagamento no banco"})


def regra_fracionamento(p: pd.DataFrame) -> pd.DataFrame:
    logo_abaixo = p["valor_centavos"].between(0.9 * ALCADA_APROVACAO, ALCADA_APROVACAO - 1)
    grupo = p[logo_abaixo].groupby(["contraparte_id", "data_pagamento"])["valor_centavos"]
    candidatos = p[logo_abaixo].assign(qtd=grupo.transform("size"), soma=grupo.transform("sum"))
    sinalizados = candidatos[(candidatos["qtd"] >= 2) & (candidatos["soma"] > ALCADA_APROVACAO)]
    detalhe = (sinalizados["qtd"].astype(str) + " notas no mesmo dia somando R$ "
               + reais(sinalizados["soma"].astype("float64")).map("{:,.2f}".format) + ", cada uma abaixo da alçada")
    return pd.DataFrame({"titulo_id": sinalizados["titulo_id"], "detalhe": detalhe})


def regra_fornecedor_novo(p: pd.DataFrame) -> pd.DataFrame:
    dias = (p["data_pagamento"] - p["data_cadastro"]).dt.days
    sinalizados = p[dias.le(DIAS_FORNECEDOR_NOVO) & p["valor_centavos"].ge(VALOR_FORNECEDOR_NOVO)]
    return pd.DataFrame({"titulo_id": sinalizados["titulo_id"],
                         "detalhe": "fornecedor cadastrado " + dias[sinalizados.index].astype(str) + " dias antes do pagamento"})


def z_robusto(p: pd.DataFrame) -> pd.Series:
    """
    z robusto = 0,6745 x (x - mediana) / MAD, calculado por fornecedor sobre o LOG
    do valor (valores financeiros são assimétricos: um valor 2x maior é comum,
    um 8x maior não). Mediana e MAD não são distorcidas pelo próprio outlier.
    """
    log_valor = np.log(p["valor_centavos"].astype("float64"))
    por_fornecedor = log_valor.groupby(p["contraparte_id"])
    mediana = por_fornecedor.transform("median")
    mad = (log_valor - mediana).abs().groupby(p["contraparte_id"]).transform("median")
    historico = por_fornecedor.transform("size")
    z = 0.6745 * (log_valor - mediana) / mad.replace(0, np.nan)  # valor fixo (aluguel): sem dispersão
    return z.where(historico >= MINIMO_HISTORICO_FORNECEDOR)


def regra_valor_atipico(p: pd.DataFrame) -> pd.DataFrame:
    z = z_robusto(p)
    sinalizados = p[z > LIMIAR_Z_ROBUSTO]
    return pd.DataFrame({"titulo_id": sinalizados["titulo_id"],
                         "detalhe": "z robusto = " + z[sinalizados.index].round(1).astype(str) + " no histórico do fornecedor"})


def regra_fora_de_dia_util(p: pd.DataFrame) -> pd.DataFrame:
    util = np.is_busday(p["data_pagamento"].values.astype("datetime64[D]"), holidays=FERIADOS.values.astype("datetime64[D]"))
    sinalizados = p[~util]
    return pd.DataFrame({"titulo_id": sinalizados["titulo_id"],
                         "detalhe": "pago em " + sinalizados["data_pagamento"].dt.day_name()})


# --------------------------------------------------------------------------- #
def benford(valores_centavos: pd.Series) -> tuple[pd.DataFrame, float, str]:
    """
    Lei de Benford: em valores financeiros "naturais", o 1º dígito é 1 em ~30% dos
    casos e 9 em ~5%. Desvios grandes indicam valores fabricados ou manipulados.
    Conformidade pelo MAD (desvio absoluto médio) com os limites de Nigrini.
    """
    reais_ = valores_centavos[valores_centavos >= 1000].astype("int64") // 100
    primeiro = reais_.astype(str).str[0].astype(int)
    observado = primeiro.value_counts(normalize=True).reindex(range(1, 10), fill_value=0)
    esperado = pd.Series(np.log10(1 + 1 / np.arange(1, 10)), index=range(1, 10))
    tabela = pd.DataFrame({"digito": range(1, 10), "observado_pct": (observado * 100).round(2).values,
                           "esperado_pct": (esperado * 100).round(2).values})
    mad = float((observado - esperado).abs().mean())
    conformidade = ("conformidade próxima" if mad < 0.006 else "conformidade aceitável" if mad < 0.012
                    else "conformidade marginal" if mad < 0.015 else "não conformidade")
    return tabela, round(mad, 4), conformidade


def detectar_anomalias(conciliacao: pd.DataFrame, titulos: pd.DataFrame, contrapartes: pd.DataFrame) -> dict:
    pagamentos = montar_pagamentos(conciliacao, titulos, contrapartes)
    regras = {
        "pagamento_duplicado": regra_duplicado, "titulo_cancelado_pago": regra_cancelado_pago,
        "fracionamento": regra_fracionamento, "fornecedor_novo": regra_fornecedor_novo,
        "valor_atipico": regra_valor_atipico, "pagamento_fora_de_dia_util": regra_fora_de_dia_util,
    }
    alertas = pd.concat([funcao(pagamentos).assign(regra=nome) for nome, funcao in regras.items()], ignore_index=True)
    alertas["peso"] = alertas["regra"].map(PESOS)

    fila = (
        alertas.groupby("titulo_id")
        .agg(score=("peso", "sum"), regras=("regra", lambda r: ", ".join(sorted(r))), detalhes=("detalhe", " | ".join))
        .join(pagamentos.set_index("titulo_id")[["nome", "categoria", "documento", "data_pagamento", "banco", "valor_centavos"]])
        .assign(valor=lambda d: reais(d["valor_centavos"].astype("float64")))
        .drop(columns="valor_centavos")
        .sort_values(["score", "valor"], ascending=False)
        .reset_index()
    )
    tabela_benford, mad, conformidade = benford(pagamentos["valor_centavos"])
    log.info("%d alertas em %d títulos | Benford: MAD %.4f (%s)", len(alertas), len(fila), mad, conformidade)
    return {"pagamentos": pagamentos, "alertas": alertas, "fila_auditoria": fila, "benford": tabela_benford,
            "benford_resumo": {"mad": mad, "conformidade": conformidade}}
