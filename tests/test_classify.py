import pandas as pd

from src.classify import classificar, classificar_movimentos
from src.utils import emparelhar_um_para_um


def _mov(linhas):
    df = pd.DataFrame(linhas, columns=["banco", "data", "historico", "valor_centavos"])
    df["data"] = pd.to_datetime(df["data"])
    df["valor_centavos"] = df["valor_centavos"].astype("Int64")
    df["mov_id"] = [f"{b}:{i}" for i, b in enumerate(df["banco"])]
    df["sequencia"] = range(len(df))
    return df


def test_classificacao_por_historico():
    mov = _mov([
        ("alfa", "2025-01-02", "TED ENVIADA ANDES DISTRIBUIDORA LTDA", -100),
        ("alfa", "2025-01-02", "TARIFA PACOTE SERVICOS", -10),
        ("beta", "2025-01-02", "DARF 2172 COFINS PIS", -50),
        ("alfa", "2025-01-02", "PIX RECEBIDO PADARIA X", 300),
        ("beta", "2025-01-02", "PIX ENVIADO MOINHO Y", -200),
    ])
    assert classificar(mov).tolist() == ["transferencia_interna", "tarifa", "imposto", "recebimento", "pagamento"]


def test_transferencia_de_sexta_cai_na_segunda():
    mov = _mov([
        ("alfa", "2025-01-17", "TED ENVIADA ANDES DISTRIBUIDORA LTDA", -500),   # sexta
        ("beta", "2025-01-20", "TED RECEBIDA ANDES DISTRIBUIDORA LT", 500),     # segunda (D+1 útil)
        ("alfa", "2025-01-17", "TED ENVIADA ANDES DISTRIBUIDORA LTDA", -900),   # sem par
    ])
    resultado, pares = classificar_movimentos(mov)
    assert len(pares) == 1
    assert resultado["par_mov_id"].tolist()[:2] == ["beta:1", "alfa:0"]
    assert pd.isna(resultado["par_mov_id"].iat[2])


def test_estorno_anula_envio_e_devolucao():
    mov = _mov([
        ("beta", "2025-03-24", "PIX ENVIADO MOINHO SANTA CLARA", -798),
        ("beta", "2025-03-25", "PIX DEVOLVIDO MOINHO SANTA CLARA", 798),
        ("beta", "2025-03-25", "PIX ENVIADO MOINHO SANTA CLARA", -798),  # pagamento legítimo depois
    ])
    resultado, _ = classificar_movimentos(mov)
    assert resultado["categoria"].tolist() == ["estornado", "estornado", "pagamento"]


def test_emparelhamento_guloso_usa_cada_lado_uma_vez():
    candidatos = pd.DataFrame({"a": ["x", "x", "y"], "b": [1, 2, 1]})  # já ordenado do melhor ao pior
    assert emparelhar_um_para_um(candidatos, "a", "b").values.tolist() == [["x", 1]]
