"""
Validação final do fechamento.

- "critica": interrompe o pipeline (os números não podem ser publicados)
- "alerta":  pendência operacional que o financeiro precisa tratar
"""

from __future__ import annotations

import pandas as pd

from src.utils import configurar_logger

log = configurar_logger("validate")


class ErroDeValidacao(Exception):
    pass


def _regra(r: list, tabela: str, regra: str, falhas, severidade: str = "critica") -> None:
    qtd = int(falhas.sum()) if isinstance(falhas, pd.Series) else int(falhas)
    r.append({"tabela": tabela, "regra": regra, "severidade": severidade, "ocorrencias": qtd, "passou": qtd == 0})


def validar(res: dict) -> pd.DataFrame:
    mov, titulos, conc = res["movimentos"], res["titulos"], res["conciliacao"]
    r: list[dict] = []

    _regra(r, "movimentos", "mov_id único", mov["mov_id"].duplicated())
    _regra(r, "movimentos", "valor preenchido e diferente de zero", mov["valor_centavos"].isna() | mov["valor_centavos"].eq(0))
    _regra(r, "movimentos", "todo movimento classificado", mov["categoria"].isna())
    _regra(r, "títulos", "titulo_id único", titulos["titulo_id"].duplicated())
    _regra(r, "títulos", "valor positivo", ~titulos["valor_centavos"].gt(0))
    _regra(r, "títulos", "título em moeda estrangeira tem cotação",
           titulos["moeda"].ne("BRL") & titulos["valor_brl_centavos"].isna())

    _regra(r, "conciliação", "cada movimento ligado a no máximo um título", conc["mov_id"].duplicated())
    _regra(r, "conciliação", "cada título ligado a no máximo um movimento", conc["titulo_id"].duplicated())
    sinal = conc["mov_id"].map(mov.set_index("mov_id")["valor_centavos"]).astype("float64")
    _regra(r, "conciliação", "recebimento só com crédito e pagamento só com débito",
           (conc["tipo"].eq("RECEBER") & sinal.lt(0)) | (conc["tipo"].eq("PAGAR") & sinal.gt(0)))
    _regra(r, "conciliação", "só recebimentos/pagamentos são conciliados",
           ~conc["mov_id"].map(mov.set_index("mov_id")["categoria"]).isin(["recebimento", "pagamento"]))

    internas = mov[mov["categoria"].eq("transferencia_interna") & mov["par_mov_id"].notna()]
    _regra(r, "movimentos", "transferências internas pareadas somam zero", internas["valor_centavos"].sum() != 0)
    saldo_final = res["caixa"]["saldo_diario"].iloc[-1]
    for banco, abertura in res["aberturas"].items():
        calculado = (abertura + mov.loc[mov["banco"] == banco, "valor_centavos"].sum()) / 100
        _regra(r, "caixa", f"saldo final {banco} = abertura + movimentos", abs(saldo_final[banco] - calculado) > 0.005)

    # alertas: pendências do financeiro
    _regra(r, "extratos", "lançamentos faltando no extrato (saldo corrido/trailer)", len(res["perdidos"]), "alerta")
    _regra(r, "movimentos", "transferência interna sem contrapartida",
           mov["categoria"].eq("transferencia_interna") & mov["par_mov_id"].isna(), "alerta")
    _regra(r, "movimentos", "recebimento/pagamento sem título no ERP", mov["situacao"].eq("sem_titulo_no_erp"), "alerta")
    _regra(r, "conciliação", "diferença de valor sem explicação", conc["natureza_diferenca"].eq("divergente"), "alerta")
    _regra(r, "títulos", "pago no banco sem baixa no ERP", titulos["situacao"].eq("pago_sem_baixa_no_erp"), "alerta")
    sem_explicacao = titulos["situacao"].eq("baixado_sem_movimento_bancario") & titulos["explicacao"].isna()
    _regra(r, "títulos", "baixado no ERP sem dinheiro no banco (não explicado)", sem_explicacao, "alerta")
    _regra(r, "títulos", "título a receber vencido em aberto",
           titulos["tipo"].eq("RECEBER") & titulos["situacao"].eq("vencido_em_aberto"), "alerta")
    _regra(r, "auditoria", "pagamentos na fila da auditoria", len(res["anomalias"]["fila_auditoria"]), "alerta")
    return pd.DataFrame(r)


def garantir_qualidade(resultado: pd.DataFrame) -> None:
    for linha in resultado.query("not passou").itertuples():
        nivel = log.error if linha.severidade == "critica" else log.warning
        nivel("[%s] %s: %s -> %d", linha.severidade, linha.tabela, linha.regra, linha.ocorrencias)
    criticas = resultado.query("severidade == 'critica' and not passou")
    if not criticas.empty:
        raise ErroDeValidacao(f"regras críticas falharam: {criticas['regra'].tolist()}")
    log.info("%d regras verificadas: todas as críticas passaram (%d alertas)", len(resultado), (~resultado["passou"]).sum())
