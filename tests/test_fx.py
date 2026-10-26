import pandas as pd

from src.fx import cotacao_na_data, valor_em_reais

PTAX = pd.DataFrame({
    "data": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-02", "2025-01-03"]),
    "moeda": ["USD", "USD", "EUR", "EUR"],
    "venda": [6.00, 6.10, 6.50, 6.60],
})


def test_fim_de_semana_usa_ultima_cotacao_da_mesma_moeda():
    df = pd.DataFrame({"moeda": ["USD", "EUR", "BRL"], "data": pd.to_datetime(["2025-01-05", "2025-01-02", "2025-01-05"])})
    resultado = cotacao_na_data(df, PTAX, "data")
    assert resultado["ptax_venda"].tolist()[:2] == [6.10, 6.50]  # domingo -> sexta (03/01)
    assert pd.isna(resultado["ptax_venda"].iat[2])                # real não precisa de cotação


def test_defasagem_acima_do_limite_fica_sem_cotacao():
    df = pd.DataFrame({"moeda": ["USD"], "data": pd.to_datetime(["2025-01-20"])})
    assert cotacao_na_data(df, PTAX, "data")["ptax_venda"].isna().all()


def test_valor_em_reais():
    titulos = pd.DataFrame({"moeda": ["USD", "BRL"], "vencimento": pd.to_datetime(["2025-01-03", "2025-01-03"]),
                            "valor_centavos": pd.array([100_000, 50_000], dtype="Int64")})
    assert valor_em_reais(titulos, PTAX)["valor_brl_centavos"].tolist() == [610_000, 50_000]
