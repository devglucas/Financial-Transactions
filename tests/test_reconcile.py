import pandas as pd

from src.reconcile import conciliar, explicar_por_lancamentos_perdidos

CONTRAPARTES = pd.DataFrame({
    "contraparte_id": ["CLI-1", "FOR-1", "FOR-2"],
    "nome_banco": ["PADARIA AURORA", "MOINHO SANTA CLARA", "HELLAS OLIVE OIL"],
})
PTAX = pd.DataFrame({"data": pd.to_datetime(["2025-03-10"]), "moeda": ["EUR"], "venda": [6.0]})


def _mov(linhas):
    df = pd.DataFrame(linhas, columns=["mov_id", "data", "historico", "valor_centavos", "categoria"])
    return df.assign(data=pd.to_datetime(df["data"]), valor_centavos=df["valor_centavos"].astype("Int64"),
                     banco=df["mov_id"].str.split(":").str[0])


def _titulos(linhas):
    df = pd.DataFrame(linhas, columns=["titulo_id", "tipo", "contraparte_id", "documento", "nosso_numero",
                                       "vencimento", "moeda", "valor_centavos", "status_erp"])
    return df.assign(vencimento=pd.to_datetime(df["vencimento"]), valor_centavos=df["valor_centavos"].astype("Int64"))


def test_regras_de_conciliacao():
    mov = _mov([
        ("alfa:1", "2025-02-10", "LIQUIDACAO BOLETO 123456789", 102_000, "recebimento"),      # boleto com juros
        ("beta:1", "2025-02-20", "PIX ENVIADO MOINHO SANTA CLARA", -50_000, "pagamento"),     # valor exato
        ("alfa:2", "2025-03-20", "PIX RECEBIDO PADARIA AURORA", 103_000, "recebimento"),      # 10 dias de atraso
        ("alfa:3", "2025-03-05", "PIX RECEBIDO PADARIA AURORA", 102_100, "recebimento"),      # 2 dias de atraso
        ("gama:1", "2025-03-10", "CAMBIO IMPORTACAO HELLAS OLIVE OIL", -6_040_000, "pagamento"),
        ("alfa:4", "2025-03-01", "TARIFA PACOTE SERVICOS", -18_990, "tarifa"),
    ])
    titulos = _titulos([
        ("T1", "RECEBER", "CLI-1", "10001", "123456789", "2025-02-05", "BRL", 100_000, "PAGO"),
        ("T2", "PAGAR", "FOR-1", "555", None, "2025-02-20", "BRL", 50_000, "ABERTO"),
        ("T3", "RECEBER", "CLI-1", "10002", None, "2025-03-03", "BRL", 100_000, "PAGO"),
        ("T4", "RECEBER", "CLI-1", "10003", None, "2025-03-10", "BRL", 100_000, "PAGO"),
        ("T5", "PAGAR", "FOR-2", "INV-2025-00001", None, "2025-03-10", "EUR", 1_000_000, "CANCELADO"),
    ])
    r = conciliar(mov, titulos, CONTRAPARTES, PTAX)
    pares = r["conciliacao"].set_index("mov_id")
    assert pares.loc["alfa:1", ["titulo_id", "regra", "natureza_diferenca"]].tolist() == ["T1", "referencia_documento", "juros_e_multa"]
    assert pares.loc["beta:1", ["titulo_id", "regra"]].tolist() == ["T2", "valor_exato"]
    # os dois PIX da mesma padaria: cada um vai para o título cujo atraso explica os juros
    assert pares.loc["alfa:2", "titulo_id"] == "T4" and pares.loc["alfa:3", "titulo_id"] == "T3"
    assert pares.loc["gama:1", ["titulo_id", "regra"]].tolist() == ["T5", "cambio_ptax"]
    assert "alfa:4" not in pares.index

    situacao = r["titulos"].set_index("titulo_id")["situacao"]
    assert situacao["T2"] == "pago_sem_baixa_no_erp"
    assert situacao["T5"] == "pago_mas_cancelado_no_erp"


def test_titulo_sem_movimento_explicado_por_linha_perdida():
    titulos = pd.DataFrame({
        "titulo_id": ["T1", "T2"], "situacao": "baixado_sem_movimento_bancario", "sentido": [1, 1],
        "valor_brl_centavos": pd.array([100_000, 70_000], dtype="Int64"),
        "vencimento": pd.to_datetime(["2025-02-05", "2025-02-05"]),
    })
    perdidos = pd.DataFrame({"banco": ["alfa"], "data_aproximada": pd.to_datetime(["2025-02-06"]),
                             "valor_centavos": [100_000], "origem": ["quebra do saldo corrido"]})
    explicacao = explicar_por_lancamentos_perdidos(titulos, perdidos).set_index("titulo_id")["explicacao"]
    assert explicacao["T1"].startswith("lançamento faltando no extrato")
    assert pd.isna(explicacao["T2"])
