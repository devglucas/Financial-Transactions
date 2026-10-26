import pandas as pd

from src.source_checks import conferir_saldo_corrido, conferir_trailer


def _movimentos(banco, valores, saldos):
    return pd.DataFrame({
        "banco": banco, "mov_id": [f"{banco}:{i}" for i in range(len(valores))],
        "data": pd.date_range("2025-01-02", periods=len(valores)), "sequencia": range(len(valores)),
        "valor_centavos": pd.array(valores, dtype="Int64"), "saldo_informado_centavos": pd.array(saldos, dtype="Int64"),
    })


def test_saldo_corrido_encontra_lancamento_faltante():
    # abertura 1000; o extrato perdeu um crédito de +300 entre o 2º e o 3º movimento
    mov = _movimentos("alfa", [100, -50, 200], [1100, 1050, 1550])
    quebras, resumo = conferir_saldo_corrido(mov, {"alfa": 1000})
    assert len(quebras) == 1
    assert quebras.iloc[0]["antes_do_movimento"] == "alfa:2"
    assert quebras.iloc[0]["valor_faltante"] == 3.0
    assert resumo.iloc[0]["diferenca"] == 3.0


def test_saldo_corrido_sem_quebras():
    quebras, _ = conferir_saldo_corrido(_movimentos("beta", [100, -50], [1100, 1050]), {"beta": 1000})
    assert quebras.empty


def test_trailer_revela_valor_da_linha_perdida():
    mov = _movimentos("gama", [5000, -2000], [None, None])
    rejeitados = pd.DataFrame({"motivo_rejeicao": ["valor_ilegivel_no_arquivo"]})
    trailer = {"quantidade": 3, "debitos_centavos": 2000, "creditos_centavos": 5700}
    resultado = conferir_trailer(mov, rejeitados, trailer).set_index("controle")["diferenca"]
    assert resultado.tolist() == [0, 0, 700]  # o crédito ilegível valia 700 centavos
