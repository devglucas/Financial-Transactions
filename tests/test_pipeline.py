"""Testes de ponta a ponta sobre os dados de data/raw (sem gravar arquivos)."""

import pytest

from main import executar_pipeline


@pytest.fixture(scope="module")
def resultado():
    return executar_pipeline(exportar=False)


def test_nenhuma_regra_critica_falha(resultado):
    assert resultado["validacoes"].query("severidade == 'critica'")["passou"].all()


def test_conciliacao_um_para_um(resultado):
    conc = resultado["conciliacao"]
    assert conc["mov_id"].is_unique and conc["titulo_id"].is_unique


def test_conciliacao_contra_gabarito(resultado):
    total = resultado["avaliacao"]["avaliacao_conciliacao"].query("regra == 'TOTAL'").iloc[0]
    assert total["precisao_pct"] == 100.0
    assert total["recall_pct"] >= 99.9


def test_controles_encontram_os_lancamentos_perdidos(resultado):
    controle = resultado["avaliacao"]["avaliacao_controles"].iloc[0]
    assert controle["recall_pct"] == 100.0
    explicados = resultado["titulos"]["explicacao"].notna().sum()
    assert explicados == len(resultado["perdidos"])


def test_anomalias_deterministicas_sem_erro(resultado):
    avaliacao = resultado["avaliacao"]["avaliacao_anomalias"].set_index("regra")
    for regra in ["pagamento_duplicado", "fracionamento", "fornecedor_novo", "titulo_cancelado_pago",
                  "pagamento_fora_de_dia_util"]:
        assert avaliacao.loc[regra, "precisao_pct"] == 100.0, regra
        assert avaliacao.loc[regra, "recall_pct"] == 100.0, regra


def test_saldo_consolidado_bate_com_os_movimentos(resultado):
    saldo = resultado["caixa"]["saldo_diario"]
    esperado = (sum(resultado["aberturas"].values()) + resultado["movimentos"]["valor_centavos"].sum()) / 100
    assert saldo["consolidado"].iat[-1] == pytest.approx(esperado, abs=0.01)
