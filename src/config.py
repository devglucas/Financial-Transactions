"""Caminhos, calendário e regras de negócio do financeiro."""

from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "data" / "raw"
EXTERNAL_DIR = ROOT_DIR / "data" / "external"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
OUTPUT_DIR = ROOT_DIR / "output"
REPORTS_DIR = OUTPUT_DIR / "reports"
CHARTS_DIR = OUTPUT_DIR / "charts"

ARQUIVOS_RAW = {
    "alfa": RAW_DIR / "banco_alfa_extrato.csv",
    "beta": RAW_DIR / "banco_beta_extrato.csv",
    "gama": RAW_DIR / "banco_gama_cnab.txt",
    "erp": RAW_DIR / "erp_titulos.csv",
    "contrapartes": RAW_DIR / "contrapartes.csv",
    "ptax": RAW_DIR / "ptax.csv",
}
ARQUIVOS_GABARITO = {
    "conciliacao": EXTERNAL_DIR / "gabarito_conciliacao.csv",
    "anomalias": EXTERNAL_DIR / "gabarito_anomalias.csv",
    "linhas_removidas": EXTERNAL_DIR / "gabarito_linhas_removidas_alfa.csv",
}

# Calendário: feriados bancários nacionais (Carnaval incluso)
DATA_INICIO, DATA_CORTE = pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")
FERIADOS = pd.to_datetime([
    "2025-01-01", "2025-03-03", "2025-03-04", "2025-04-18", "2025-04-21", "2025-05-01",
    "2025-06-19", "2025-11-20", "2025-12-25", "2026-01-01",
])
DIA_UTIL = pd.offsets.CustomBusinessDay(holidays=FERIADOS)

# O arquivo CNAB do Banco Gama não informa saldo: o saldo de abertura vem do
# fechamento de 2024 informado pela tesouraria.
SALDO_ABERTURA_GAMA_CENTAVOS = 5_000_000

# Conciliação
JANELA_DIAS_ANTES_VENCIMENTO = 15     # pagamento antecipado aceito
JANELA_DIAS_APOS_VENCIMENTO = 60      # pagamento em atraso aceito
VARIACAO_MINIMA = -0.06               # desconto máximo esperado (pontualidade)
VARIACAO_MAXIMA = 0.12                # multa + juros máximos esperados
TOLERANCIA_CAMBIO = 0.015             # spread do banco sobre a PTAX
DIAS_UTEIS_TRANSFERENCIA = 2          # a TED cai na outra conta em até D+2 úteis

NOME_EMPRESA_NO_BANCO = "ANDES DISTRIB"   # como o banco grava a própria empresa
DIAS_ESTORNO = 5

# Anomalias
ALCADA_APROVACAO = 1_000_000          # R$ 10.000,00 em centavos
DIAS_FORNECEDOR_NOVO = 30
VALOR_FORNECEDOR_NOVO = 5_000_000     # R$ 50.000,00 em centavos
DIAS_PAGAMENTO_DUPLICADO = 7
LIMIAR_Z_ROBUSTO = 3.5
MINIMO_HISTORICO_FORNECEDOR = 6
