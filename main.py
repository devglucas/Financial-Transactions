"""
Orquestrador do fechamento financeiro.

    extração -> limpeza -> controles dos extratos -> classificação
             -> conciliação -> caixa -> auditoria -> validação
             -> avaliação -> exportação, relatório e gráficos

Uso:
    python main.py
"""

from __future__ import annotations

import time

import pandas as pd

from src.anomalies import detectar_anomalias
from src.cashflow import analisar_caixa
from src.classify import classificar_movimentos
from src.clean import limpar_contrapartes, limpar_movimentos, limpar_ptax, limpar_titulos
from src.evaluate import avaliar
from src.extract import extrair_dados
from src.load import exportar_dados, exportar_relatorios
from src.reconcile import conciliar
from src.report import gerar_relatorio, tabelas_resumo
from src.source_checks import conferir_saldo_corrido, conferir_trailer, lancamentos_perdidos
from src.utils import configurar_logger
from src.validate import garantir_qualidade, validar
from src.visualize import gerar_graficos

log = configurar_logger("pipeline")


def executar_pipeline(exportar: bool = True) -> dict:
    inicio = time.perf_counter()

    log.info("1/8 Extração")
    dados = extrair_dados()

    log.info("2/8 Limpeza")
    movimentos, rej_mov, aberturas, _ = limpar_movimentos(dados)
    contrapartes = limpar_contrapartes(dados["contrapartes"])
    titulos, rej_titulos = limpar_titulos(dados["erp"], contrapartes)
    ptax, rej_ptax = limpar_ptax(dados["ptax"])

    log.info("3/8 Controles dos extratos")
    trailer = conferir_trailer(movimentos, rej_mov, dados["controles_gama"]["trailer"])
    quebras, resumo_saldos = conferir_saldo_corrido(movimentos, aberturas)
    perdidos = lancamentos_perdidos(quebras, trailer)

    log.info("4/8 Classificação e conciliação")
    movimentos, _ = classificar_movimentos(movimentos)
    res = conciliar(movimentos, titulos, contrapartes, ptax, perdidos)
    res.update(aberturas=aberturas, perdidos=perdidos, trailer=trailer, resumo_saldos=resumo_saldos, ptax=ptax,
               rejeitados=pd.concat([rej_mov.assign(fonte="extratos"), rej_titulos.assign(fonte="erp"),
                                     rej_ptax.assign(fonte="ptax")], ignore_index=True))

    log.info("5/8 Caixa e auditoria")
    res["caixa"] = analisar_caixa(res["movimentos"], aberturas, res["conciliacao"], res["titulos"], contrapartes)
    res["anomalias"] = detectar_anomalias(res["conciliacao"], res["titulos"], contrapartes)

    log.info("6/8 Validação")
    validacoes = validar(res)
    garantir_qualidade(validacoes)  # interrompe aqui se alguma regra crítica falhar

    log.info("7/8 Avaliação contra o gabarito")
    avaliacao = avaliar(res)

    if exportar:
        log.info("8/8 Exportação, relatório e gráficos")
        tabelas = tabelas_resumo(res)
        exportar_dados(res)
        exportar_relatorios({**tabelas, **(avaliacao or {}), "validacoes": validacoes})
        gerar_relatorio(res, tabelas, validacoes, avaliacao)
        gerar_graficos(res, tabelas)

    log.info("Pipeline concluído em %.1fs", time.perf_counter() - inicio)
    return {**res, "validacoes": validacoes, "avaliacao": avaliacao}


if __name__ == "__main__":
    executar_pipeline()
