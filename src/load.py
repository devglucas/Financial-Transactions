"""
Exportação dos resultados.

Valores monetários são gravados em CENTAVOS (colunas *_centavos), inteiros e
sem ambiguidade de separador decimal; os relatórios em output/ usam reais.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import PROCESSED_DIR, REPORTS_DIR, ROOT_DIR
from src.utils import configurar_logger

log = configurar_logger("load")


def salvar_csv(df: pd.DataFrame, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho, index=False, encoding="utf-8")


def exportar_dados(res: dict) -> None:
    arquivos = {
        "movimentos.csv": res["movimentos"],
        "titulos.csv": res["titulos"],
        "conciliacao.csv": res["conciliacao"],
        "rejeitados.csv": res["rejeitados"],
        "ptax_validada.csv": res["ptax"],
    }
    for nome, df in arquivos.items():
        salvar_csv(df, PROCESSED_DIR / nome)
    log.info("%d arquivos salvos em %s", len(arquivos), PROCESSED_DIR.relative_to(ROOT_DIR))


def exportar_relatorios(tabelas: dict[str, pd.DataFrame]) -> None:
    for nome, df in tabelas.items():
        salvar_csv(df, REPORTS_DIR / f"{nome}.csv")
    log.info("%d relatórios CSV salvos em %s", len(tabelas), REPORTS_DIR.relative_to(ROOT_DIR))
