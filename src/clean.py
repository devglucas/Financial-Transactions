"""
Limpeza e padronização.

Saídas principais:
- movimentos: os três extratos em um esquema único, valor em centavos com sinal
  (+ crédito, - débito), na ordem cronológica em que o banco lançou
- títulos: contas a pagar e a receber do ERP, valor positivo na moeda original
- contrapartes e cotações PTAX limpas

Cada função devolve também os registros rejeitados, com motivo.
"""

from __future__ import annotations

import pandas as pd

from src.config import SALDO_ABERTURA_GAMA_CENTAVOS
from src.utils import configurar_logger, normalizar_texto, para_centavos, parse_numero, separar_rejeitados

log = configurar_logger("clean")

COLUNAS_MOVIMENTO = ["banco", "documento", "data", "historico", "valor_centavos", "saldo_informado_centavos",
                     "sequencia", "linha_origem"]

TIPOS_TITULO = {"RECEBER": "RECEBER", "A RECEBER": "RECEBER", "R": "RECEBER",
                "PAGAR": "PAGAR", "A PAGAR": "PAGAR", "P": "PAGAR"}
STATUS_TITULO = {"PAGO": "PAGO", "LIQUIDADO": "PAGO", "ABERTO": "ABERTO", "EM ABERTO": "ABERTO",
                 "CANCELADO": "CANCELADO"}
MOEDAS = {"BRL": "BRL", "R$": "BRL", "USD": "USD", "US$": "USD", "DOLAR": "USD", "EUR": "EUR", "€": "EUR",
          "EURO": "EUR"}


def _parse_data(serie: pd.Series, formatos: list[str]) -> pd.Series:
    texto = serie.astype("string").str.strip()
    resultado = pd.to_datetime(texto, format=formatos[0], errors="coerce")
    for formato in formatos[1:]:
        resultado = resultado.fillna(pd.to_datetime(texto, format=formato, errors="coerce"))
    return resultado


# --------------------------------------------------------------------------- #
# Extratos
# --------------------------------------------------------------------------- #
def limpar_alfa(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Devolve (movimentos, saldos anteriores mensais, saldo de abertura em centavos)."""
    df = df.assign(data=_parse_data(df["data"], ["%d/%m/%Y"]),
                   saldo_informado_centavos=para_centavos(parse_numero(df["saldo"])))
    saldo_anterior = df["historico"].eq("SALDO ANTERIOR")
    saldos_mensais = df.loc[saldo_anterior, ["data", "saldo_informado_centavos", "linha_origem"]]
    mov = df.loc[~saldo_anterior]
    sinal = mov["dc"].map({"C": 1, "D": -1})
    mov = mov.assign(banco="alfa", valor_centavos=para_centavos(parse_numero(mov["valor"])) * sinal,
                     sequencia=range(len(mov)))
    return mov, saldos_mensais.reset_index(drop=True), int(saldos_mensais["saldo_informado_centavos"].iat[0])


def limpar_beta(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """
    Banco digital: exportação em ordem DECRESCENTE e com lançamentos 'pending'
    (autorizados, mas ainda não liquidados). Só 'posted' movimenta o saldo.
    """
    # ordem cronológica: data crescente; no mesmo dia, inverte a ordem do arquivo
    df = df.assign(data=_parse_data(df["data"], ["%Y-%m-%d"]), valor_centavos=para_centavos(parse_numero(df["valor"])),
                   saldo_informado_centavos=para_centavos(parse_numero(df["saldo"])))
    df = df.sort_values(["data", "linha_origem"], ascending=[True, False])

    pendentes = df["status"].ne("posted")
    confirmados = df.loc[~pendentes, ["historico", "valor_centavos", "data"]]
    gemeos = df.loc[pendentes].reset_index().merge(confirmados, on=["historico", "valor_centavos"], suffixes=("", "_posted"))
    gemeos = gemeos.loc[(gemeos["data_posted"] - gemeos["data"]).dt.days.abs() <= 2, "index"].unique()
    df, rej_gemeos = separar_rejeitados(df, pendentes & df.index.isin(gemeos), "pendente_duplicado_do_lancamento_liquidado")
    df, rej_transito = separar_rejeitados(df, df["status"].ne("posted"), "pendente_nao_liquidado")

    df = df.assign(banco="beta", sequencia=range(len(df)))
    abertura = int(df["saldo_informado_centavos"].iat[0] - df["valor_centavos"].iat[0])
    return df, pd.concat([rej_gemeos, rej_transito]), abertura


def limpar_gama(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df, rej = separar_rejeitados(df, ~df["valor_centavos"].str.fullmatch(r"\d{15}", na=False), "valor_ilegivel_no_arquivo")
    sinal = df["dc"].map({"C": 1, "D": -1})
    df = df.assign(banco="gama", data=_parse_data(df["data"], ["%d%m%Y"]),
                   valor_centavos=df["valor_centavos"].astype("Int64") * sinal,
                   saldo_informado_centavos=pd.NA, sequencia=range(len(df)))
    return df, rej


def limpar_movimentos(dados: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict, pd.DataFrame]:
    alfa, saldos_alfa, abertura_alfa = limpar_alfa(dados["alfa"])
    beta, rej_beta, abertura_beta = limpar_beta(dados["beta"])
    gama, rej_gama = limpar_gama(dados["gama"])

    movimentos = pd.concat([m[COLUNAS_MOVIMENTO] for m in (alfa, beta, gama)], ignore_index=True)
    movimentos["historico"] = normalizar_texto(movimentos["historico"])
    movimentos["saldo_informado_centavos"] = movimentos["saldo_informado_centavos"].astype("Int64")
    movimentos["mov_id"] = movimentos["banco"] + ":" + movimentos["documento"]
    movimentos, rej_dup = separar_rejeitados(movimentos, movimentos["mov_id"].duplicated(), "documento_repetido")

    rejeitados = pd.concat([rej_beta.assign(banco="beta"), rej_gama.assign(banco="gama"), rej_dup], ignore_index=True)
    aberturas = {"alfa": abertura_alfa, "beta": abertura_beta, "gama": SALDO_ABERTURA_GAMA_CENTAVOS}
    log.info("movimentos: %d (alfa %d, beta %d, gama %d) | %d rejeitados", len(movimentos), len(alfa), len(beta),
             len(gama), len(rejeitados))
    return movimentos.reset_index(drop=True), rejeitados, aberturas, saldos_alfa


# --------------------------------------------------------------------------- #
# ERP e cadastros
# --------------------------------------------------------------------------- #
def limpar_contrapartes(df: pd.DataFrame) -> pd.DataFrame:
    categoria = df["categoria"].str.strip()
    # 'MATÉRIA-PRIMA' e 'Matéria-prima' são a mesma categoria: fica a grafia mais comum
    canonica = categoria.groupby(categoria.str.lower()).transform(lambda s: s.mode().iat[0])
    return df.assign(
        nome=df["nome"].str.strip(),
        categoria=canonica,
        data_cadastro=pd.to_datetime(df["data_cadastro"], format="%Y-%m-%d"),
        nome_banco=normalizar_texto(df["nome"]).str.replace(r"[&.]", " ", regex=True).str.replace(r"\s+", " ", regex=True),
    ).drop(columns="linha_origem")


def limpar_titulos(df: pd.DataFrame, contrapartes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    moeda = normalizar_texto(df["moeda"]).map(MOEDAS)
    moeda_padrao = df["contraparte_id"].map(contrapartes.set_index("contraparte_id")["moeda_padrao"])
    df = df.assign(
        tipo=normalizar_texto(df["tipo"]).map(TIPOS_TITULO),
        status_erp=normalizar_texto(df["status"]).map(STATUS_TITULO),
        moeda=moeda.fillna(moeda_padrao),  # moeda em branco: a moeda padrão do fornecedor/cliente
        emissao=_parse_data(df["emissao"], ["%Y-%m-%d", "%d/%m/%Y"]),
        vencimento=_parse_data(df["vencimento"], ["%Y-%m-%d", "%d/%m/%Y"]),
        data_baixa=_parse_data(df["data_baixa"], ["%Y-%m-%d", "%d/%m/%Y"]),
        # o módulo de contas a pagar grava parte dos valores com sinal negativo
        valor_centavos=para_centavos(parse_numero(df["valor"]).abs()),
    ).drop(columns=["status", "valor"])

    regras = [
        (df["tipo"].isna() | df["status_erp"].isna() | df["moeda"].isna(), "dominio_invalido"),
        (df["vencimento"].isna() | df["valor_centavos"].isna() | df["valor_centavos"].le(0), "vencimento_ou_valor_invalido"),
    ]
    rejeitados = []
    for invalido, motivo in regras:
        df, rej = separar_rejeitados(df, invalido.reindex(df.index), motivo)
        rejeitados.append(rej)

    # mesmo título lançado duas vezes: mantém o que foi baixado (PAGO) ou o primeiro
    prioridade = df["status_erp"].map({"PAGO": 0, "ABERTO": 1, "CANCELADO": 2})
    df = df.assign(_prioridade=prioridade).sort_values(["_prioridade", "titulo_id"])
    chave = ["tipo", "contraparte_id", "documento", "valor_centavos"]
    df, rej_dup = separar_rejeitados(df, df.duplicated(subset=chave), "lancamento_duplicado_no_erp")
    rejeitados.append(rej_dup)

    df = df.drop(columns="_prioridade").sort_values("titulo_id").reset_index(drop=True)
    rejeitados = pd.concat(rejeitados).drop(columns="_prioridade", errors="ignore")
    log.info("títulos: %d (receber %d, pagar %d) | %d rejeitados", len(df), df["tipo"].eq("RECEBER").sum(),
             df["tipo"].eq("PAGAR").sum(), len(rejeitados))
    return df, rejeitados


def limpar_ptax(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Cotações duplicadas, zeradas ou com a vírgula no lugar errado (10x) são
    rejeitadas. O erro é detectado comparando com a mediana móvel da moeda.
    """
    df = df.assign(data=_parse_data(df["Data"], ["%d/%m/%Y"]), moeda=df["Moeda"],
                   compra=parse_numero(df["Compra"]), venda=parse_numero(df["Venda"]))
    df = df[["data", "moeda", "compra", "venda", "linha_origem"]].sort_values(["moeda", "data"])
    df, rej_dup = separar_rejeitados(df, df.duplicated(subset=["data", "moeda"]), "cotacao_duplicada")

    mediana = df.groupby("moeda")["venda"].transform(lambda s: s.rolling(7, center=True, min_periods=3).median())
    desvio = (df["venda"] / mediana - 1).abs()
    df, rej_erro = separar_rejeitados(df, df["venda"].le(0) | desvio.gt(0.2), "cotacao_implausivel")
    log.info("ptax: %d cotações válidas | %d rejeitadas", len(df), len(rej_dup) + len(rej_erro))
    return df.drop(columns="linha_origem").reset_index(drop=True), pd.concat([rej_dup, rej_erro])
