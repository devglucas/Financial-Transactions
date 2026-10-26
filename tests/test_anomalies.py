import numpy as np
import pandas as pd

from src.anomalies import (
    benford,
    regra_duplicado,
    regra_fora_de_dia_util,
    regra_fornecedor_novo,
    regra_fracionamento,
    regra_valor_atipico,
)


def _pagamentos(linhas):
    df = pd.DataFrame(linhas, columns=["titulo_id", "contraparte_id", "documento", "data_pagamento", "valor_centavos"])
    return df.assign(data_pagamento=pd.to_datetime(df["data_pagamento"]), data_cadastro=pd.Timestamp("2020-01-01"),
                     valor_centavos=df["valor_centavos"].astype("int64"))


def test_duplicado_sinaliza_o_pagamento_posterior():
    p = _pagamentos([
        ("T1", "F1", "123", "2025-03-03", 500_000),
        ("T2", "F1", "123A", "2025-03-06", 500_000),   # mesmo valor 3 dias depois
        ("T3", "F1", "200", "2025-04-03", 500_000),   # 28 dias depois: recorrente, não duplicado
    ])
    assert regra_duplicado(p)["titulo_id"].tolist() == ["T2"]


def test_fracionamento_abaixo_da_alcada():
    p = _pagamentos([
        ("T1", "F1", "1", "2025-05-05", 990_000), ("T2", "F1", "2", "2025-05-05", 985_000),
        ("T3", "F2", "3", "2025-05-05", 990_000),                                          # sozinho no dia
        ("T4", "F1", "4", "2025-05-05", 300_000),                                          # longe da alçada
    ])
    assert sorted(regra_fracionamento(p)["titulo_id"]) == ["T1", "T2"]


def test_fornecedor_novo_com_valor_alto():
    p = _pagamentos([("T1", "F9", "1", "2025-06-10", 8_000_000), ("T2", "F9", "2", "2025-06-10", 100_000)])
    p["data_cadastro"] = pd.Timestamp("2025-06-01")
    assert regra_fornecedor_novo(p)["titulo_id"].tolist() == ["T1"]


def test_valor_atipico_pelo_z_robusto():
    rng = np.random.default_rng(1)
    valores = (rng.lognormal(np.log(1_000_000), 0.3, 20)).astype(int).tolist() + [9_000_000]
    p = _pagamentos([(f"T{i}", "F1", str(i), "2025-01-10", v) for i, v in enumerate(valores)])
    assert regra_valor_atipico(p)["titulo_id"].tolist() == ["T20"]


def test_pagamento_em_fim_de_semana_e_feriado():
    p = _pagamentos([("T1", "F1", "1", "2025-03-08", 1), ("T2", "F1", "2", "2025-04-21", 1), ("T3", "F1", "3", "2025-04-22", 1)])
    assert regra_fora_de_dia_util(p)["titulo_id"].tolist() == ["T1", "T2"]   # sábado e Tiradentes


def test_benford_em_dados_que_seguem_a_lei():
    rng = np.random.default_rng(7)
    valores = pd.Series((10 ** rng.uniform(3, 9, 20_000)).astype("int64"))   # várias ordens de grandeza
    tabela, mad, conformidade = benford(valores)
    assert mad < 0.006 and conformidade == "conformidade próxima"
    assert abs(tabela.loc[0, "observado_pct"] - 30.1) < 1.5
