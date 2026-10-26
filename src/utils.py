"""Funções genéricas: texto, dinheiro em centavos, datas, rejeição e formatação."""

from __future__ import annotations

import logging
import unicodedata

import numpy as np
import pandas as pd


def configurar_logger(nome: str = "pipeline") -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)-10s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(nome)


# --------------------------------------------------------------------------- #
# Texto
# --------------------------------------------------------------------------- #
def sem_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def normalizar_texto(serie: pd.Series) -> pd.Series:
    """CAIXA ALTA, sem acentos e sem espaços extras: o formato dos históricos bancários."""
    return (
        serie.astype("string").str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
        .astype("string").str.upper().str.replace(r"\s+", " ", regex=True).str.strip()
    )


# --------------------------------------------------------------------------- #
# Dinheiro
# --------------------------------------------------------------------------- #
def parse_numero(serie: pd.Series) -> pd.Series:
    """'1.234,56', '1234.56', '-1234.56' e 'R$ 10,00' -> float. Vírgula = formato brasileiro."""
    texto = serie.astype("string").str.replace(r"(?i)r\$", "", regex=True).str.replace(r"\s", "", regex=True)
    brasileiro = texto.str.contains(",", regex=False, na=False)
    texto = texto.mask(brasileiro, texto.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(texto, errors="coerce").astype("float64")


def para_centavos(valores: pd.Series) -> pd.Series:
    """
    Dinheiro é guardado em CENTAVOS (inteiro). Somar floats acumula erro:
    0.1 + 0.2 == 0.30000000000000004. Com inteiros, a soma é exata.
    """
    return (valores * 100).round().astype("Int64")


def reais(centavos) -> float | pd.Series:
    return centavos / 100


# --------------------------------------------------------------------------- #
# Rejeição e formatação
# --------------------------------------------------------------------------- #
def separar_rejeitados(df: pd.DataFrame, invalido: pd.Series, motivo: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    invalido = invalido.fillna(False).astype(bool)
    return df.loc[~invalido], df.loc[invalido].assign(motivo_rejeicao=motivo)


def formatar_br(valor, casas: int = 2) -> str:
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return ""
    if isinstance(valor, (bool, np.bool_)):
        return "sim" if valor else "não"
    if isinstance(valor, (int, np.integer)):
        return f"{valor:,}".replace(",", ".")
    if isinstance(valor, (float, np.floating)):
        return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def df_para_markdown(df: pd.DataFrame, casas: int = 2) -> str:
    cabecalho = "| " + " | ".join(map(str, df.columns)) + " |"
    separador = "|" + "|".join("---" for _ in df.columns) + "|"
    linhas = [
        "| " + " | ".join("" if pd.isna(v) else formatar_br(v, casas) for v in linha) + " |"
        for linha in df.itertuples(index=False)
    ]
    return "\n".join([cabecalho, separador, *linhas])
