"""
Extração: lê cada fonte no seu formato, sem converter tipos.

Tudo vem como texto; as conversões ficam em `clean.py`. Cada linha guarda
`linha_origem` (número da linha no arquivo) para rastrear qualquer rejeição.
"""

from __future__ import annotations

import io

import pandas as pd

from src.config import ARQUIVOS_RAW
from src.utils import configurar_logger

log = configurar_logger("extract")

# Layout do arquivo de largura fixa do Banco Gama: (início, fim) de cada campo
LAYOUT_GAMA_DETALHE = {
    "data": (1, 9), "dc": (9, 10), "valor_centavos": (10, 25), "documento": (25, 35), "historico": (35, 75),
}


def ler_alfa(caminho) -> pd.DataFrame:
    """
    CSV ';' com BOM (utf-8-sig). O arquivo é a concatenação de exportações
    mensais: o cabeçalho se repete no início de cada mês e há linhas em branco.
    """
    df = pd.read_csv(caminho, sep=";", encoding="utf-8-sig", dtype="string", skip_blank_lines=False)
    df["linha_origem"] = df.index + 2
    df = df.dropna(how="all", subset=df.columns[:-1])            # linhas em branco
    df = df[df["Data"] != "Data"]                                 # cabeçalhos repetidos
    return df.rename(columns={"Data": "data", "Histórico": "historico", "Documento": "documento",
                              "Valor": "valor", "D/C": "dc", "Saldo": "saldo"})


def ler_beta(caminho) -> pd.DataFrame:
    df = pd.read_csv(caminho, dtype="string")
    df["linha_origem"] = df.index + 2
    return df.rename(columns={"date": "data", "description": "historico", "amount": "valor",
                              "balance": "saldo", "transaction_id": "documento"})


def ler_gama(caminho) -> tuple[pd.DataFrame, dict, dict]:
    """
    Largura fixa: cada campo ocupa posições fixas da linha. O 1º caractere
    indica o tipo de registro: 0 = header, 1 = movimento, 9 = trailer.
    `read_fwf` lê os detalhes; header e trailer são fatiados diretamente.
    """
    linhas = caminho.read_text(encoding="ascii").splitlines()
    header = next(l for l in linhas if l.startswith("0"))
    trailer = next(l for l in linhas if l.startswith("9"))
    numeros_detalhe = [i for i, l in enumerate(linhas, start=1) if l.startswith("1")]
    detalhes = pd.read_fwf(
        io.StringIO("\n".join(linhas[i - 1] for i in numeros_detalhe)),
        colspecs=list(LAYOUT_GAMA_DETALHE.values()), names=list(LAYOUT_GAMA_DETALHE), dtype="string", header=None,
    ).assign(linha_origem=numeros_detalhe)
    info_header = {"banco": header[1:31].strip(), "conta": header[31:43].strip(), "data_geracao": header[43:51]}
    info_trailer = {"quantidade": int(trailer[1:7]), "debitos_centavos": int(trailer[7:24]),
                    "creditos_centavos": int(trailer[24:41])}
    return detalhes, info_header, info_trailer


def ler_csv_texto(caminho, sep: str = ",") -> pd.DataFrame:
    df = pd.read_csv(caminho, sep=sep, dtype="string")
    return df.assign(linha_origem=df.index + 2)


def extrair_dados() -> dict:
    gama, header_gama, trailer_gama = ler_gama(ARQUIVOS_RAW["gama"])
    dados = {
        "alfa": ler_alfa(ARQUIVOS_RAW["alfa"]),
        "beta": ler_beta(ARQUIVOS_RAW["beta"]),
        "gama": gama,
        "erp": ler_csv_texto(ARQUIVOS_RAW["erp"]),
        "contrapartes": ler_csv_texto(ARQUIVOS_RAW["contrapartes"]),
        "ptax": ler_csv_texto(ARQUIVOS_RAW["ptax"], sep=";"),
        "controles_gama": {"header": header_gama, "trailer": trailer_gama},
    }
    for nome, df in dados.items():
        if isinstance(df, pd.DataFrame):
            log.info("%-13s %5d linhas", nome, len(df))
    return dados
