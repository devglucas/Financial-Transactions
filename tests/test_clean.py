import pandas as pd

from src.clean import limpar_alfa, limpar_beta, limpar_gama, limpar_ptax, limpar_titulos
from src.utils import para_centavos, parse_numero


def _texto(**colunas) -> pd.DataFrame:
    df = pd.DataFrame(colunas, dtype="string")
    return df.assign(linha_origem=range(2, len(df) + 2))


def test_centavos_somam_sem_erro_de_float():
    valores = pd.Series([0.1, 0.2, 1234.56])
    assert 0.1 + 0.2 != 0.3
    assert para_centavos(valores).sum() == 30 + 123456
    assert para_centavos(parse_numero(pd.Series(["1.234,56", "-1234.56", "R$ 10,00"]))).tolist() == [123456, -123456, 1000]


def test_alfa_sinal_pelo_dc_e_saldo_de_abertura():
    df = _texto(data=["01/01/2025", "02/01/2025", "02/01/2025"], historico=["SALDO ANTERIOR", "PIX RECEBIDO X", "TARIFA"],
                documento=[None, "1", "2"], valor=[None, "100,00", "9,90"], dc=[None, "C", "D"],
                saldo=["1.000,00", "1.100,00", "1.090,10"])
    mov, saldos, abertura = limpar_alfa(df)
    assert abertura == 100000
    assert mov["valor_centavos"].tolist() == [10000, -990]
    assert len(saldos) == 1


def test_beta_ordena_e_descarta_pendentes():
    # arquivo em ordem decrescente: no mesmo dia, o lançamento mais antigo vem por último
    df = _texto(data=["2025-01-03", "2025-01-02", "2025-01-02", "2025-01-02"],
                historico=["PIX ENVIADO B", "PIX ENVIADO A", "PIX ENVIADO A", "TED RECEBIDA"],
                valor=["-50.00", "-100.00", "-100.00", "500.00"], saldo=["", "1300.00", "", "1400.00"],
                documento=["p1", "t3", "t2", "t1"], status=["pending", "posted", "pending", "posted"])
    mov, rej, abertura = limpar_beta(df)
    assert mov["documento"].tolist() == ["t1", "t3"]
    assert abertura == 90000                                  # 1400 - 500
    assert sorted(rej["motivo_rejeicao"]) == ["pendente_duplicado_do_lancamento_liquidado", "pendente_nao_liquidado"]


def test_gama_rejeita_valor_ilegivel():
    df = _texto(data=["07022025", "08022025"], dc=["C", "D"], valor_centavos=["000000000010000", "0000#%3!0001000"],
                documento=["CB1", "CB2"], historico=["TED", "CAMBIO"])
    mov, rej = limpar_gama(df)
    assert mov["valor_centavos"].tolist() == [10000]
    assert rej["motivo_rejeicao"].tolist() == ["valor_ilegivel_no_arquivo"]


def test_titulos_normaliza_sinal_moeda_e_remove_duplicado():
    contrapartes = pd.DataFrame({"contraparte_id": ["FOR-1", "FOR-2"], "moeda_padrao": ["BRL", "USD"]})
    df = _texto(titulo_id=["T1", "T2", "T3"], tipo=["A PAGAR", "P", "Pagar"], contraparte_id=["FOR-1", "FOR-1", "FOR-2"],
                documento=["55", "55", "INV-1"], nosso_numero=[None] * 3, emissao=["2025-01-01"] * 3,
                vencimento=["10/02/2025", "2025-02-10", "2025-03-01"], valor=["-1.500,00", "1500.00", "2000.00"],
                moeda=["R$", "BRL", None], status=["Em aberto", "LIQUIDADO", "aberto"], data_baixa=[None, "2025-02-10", None])
    titulos, rej = limpar_titulos(df, contrapartes)
    assert titulos["titulo_id"].tolist() == ["T2", "T3"]      # fica o lançamento baixado (PAGO)
    assert titulos["valor_centavos"].tolist() == [150000, 200000]
    assert titulos["moeda"].tolist() == ["BRL", "USD"]       # moeda em branco = moeda do fornecedor
    assert rej["motivo_rejeicao"].tolist() == ["lancamento_duplicado_no_erp"]


def test_ptax_rejeita_cotacao_implausivel():
    datas = [f"0{d}/01/2025" for d in range(2, 9)]
    vendas = ["5,10", "5,11", "51,20", "5,12", "0,0000", "5,13", "5,14"]
    df = _texto(Data=datas, Moeda=["USD"] * 7, Compra=vendas, Venda=vendas)
    ptax, rej = limpar_ptax(df)
    assert len(ptax) == 5
    assert set(rej["venda"]) == {51.2, 0.0}
