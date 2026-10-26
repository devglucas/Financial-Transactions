"""
Classificação dos movimentos bancários antes da conciliação.

Nem todo movimento tem um título no ERP. Tarifas, impostos, folha, rendimentos,
transferências entre as contas da própria empresa e estornos são identificados
aqui para não poluírem a conciliação nem os indicadores de caixa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import DIAS_ESTORNO, DIAS_UTEIS_TRANSFERENCIA, FERIADOS, NOME_EMPRESA_NO_BANCO
from src.utils import configurar_logger, dias_uteis_entre, emparelhar_um_para_um

log = configurar_logger("classify")

# A ordem importa: a primeira regra que casar define a categoria.
REGRAS_HISTORICO = [
    (rf"^TED (?:ENVIADA|RECEBIDA) {NOME_EMPRESA_NO_BANCO}", "transferencia_interna"),
    (r"^TARIFA", "tarifa"),
    (r"^(?:IOF|DARF|GPS)\b", "imposto"),
    (r"^FOLHA", "folha"),
    (r"^REND", "rendimento"),
    (r"DEVOLVID|ESTORNO", "devolucao"),
]


def classificar(movimentos: pd.DataFrame) -> pd.Series:
    condicoes = [movimentos["historico"].str.contains(regex, regex=True, na=False) for regex, _ in REGRAS_HISTORICO]
    padrao = np.where(movimentos["valor_centavos"] > 0, "recebimento", "pagamento")
    return pd.Series(np.select(condicoes, [c for _, c in REGRAS_HISTORICO], default=padrao), index=movimentos.index)


def parear_transferencias(mov: pd.DataFrame) -> pd.DataFrame:
    """Saída de uma conta própria + entrada em outra, mesmo valor, em até D+2 úteis."""
    internas = mov[mov["categoria"] == "transferencia_interna"]
    saidas = internas[internas["valor_centavos"] < 0].assign(valor=lambda d: -d["valor_centavos"])
    entradas = internas[internas["valor_centavos"] > 0].assign(valor=lambda d: d["valor_centavos"])
    candidatos = saidas.merge(entradas, on="valor", suffixes=("_saida", "_entrada"))
    # sexta -> segunda é D+1 útil (3 dias corridos): o prazo é contado em dias úteis
    defasagem = dias_uteis_entre(candidatos["data_saida"], candidatos["data_entrada"], FERIADOS)
    candidatos = candidatos[(candidatos["banco_saida"] != candidatos["banco_entrada"])
                            & defasagem.between(0, DIAS_UTEIS_TRANSFERENCIA)]
    candidatos = candidatos.assign(defasagem=defasagem).sort_values(["defasagem", "data_saida"])
    return emparelhar_um_para_um(candidatos, "mov_id_saida", "mov_id_entrada")


def parear_estornos(mov: pd.DataFrame) -> pd.DataFrame:
    """'PIX DEVOLVIDO X' anula um 'PIX ENVIADO X' de mesmo valor, na mesma conta, dias antes."""
    devolucoes = mov[mov["categoria"] == "devolucao"].assign(
        favorecido=lambda d: d["historico"].str.replace(r"^.*DEVOLVID[OA]\s*", "", regex=True))
    envios = mov[mov["categoria"] == "pagamento"].assign(
        favorecido=lambda d: d["historico"].str.replace(r"^PIX ENVIADO\s*", "", regex=True),
        valor_centavos=lambda d: -d["valor_centavos"])
    candidatos = devolucoes.merge(envios, on=["banco", "favorecido", "valor_centavos"], suffixes=("_devolucao", "_envio"))
    dias = (candidatos["data_devolucao"] - candidatos["data_envio"]).dt.days
    # a devolução sempre vem DEPOIS do envio na sequência do banco; fica o envio anterior mais próximo
    distancia = candidatos["sequencia_devolucao"] - candidatos["sequencia_envio"]
    candidatos = candidatos[dias.between(0, DIAS_ESTORNO) & (distancia > 0)].assign(distancia=distancia)
    candidatos = candidatos.sort_values("distancia")
    return emparelhar_um_para_um(candidatos, "mov_id_devolucao", "mov_id_envio")


def classificar_movimentos(movimentos: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devolve (movimentos com categoria e par, pares de transferência)."""
    mov = movimentos.assign(categoria=classificar(movimentos), par_mov_id=pd.NA)

    transferencias = parear_transferencias(mov)
    estornos = parear_estornos(mov)
    for a, b in [("mov_id_saida", "mov_id_entrada"), ("mov_id_devolucao", "mov_id_envio")]:
        pares = transferencias if a == "mov_id_saida" else estornos
        ligacao = pd.concat([pares.set_index(a)[b], pares.set_index(b)[a]])
        mov["par_mov_id"] = mov["par_mov_id"].fillna(mov["mov_id"].map(ligacao))
    mov.loc[mov["mov_id"].isin(estornos["mov_id_envio"]) | mov["mov_id"].isin(estornos["mov_id_devolucao"]),
            "categoria"] = "estornado"

    sem_par = mov["categoria"].eq("transferencia_interna") & mov["par_mov_id"].isna()
    log.info("categorias: %s", mov["categoria"].value_counts().to_dict())
    log.info("%d transferências pareadas | %d sem par | %d estornos", len(transferencias), sem_par.sum(), len(estornos))
    return mov, transferencias
