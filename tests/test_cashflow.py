import pandas as pd

from src.cashflow import aging_recebiveis, fluxo_mensal, saldo_diario


def _mov(linhas):
    df = pd.DataFrame(linhas, columns=["banco", "data", "valor_centavos", "categoria"])
    return df.assign(data=pd.to_datetime(df["data"]), valor_centavos=df["valor_centavos"].astype("Int64"))


def test_saldo_diario_repete_saldo_em_dias_sem_movimento():
    mov = _mov([("alfa", "2025-01-02", 10_000, "recebimento"), ("beta", "2025-01-06", -5_000, "pagamento")])
    saldo = saldo_diario(mov, {"alfa": 100_000, "beta": 50_000}).set_index("data")
    assert saldo.loc["2025-01-01", "consolidado"] == 1500.0
    assert saldo.loc["2025-01-04", "alfa"] == 1100.0          # sábado: repete o saldo de sexta
    assert saldo.loc["2025-12-31", "consolidado"] == 1550.0


def test_fluxo_mensal_ignora_transferencias_internas():
    mov = _mov([
        ("alfa", "2025-01-10", 100_000, "recebimento"),
        ("alfa", "2025-01-12", -30_000, "transferencia_interna"),
        ("beta", "2025-01-12", 30_000, "transferencia_interna"),
        ("beta", "2025-02-05", -40_000, "pagamento"),
    ])
    fluxo = fluxo_mensal(mov).set_index("mes")
    assert fluxo.loc["2025-01", ["entradas", "saidas"]].tolist() == [1000.0, 0.0]
    assert fluxo.loc["2025-02", "acumulado"] == 600.0


def test_aging_por_faixa_de_atraso():
    titulos = pd.DataFrame({
        "titulo_id": ["T1", "T2", "T3", "T4"], "tipo": "RECEBER",
        "situacao": ["a_vencer", "vencido_em_aberto", "vencido_em_aberto", "conciliado"],
        "vencimento": pd.to_datetime(["2026-01-10", "2025-12-21", "2025-08-01", "2025-11-01"]),
        "valor_brl_centavos": pd.array([10_000, 20_000, 30_000, 99_999], dtype="Int64"),
    })
    aging = aging_recebiveis(titulos).set_index("faixa")["valor"]
    assert aging["a vencer"] == 100.0 and aging["1-30 dias"] == 200.0 and aging["90+ dias"] == 300.0
    assert aging.sum() == 600.0                                 # títulos conciliados não entram
