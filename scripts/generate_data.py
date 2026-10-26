"""
Gerador de dados sintéticos do financeiro da "Andes Distribuidora de Alimentos".

A empresa vende para supermercados e restaurantes (contas a receber), compra de
fornecedores nacionais e importa em dólar/euro (contas a pagar). O dinheiro
passa por três bancos, cada um exportando o extrato em um formato:

    data/raw/banco_alfa_extrato.csv   recebimentos; CSV ';' com BOM, um bloco por mês
                                      (cabeçalho repetido + linha SALDO ANTERIOR)
    data/raw/banco_beta_extrato.csv   pagamentos; banco digital, CSV ',' em ordem
                                      DECRESCENTE, com lançamentos "pending" duplicados
    data/raw/banco_gama_cnab.txt      câmbio; arquivo de LARGURA FIXA com header e
                                      trailer de totais de controle
    data/raw/erp_titulos.csv          títulos a pagar e a receber do ERP
    data/raw/contrapartes.csv         cadastro de clientes e fornecedores
    data/raw/ptax.csv                 cotações de câmbio (formato do Banco Central)

    data/external/gabarito_*.csv      vínculos verdadeiros movimento <-> título,
                                      anomalias inseridas e linhas removidas do extrato

O gabarito serve apenas para medir a qualidade da conciliação e da detecção de
anomalias. Empresas, valores e cotações são fictícios.

Uso:
    python scripts/generate_data.py
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 2025
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
EXTERNAL_DIR = ROOT / "data" / "external"

INICIO, FIM = pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")
FERIADOS = pd.to_datetime([
    "2025-01-01", "2025-03-03", "2025-03-04", "2025-04-18", "2025-04-21", "2025-05-01",
    "2025-06-19", "2025-11-20", "2025-12-25", "2024-12-25", "2026-01-01",
])
DU = pd.offsets.CustomBusinessDay(holidays=FERIADOS)
ALCADA = 10_000.0  # pagamentos acima disso exigem aprovação da diretoria
EMPRESA = "ANDES DISTRIBUIDORA LTDA"
SALDO_INICIAL = {"alfa": 1_200_000.00, "beta": 150_000.00, "gama": 50_000.00}

PREFIXOS_CLIENTE = ["Supermercado", "Mercado", "Mercearia", "Restaurante", "Padaria", "Empório",
                    "Atacadão", "Hortifruti", "Lanchonete", "Hotel"]
NOMES_CLIENTE = ["Bom Preço", "São Jorge", "Estrela", "Central", "Família", "Primavera", "Real",
                 "Popular", "Sol Nascente", "Boa Vista", "Avenida", "Paulista", "Ipiranga", "Aurora",
                 "Bandeirantes", "Brasil", "União", "Nova Era", "Vitória", "Santa Luzia"]

# categoria -> (fornecedores, valor base em R$, recorrente mensal?, títulos/ano por fornecedor)
FORNECEDORES = {
    "Matéria-prima": (["Moinho Santa Clara", "Laticínios Serra Azul", "Frigorífico Boi Bom",
                       "Cerealista Planalto", "Açúcar União Paulista", "Grãos do Cerrado",
                       "Café Montanhês", "Hortigranjeiros Vale Verde"], 18_000, False, 40),
    "Embalagens": (["Embalagens Fortpack", "Plásticos Ideal", "Papelão Ondulado Sul", "Rótulos & Cia"],
                   6_500, False, 24),
    "Logística": (["Transportadora Rota Certa", "Expresso Litoral", "Frota Rápida Logística",
                   "Armazéns Gerais Tietê"], 9_000, False, 30),
    "Manutenção": (["Refrigeração Polar", "MaqServ Manutenção Industrial", "Elétrica Faísca"], 3_500, False, 10),
    "Serviços": (["Contabilidade Exata", "Limpeza Brilho Total", "Segurança Vigilante"], 4_200, True, 12),
    "Tecnologia": (["Nuvem Sistemas ERP", "Telecom Conecta", "Datacenter Seguro"], 2_800, True, 12),
    "Utilidades": (["Energia Paulista S.A.", "Saneamento Municipal", "Gás Natural Vale"], 7_500, True, 12),
    "Imóveis": (["Imobiliária Patrimônio"], 32_000, True, 12),
}
IMPORTADORES = [("Andean Coffee Exporters", "USD"), ("Pacific Spice Traders", "USD"),
                ("Hellas Olive Oil", "EUR"), ("Iberia Conservas", "EUR"), ("Chile Fruit Export", "USD")]


def sem_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def nome_banco(nome: str, tamanho: int = 30) -> str:
    """Bancos gravam o favorecido em CAIXA ALTA, sem acentos e truncado."""
    return sem_acentos(nome).upper().replace("&", "E").replace(".", "")[:tamanho].strip()


def dia_util(data: pd.Timestamp) -> pd.Timestamp:
    return DU.rollforward(data).normalize()


def escolher(rng, opcoes):
    return opcoes[rng.integers(len(opcoes))]


def br(valor: float) -> str:
    """1234.5 -> '1.234,50'"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- #
# Câmbio
# --------------------------------------------------------------------------- #
def gerar_ptax(rng) -> pd.DataFrame:
    dias = pd.bdate_range("2024-11-01", "2026-01-31", freq="C", holidays=FERIADOS)
    cov = [[0.006 ** 2, 0.6 * 0.006 * 0.005], [0.6 * 0.006 * 0.005, 0.005 ** 2]]
    retornos = rng.multivariate_normal([-0.0003, -0.0001], cov, len(dias))
    usd = 6.05 * np.exp(np.cumsum(retornos[:, 0]))
    eur = 6.35 * np.exp(np.cumsum(retornos[:, 1]))
    return pd.concat([
        pd.DataFrame({"data": dias, "moeda": "USD", "venda": usd.round(4)}),
        pd.DataFrame({"data": dias, "moeda": "EUR", "venda": eur.round(4)}),
    ]).assign(compra=lambda d: (d["venda"] - 0.0006).round(4)).sort_values(["data", "moeda"]).reset_index(drop=True)


def cotacao(ptax: pd.DataFrame, moeda: str, data: pd.Timestamp) -> float:
    serie = ptax[(ptax["moeda"] == moeda) & (ptax["data"] <= data)]
    return float(serie["venda"].iat[-1])


def sujar_ptax(rng, ptax: pd.DataFrame) -> pd.DataFrame:
    df = ptax.copy()
    df = df.drop(index=rng.choice(df.index, 10, replace=False))           # dias sem cotação publicada
    erros = rng.choice(df.index, 3, replace=False)
    df.loc[erros[:2], ["compra", "venda"]] *= 10                         # vírgula no lugar errado
    df.loc[erros[2], ["compra", "venda"]] = 0.0                          # cotação zerada
    df = pd.concat([df, df.sample(2, random_state=SEED)]).sort_values(["data", "moeda"])
    return pd.DataFrame({
        "Data": df["data"].dt.strftime("%d/%m/%Y"),
        "Moeda": df["moeda"],
        "Compra": df["compra"].map(lambda v: f"{v:.4f}".replace(".", ",")),
        "Venda": df["venda"].map(lambda v: f"{v:.4f}".replace(".", ",")),
    })


# --------------------------------------------------------------------------- #
# Contrapartes e títulos
# --------------------------------------------------------------------------- #
def gerar_contrapartes(rng) -> list[dict]:
    contrapartes = []
    combinacoes = [(p, n) for p in PREFIXOS_CLIENTE for n in NOMES_CLIENTE]
    for i, idx in enumerate(rng.choice(len(combinacoes), 120, replace=False), start=1):
        prefixo, nome = combinacoes[idx]
        contrapartes.append({"contraparte_id": f"CLI-{i:03d}", "nome": f"{prefixo} {nome}", "tipo": "CLIENTE",
                             "categoria": "Cliente", "moeda": "BRL",
                             "data_cadastro": pd.Timestamp("2018-01-01") + pd.Timedelta(days=int(rng.integers(0, 2400))),
                             "peso": rng.lognormal(0, 0.8)})
    i = 1
    for categoria, (nomes, base, recorrente, freq) in FORNECEDORES.items():
        for nome in nomes:
            contrapartes.append({"contraparte_id": f"FOR-{i:03d}", "nome": nome, "tipo": "FORNECEDOR",
                                 "categoria": categoria, "moeda": "BRL",
                                 "data_cadastro": pd.Timestamp("2016-01-01") + pd.Timedelta(days=int(rng.integers(0, 2900))),
                                 "base": base * rng.uniform(0.7, 1.3), "recorrente": recorrente, "freq": freq,
                                 "dia_vencimento": int(escolher(rng, [5, 10, 15, 20]))})
            i += 1
    for nome, moeda in IMPORTADORES:
        contrapartes.append({"contraparte_id": f"FOR-{i:03d}", "nome": nome, "tipo": "FORNECEDOR",
                             "categoria": "Importação", "moeda": moeda,
                             "data_cadastro": pd.Timestamp("2019-01-01") + pd.Timedelta(days=int(rng.integers(0, 1500))),
                             "base": 14_000 * rng.uniform(0.7, 1.3), "recorrente": False, "freq": 14})
        i += 1
    return contrapartes


def gerar_titulos_receber(rng, clientes: list[dict]) -> list[dict]:
    pesos = np.array([c["peso"] for c in clientes])
    emissoes = pd.bdate_range("2024-12-01", "2025-12-20", freq="C", holidays=FERIADOS)
    titulos = []
    for i in range(2700):
        cliente = clientes[rng.choice(len(clientes), p=pesos / pesos.sum())]
        emissao = emissoes[rng.integers(len(emissoes))]
        vencimento = dia_util(emissao + pd.Timedelta(days=int(rng.choice([21, 28, 30, 45], p=[0.2, 0.35, 0.3, 0.15]))))
        valor = round(float(np.clip(rng.lognormal(np.log(6600), 0.7), 300, 90_000)), 2)
        r = rng.random()
        data_pag, valor_pago, status = None, None, "pago"
        if r < 0.04:  # antecipa e ganha desconto de pontualidade
            data_pag = DU.rollback(vencimento - pd.Timedelta(days=int(rng.integers(3, 11))))
            valor_pago = round(valor * 0.98, 2)
        elif r < 0.72:
            data_pag = vencimento if rng.random() < 0.7 else vencimento - DU * int(rng.integers(1, 3))
            valor_pago = valor
        elif r < 0.92:  # atraso: multa de 2% + juros de 1% ao mês pro rata
            atraso = int(rng.integers(1, 46))
            data_pag = dia_util(vencimento + pd.Timedelta(days=atraso))
            valor_pago = round(valor * (1.02 + 0.01 * (data_pag - vencimento).days / 30), 2)
        elif r < 0.97:
            status = "inadimplente"
        else:
            status = "cancelado"
        if data_pag is not None and data_pag < INICIO:
            continue  # liquidado em 2024: fora do período
        if data_pag is not None and data_pag > FIM:
            data_pag, valor_pago, status = None, None, "aberto"
        titulos.append({
            "tipo": "RECEBER", "contraparte_id": cliente["contraparte_id"], "nome": cliente["nome"],
            "emissao": emissao, "vencimento": vencimento, "valor": valor, "moeda": "BRL",
            "nosso_numero": f"{rng.integers(10 ** 8, 10 ** 9)}", "status_real": status,
            "data_pag": data_pag, "valor_pago_brl": valor_pago, "banco": "alfa",
            "meio": "boleto" if rng.random() < 0.65 else "pix", "anomalia": None,
        })
    titulos.sort(key=lambda t: t["emissao"])
    for n, titulo in enumerate(titulos, start=10001):
        titulo["documento"] = str(n)
    return titulos


def pagamento_fornecedor(rng, vencimento: pd.Timestamp, valor: float) -> tuple:
    r = rng.random()
    if r < 0.06:
        data_pag = dia_util(vencimento + pd.Timedelta(days=int(rng.integers(1, 21))))
        return data_pag, round(valor * (1.02 + 0.01 * (data_pag - vencimento).days / 30), 2)
    if r < 0.08:
        return DU.rollback(vencimento - pd.Timedelta(days=int(rng.integers(3, 8)))), round(valor * 0.97, 2)
    if r < 0.09:
        return None, None  # empresa atrasou e ainda não pagou
    return dia_util(vencimento), valor


def gerar_titulos_pagar(rng, fornecedores: list[dict], ptax: pd.DataFrame) -> list[dict]:
    titulos = []
    emissoes = pd.bdate_range("2024-12-01", "2025-12-20", freq="C", holidays=FERIADOS)
    for f in fornecedores:
        seq_doc = int(rng.integers(1000, 90000))
        if f["categoria"] == "Importação":
            datas = sorted(emissoes[rng.integers(len(emissoes), size=rng.poisson(f["freq"]))])
            for n, emissao in enumerate(datas, start=1):
                vencimento = dia_util(emissao + pd.Timedelta(days=60))
                valor = round(float(rng.lognormal(np.log(f["base"]), 0.35)), 2)
                titulo = {"tipo": "PAGAR", "contraparte_id": f["contraparte_id"], "nome": f["nome"],
                          "emissao": emissao, "vencimento": vencimento, "valor": valor, "moeda": f["moeda"],
                          "documento": f"INV-{emissao.year}-{seq_doc + n:05d}", "nosso_numero": None,
                          "banco": "gama", "meio": "cambio", "anomalia": None, "status_real": "pago",
                          "data_pag": vencimento, "valor_pago_brl": None}
                if vencimento < INICIO:
                    continue
                if vencimento > FIM:
                    titulo.update(status_real="aberto", data_pag=None)
                else:
                    spread = rng.uniform(0.003, 0.01)
                    titulo["valor_pago_brl"] = round(valor * cotacao(ptax, f["moeda"], vencimento) * (1 + spread), 2)
                titulos.append(titulo)
            continue

        if f["recorrente"]:
            vencimentos = [dia_util(pd.Timestamp(2025, m, f["dia_vencimento"])) for m in range(1, 13)]
            vencimentos.append(dia_util(pd.Timestamp(2026, 1, f["dia_vencimento"])))
            fixo = f["categoria"] in ("Imóveis", "Tecnologia", "Serviços")
            valores = [round(f["base"] if fixo else f["base"] * rng.uniform(0.85, 1.15), 2) for _ in vencimentos]
            emissoes_titulo = [v - pd.Timedelta(days=20) for v in vencimentos]
        else:
            emissoes_titulo = sorted(emissoes[rng.integers(len(emissoes), size=rng.poisson(f["freq"]))])
            vencimentos = [dia_util(e + pd.Timedelta(days=int(escolher(rng, [28, 30, 35, 45])))) for e in emissoes_titulo]
            valores = [round(float(rng.lognormal(np.log(f["base"]), 0.45)), 2) for _ in vencimentos]

        for emissao, vencimento, valor in zip(emissoes_titulo, vencimentos, valores):
            seq_doc += int(rng.integers(1, 40))
            data_pag, valor_pago = pagamento_fornecedor(rng, vencimento, valor)
            status = "pago"
            if data_pag is not None and data_pag < INICIO:
                continue
            if data_pag is None or data_pag > FIM:
                data_pag, valor_pago, status = None, None, "aberto"
            titulos.append({"tipo": "PAGAR", "contraparte_id": f["contraparte_id"], "nome": f["nome"],
                            "emissao": emissao, "vencimento": vencimento, "valor": valor, "moeda": "BRL",
                            "documento": str(seq_doc), "nosso_numero": None, "banco": "beta",
                            "meio": str(rng.choice(["pix", "boleto", "ted"], p=[0.5, 0.4, 0.1])),
                            "anomalia": None, "status_real": status, "data_pag": data_pag,
                            "valor_pago_brl": valor_pago})
    return titulos


def inserir_anomalias(rng, titulos: list[dict], fornecedores: list[dict], contrapartes: list[dict]) -> None:
    """Fraudes e erros clássicos de contas a pagar, marcados no gabarito."""
    candidatos = [t for t in titulos if t["tipo"] == "PAGAR" and t["banco"] == "beta" and t["status_real"] == "pago"
                  and pd.Timestamp("2025-02-01") <= t["data_pag"] <= pd.Timestamp("2025-11-30")]
    escolhidos = iter(rng.permutation(len(candidatos)))
    proximo = lambda: candidatos[next(escolhidos)]  # noqa: E731

    for _ in range(8):  # pagamento duplicado com número de nota "levemente" alterado
        original = proximo()
        copia = dict(original, documento=original["documento"] + escolher(rng, ["A", "-1", "B"]),
                     anomalia="pagamento_duplicado", meio="pix")
        copia["vencimento"] = dia_util(original["vencimento"] + pd.Timedelta(days=int(rng.integers(0, 6))))
        copia["data_pag"] = copia["vencimento"]
        titulos.append(copia)

    frequentes = [f for f in fornecedores if f["categoria"] in ("Matéria-prima", "Logística", "Embalagens")]
    for _ in range(6):  # valor muito acima do histórico do fornecedor
        titulo = next(t for t in (proximo() for _ in range(50)) if any(f["contraparte_id"] == t["contraparte_id"] for f in frequentes))
        fator = rng.uniform(6, 10)
        titulo.update(valor=round(titulo["valor"] * fator, 2), valor_pago_brl=round(titulo["valor_pago_brl"] * fator, 2),
                      anomalia="valor_atipico")

    for _ in range(4):  # fracionamento: várias notas no mesmo dia, cada uma logo abaixo da alçada
        f = escolher(rng, frequentes)
        dia = dia_util(pd.Timestamp("2025-03-01") + pd.Timedelta(days=int(rng.integers(0, 250))))
        doc = int(rng.integers(100000, 900000))
        for k in range(3):
            valor = round(float(rng.uniform(ALCADA * 0.95, ALCADA * 0.999)), 2)
            titulos.append({"tipo": "PAGAR", "contraparte_id": f["contraparte_id"], "nome": f["nome"],
                            "emissao": dia - pd.Timedelta(days=2), "vencimento": dia, "valor": valor, "moeda": "BRL",
                            "documento": str(doc + k), "nosso_numero": None, "banco": "beta", "meio": "pix",
                            "anomalia": "fracionamento", "status_real": "pago", "data_pag": dia, "valor_pago_brl": valor})

    for k, nome in enumerate(["Prisma Consultoria Estratégica", "Alfa Assessoria Empresarial", "Nexus Serviços Gerais"]):
        dia = dia_util(pd.Timestamp("2025-04-01") + pd.Timedelta(days=int(rng.integers(0, 200))))
        novo = {"contraparte_id": f"FOR-{900 + k}", "nome": nome, "tipo": "FORNECEDOR", "categoria": "Serviços",
                "moeda": "BRL", "data_cadastro": dia - pd.Timedelta(days=int(rng.integers(5, 21)))}
        contrapartes.append(novo)
        valor = round(float(rng.uniform(55_000, 120_000)), 2)
        titulos.append({"tipo": "PAGAR", "contraparte_id": novo["contraparte_id"], "nome": nome,
                        "emissao": dia - pd.Timedelta(days=3), "vencimento": dia, "valor": valor, "moeda": "BRL",
                        "documento": str(rng.integers(100, 999)), "nosso_numero": None, "banco": "beta", "meio": "ted",
                        "anomalia": "fornecedor_novo", "status_real": "pago", "data_pag": dia, "valor_pago_brl": valor})

    for _ in range(5):  # pago num sábado/domingo: fora da rotina da tesouraria
        titulo = proximo()
        sabado = titulo["data_pag"] - pd.Timedelta(days=(titulo["data_pag"].dayofweek - 5) % 7)
        titulo.update(data_pag=sabado + pd.Timedelta(days=int(rng.integers(0, 2))), anomalia="pagamento_fim_de_semana",
                      meio="pix")

    for _ in range(3):  # título cancelado no ERP, mas o dinheiro saiu
        proximo().update(anomalia="titulo_cancelado_pago")


# --------------------------------------------------------------------------- #
# Extratos
# --------------------------------------------------------------------------- #
def gerar_movimentos(rng, titulos: list[dict], contrapartes: list[dict]) -> dict[str, list[dict]]:
    mov = {"alfa": [], "beta": [], "gama": []}
    docs_usados: set[str] = set()

    def documento(banco: str) -> str:
        while True:
            doc = {"alfa": f"{rng.integers(10 ** 6, 10 ** 7)}", "beta": f"tx_{rng.integers(0, 16 ** 10):010x}",
                   "gama": f"CB{rng.integers(10 ** 7, 10 ** 8)}"}[banco]
            if doc not in docs_usados:
                docs_usados.add(doc)
                return doc

    def lancar(banco, data, historico, valor, titulo=None, tipo_real="titulo"):
        mov[banco].append({"data": pd.Timestamp(data).normalize(), "historico": historico, "valor": round(valor, 2),
                           "documento": documento(banco), "titulo": titulo, "tipo_real": tipo_real})

    for t in titulos:
        if t["data_pag"] is None:
            continue
        if t["tipo"] == "RECEBER":
            historico = (f"LIQUIDACAO BOLETO {t['nosso_numero']}" if t["meio"] == "boleto"
                         else f"PIX RECEBIDO {nome_banco(t['nome'], 25)}" + (f" NF {t['documento']}" if rng.random() < 0.3 else ""))
            lancar("alfa", t["data_pag"], historico, t["valor_pago_brl"], t)
        elif t["banco"] == "gama":
            lancar("gama", t["data_pag"], f"CAMBIO IMPORTACAO {nome_banco(t['nome'], 22)} {t['documento']}", -t["valor_pago_brl"], t)
            lancar("gama", t["data_pag"], "IOF S/ OPERACAO CAMBIO", -round(t["valor_pago_brl"] * 0.0038, 2), tipo_real="imposto")
            lancar("gama", t["data_pag"], "TARIFA CONTRATO CAMBIO", -120.00, tipo_real="tarifa")
        else:
            prefixo = {"pix": "PIX ENVIADO", "boleto": "PAGTO BOLETO", "ted": "TED ENVIADA"}[t["meio"]]
            historico = f"{prefixo} {nome_banco(t['nome'])}" + (f" NF {t['documento']}" if rng.random() < 0.5 else "")
            lancar("beta", t["data_pag"], historico, -t["valor_pago_brl"], t)
            if t["meio"] == "ted":
                lancar("beta", t["data_pag"], "TARIFA TED", -9.90, tipo_real="tarifa")

    meses = pd.date_range(INICIO, FIM, freq="MS")
    for mes in meses:
        lancar("alfa", dia_util(mes), "TARIFA PACOTE SERVICOS", -189.90, tipo_real="tarifa")
        lancar("alfa", dia_util(mes), "REND APLIC AUTOMATICA", float(rng.uniform(1200, 4800)), tipo_real="rendimento")
        lancar("beta", mes + DU * 4, "FOLHA DE PAGAMENTO", -float(rng.uniform(175_000, 195_000)), tipo_real="folha")
        lancar("beta", dia_util(mes + pd.Timedelta(days=19)), "DARF 2172 COFINS PIS", -float(rng.uniform(45_000, 75_000)),
               tipo_real="imposto")
        lancar("beta", dia_util(mes + pd.Timedelta(days=19)), "GPS INSS EMPRESA", -float(rng.uniform(30_000, 45_000)),
               tipo_real="imposto")

    fornecedores = [c for c in contrapartes if c["tipo"] == "FORNECEDOR" and c["moeda"] == "BRL"]
    for _ in range(6):  # PIX enviado por engano e devolvido no dia seguinte
        dia = dia_util(INICIO + pd.Timedelta(days=int(rng.integers(10, 350))))
        favorecido, valor = nome_banco(escolher(rng, fornecedores)["nome"]), float(rng.uniform(500, 5000))
        lancar("beta", dia, f"PIX ENVIADO {favorecido}", -valor, tipo_real="estorno")
        lancar("beta", dia + DU, f"PIX DEVOLVIDO {favorecido}", valor, tipo_real="estorno")

    # transferências entre contas próprias: Alfa abastece Beta toda semana e Gama antes de cada câmbio
    # A tesouraria transfere toda segunda-feira só o que falta para cobrir os pagamentos da semana.
    beta = pd.DataFrame(mov["beta"])
    transferido = 0.0
    for semana in pd.date_range(INICIO, FIM, freq="W-MON"):
        inicio = dia_util(semana)
        saldo = SALDO_INICIAL["beta"] + beta.loc[beta["data"] < inicio, "valor"].sum() + transferido
        semana_mov = beta[(beta["data"] >= inicio) & (beta["data"] < inicio + pd.Timedelta(days=7))]
        necessidade = semana_mov.loc[semana_mov["valor"] < 0, "valor"].abs().sum() + 50_000 - saldo
        if necessidade <= 0:
            continue
        valor = float(np.ceil(necessidade / 10_000) * 10_000)
        transferido += valor
        envio = inicio - DU  # sai na véspera; às vezes só cai no dia seguinte (D+1)
        lancar("alfa", envio, f"TED ENVIADA {EMPRESA}", -valor, tipo_real="transferencia")
        lancar("beta", envio if rng.random() < 0.8 else inicio, f"TED RECEBIDA {EMPRESA[:22]}", valor,
               tipo_real="transferencia")
    for m in [m for m in mov["gama"] if m["historico"].startswith("CAMBIO")]:
        valor = float(np.ceil(abs(m["valor"]) * 1.0045 / 1000) * 1000 + 1000)
        vespera = m["data"] - DU
        lancar("alfa", vespera, f"TED ENVIADA {EMPRESA}", -valor, tipo_real="transferencia")
        lancar("gama", vespera, f"TED RECEBIDA {EMPRESA[:22]}", valor, tipo_real="transferencia")

    for banco, lista in mov.items():
        df = pd.DataFrame(lista)
        df = df[(df["data"] >= INICIO) & (df["data"] <= FIM)]
        # dentro do dia a ordem é aleatória, mas créditos de transferência entram no início do expediente
        ordem = np.where((df["tipo_real"] == "transferencia") & (df["valor"] > 0), -1.0, rng.random(len(df)))
        df = df.assign(ordem=ordem).sort_values(["data", "ordem"]).drop(columns="ordem")
        df["saldo"] = (SALDO_INICIAL[banco] + df["valor"].cumsum()).round(2)
        mov[banco] = df.reset_index(drop=True)
    return mov


def exportar_alfa(rng, mov: pd.DataFrame) -> pd.DataFrame:
    """Um bloco por mês (o banco só exporta mês a mês e alguém concatenou os arquivos)."""
    removidas = mov.loc[rng.choice(mov.index, 4, replace=False)]
    exportado = mov.drop(index=removidas.index)
    linhas = []
    saldo_anterior = SALDO_INICIAL["alfa"]
    for mes, bloco in exportado.groupby(exportado["data"].dt.to_period("M")):
        linhas.append("Data;Histórico;Documento;Valor;D/C;Saldo")
        linhas.append(f"{mes.start_time:%d/%m/%Y};SALDO ANTERIOR;;;;{br(saldo_anterior)}")
        for m in bloco.itertuples():
            linhas.append(f"{m.data:%d/%m/%Y};{m.historico};{m.documento};{br(abs(m.valor))};"
                          f"{'C' if m.valor > 0 else 'D'};{br(m.saldo)}")
        saldo_anterior = mov.loc[mov["data"].dt.to_period("M") == mes, "saldo"].iat[-1]
        linhas.append("")
    (RAW_DIR / "banco_alfa_extrato.csv").write_text("\n".join(linhas), encoding="utf-8-sig")
    return removidas


def exportar_beta(rng, mov: pd.DataFrame) -> None:
    """Banco digital: ordem decrescente e lançamentos 'pending' que depois viram 'posted'."""
    linhas = mov.assign(status="posted", amount=mov["valor"], balance=mov["saldo"])
    pendentes = linhas.sample(frac=0.03, random_state=SEED).assign(
        status="pending", balance=np.nan,
        documento=lambda d: [f"tx_{rng.integers(0, 16 ** 10):010x}" for _ in range(len(d))])
    em_transito = pd.DataFrame({"data": [FIM, FIM], "historico": ["PIX ENVIADO EXPRESSO LITORAL", "PAGTO BOLETO PLASTICOS IDEAL"],
                                "amount": [-4321.10, -2980.45], "documento": ["tx_ffff000001", "tx_ffff000002"],
                                "status": "pending", "balance": np.nan})
    saida = pd.concat([linhas, pendentes, em_transito]).assign(ordem=lambda d: range(len(d)))
    saida = saida.sort_values(["data", "status", "ordem"], ascending=[False, True, False])
    pd.DataFrame({
        "date": saida["data"].dt.strftime("%Y-%m-%d"), "description": saida["historico"],
        "amount": saida["amount"].map(lambda v: f"{v:.2f}"),
        "balance": saida["balance"].map(lambda v: "" if pd.isna(v) else f"{v:.2f}"),
        "transaction_id": saida["documento"], "status": saida["status"],
    }).to_csv(RAW_DIR / "banco_beta_extrato.csv", index=False)


def exportar_gama(rng, mov: pd.DataFrame) -> None:
    """Layout de largura fixa (estilo CNAB): header (0), detalhes (1) e trailer (9)."""
    linhas = [f"0{'BANCO GAMA S.A.':<30}{'0012345-6':<12}{FIM:%d%m%Y}".ljust(100)]
    for m in mov.itertuples():
        centavos = round(abs(m.valor) * 100)
        linhas.append(f"1{m.data:%d%m%Y}{'C' if m.valor > 0 else 'D'}{centavos:015d}{m.documento:<10}"
                      f"{m.historico[:40]:<40}".ljust(100))
    corrompida = int(rng.integers(5, len(linhas)))  # falha de transmissão: valor ilegível
    linhas[corrompida] = linhas[corrompida][:15] + "0#%3!" + linhas[corrompida][20:]
    debitos = round(mov.loc[mov["valor"] < 0, "valor"].abs().sum() * 100)
    creditos = round(mov.loc[mov["valor"] > 0, "valor"].sum() * 100)
    linhas.append(f"9{len(mov):06d}{debitos:017d}{creditos:017d}".ljust(100))
    (RAW_DIR / "banco_gama_cnab.txt").write_text("\n".join(linhas) + "\n", encoding="ascii")


# --------------------------------------------------------------------------- #
# ERP
# --------------------------------------------------------------------------- #
def exportar_erp(rng, titulos: list[dict]) -> pd.DataFrame:
    registros = []
    for i, t in enumerate(titulos, start=1):
        t["titulo_id"] = f"TIT-{i:05d}"
        if t["anomalia"] == "titulo_cancelado_pago" or t["status_real"] == "cancelado":
            status = "CANCELADO"
        elif t["status_real"] == "pago":
            status = "PAGO" if rng.random() > 0.04 else "ABERTO"           # baixa ainda não feita no ERP
        elif t["vencimento"] < FIM and rng.random() < 0.02:
            status = "PAGO"                                                # baixa sem dinheiro no banco
        else:
            status = "ABERTO"
        data_baixa = (t["data_pag"] if t["data_pag"] is not None else t["vencimento"]) if status == "PAGO" else None
        if data_baixa is not None and rng.random() < 0.1:
            data_baixa = None
        registros.append({**t, "status_erp": status, "data_baixa": data_baixa})
    df = pd.DataFrame(registros)

    # duplicidade de digitação: o mesmo título lançado duas vezes (só um é pago)
    duplicados = df[(df["tipo"] == "PAGAR") & (df["anomalia"].isna())].sample(12, random_state=SEED).copy()
    duplicados["titulo_id"] = [f"TIT-{len(df) + k + 1:05d}" for k in range(len(duplicados))]
    duplicados[["status_erp", "data_baixa", "data_pag"]] = ["ABERTO", None, None]
    df = pd.concat([df, duplicados], ignore_index=True)

    def data_texto(d):
        if pd.isna(d):
            return ""
        return d.strftime("%d/%m/%Y") if rng.random() < 0.15 else d.strftime("%Y-%m-%d")

    def valor_texto(t):
        valor = -t.valor if t.tipo == "PAGAR" and rng.random() < 0.3 else t.valor  # sinal invertido no módulo de pagar
        return br(valor) if rng.random() < 0.1 else f"{valor:.2f}"

    moedas = {"BRL": ["BRL", "BRL", "R$", ""], "USD": ["USD", "US$", "dolar"], "EUR": ["EUR", "€", "euro"]}
    tipos = {"RECEBER": ["RECEBER", "Receber", "A RECEBER", "R"], "PAGAR": ["PAGAR", "Pagar", "A PAGAR", "P"]}
    status_txt = {"PAGO": ["PAGO", "Pago", "LIQUIDADO"], "ABERTO": ["ABERTO", "Em aberto", "aberto"],
                  "CANCELADO": ["CANCELADO", "Cancelado"]}
    return pd.DataFrame({
        "titulo_id": df["titulo_id"],
        "tipo": [escolher(rng, tipos[t]) for t in df["tipo"]],
        "contraparte_id": df["contraparte_id"],
        "documento": df["documento"],
        "nosso_numero": df["nosso_numero"],
        "emissao": df["emissao"].map(data_texto),
        "vencimento": df["vencimento"].map(data_texto),
        "valor": [valor_texto(t) for t in df.itertuples()],
        "moeda": [escolher(rng, moedas[m]) for m in df["moeda"]],
        "status": [escolher(rng, status_txt[s]) for s in df["status_erp"]],
        "data_baixa": df["data_baixa"].map(data_texto),
    }).sample(frac=1, random_state=SEED)


# --------------------------------------------------------------------------- #
def main() -> None:
    rng = np.random.default_rng(SEED)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)

    ptax = gerar_ptax(rng)
    contrapartes = gerar_contrapartes(rng)
    clientes = [c for c in contrapartes if c["tipo"] == "CLIENTE"]
    fornecedores = [c for c in contrapartes if c["tipo"] == "FORNECEDOR"]
    titulos = gerar_titulos_receber(rng, clientes) + gerar_titulos_pagar(rng, fornecedores, ptax)
    inserir_anomalias(rng, titulos, fornecedores, contrapartes)
    erp = exportar_erp(rng, titulos)  # atribui titulo_id
    movimentos = gerar_movimentos(rng, titulos, contrapartes)

    removidas = exportar_alfa(rng, movimentos["alfa"])
    exportar_beta(rng, movimentos["beta"])
    exportar_gama(rng, movimentos["gama"])
    erp.to_csv(RAW_DIR / "erp_titulos.csv", index=False)
    sujar_ptax(rng, ptax).to_csv(RAW_DIR / "ptax.csv", sep=";", index=False)
    pd.DataFrame([{
        "contraparte_id": c["contraparte_id"],
        "nome": c["nome"] + (" " if rng.random() < 0.1 else ""),
        "tipo": c["tipo"], "categoria": c["categoria"] if rng.random() > 0.1 else c["categoria"].upper(),
        "moeda_padrao": c["moeda"], "data_cadastro": c["data_cadastro"].strftime("%Y-%m-%d"),
    } for c in contrapartes]).to_csv(RAW_DIR / "contrapartes.csv", index=False)

    # gabaritos
    vinculos = [{"banco": banco, "documento": m.documento, "titulo_id": m.titulo["titulo_id"]}
                for banco, df in movimentos.items() for m in df.itertuples()
                if m.titulo is not None and not (banco == "alfa" and m.Index in removidas.index)]
    pd.DataFrame(vinculos).to_csv(EXTERNAL_DIR / "gabarito_conciliacao.csv", index=False)
    pd.DataFrame([{"titulo_id": t["titulo_id"], "anomalia": t["anomalia"]} for t in titulos if t["anomalia"]]) \
        .to_csv(EXTERNAL_DIR / "gabarito_anomalias.csv", index=False)
    removidas[["data", "historico", "documento", "valor"]].to_csv(EXTERNAL_DIR / "gabarito_linhas_removidas_alfa.csv", index=False)

    print(f"Títulos: {len(titulos)} (+12 duplicados no ERP) | movimentos: "
          + ", ".join(f"{b} {len(df)}" for b, df in movimentos.items()))
    for arquivo in sorted([*RAW_DIR.iterdir(), *EXTERNAL_DIR.iterdir()]):
        print(f"  {arquivo.relative_to(ROOT)!s:<45} {arquivo.stat().st_size / 1024:>8.1f} KB")


if __name__ == "__main__":
    main()
