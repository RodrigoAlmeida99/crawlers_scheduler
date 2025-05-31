import streamlit as st
import pandas as pd
import os
from datetime import datetime

# Caminho real da planilha Excel
CAMINHO_TABELA = r"C:\Users\ROdrigo.almeida\OneDrive - Alvarez and Marsal\Documents\Crawlers-Python\Crawlers_Scheduler\source\Crawlers_scheduler.xlsx"
NOME_ABA = "Agendamentos"

def carregar_agendamentos():
    if os.path.exists(CAMINHO_TABELA):
        return pd.read_excel(CAMINHO_TABELA, sheet_name=NOME_ABA)
    else:
        return pd.DataFrame(columns=["Nome", "Caminho", "Periodicidade", "Última Execução", "Ativo"])

def salvar_agendamentos(df):
    with pd.ExcelWriter(CAMINHO_TABELA, engine="openpyxl", mode='w') as writer:
        df.to_excel(writer, sheet_name=NOME_ABA, index=False)

# Configurações da página
st.set_page_config(page_title="Gerenciador de Agendamentos", layout="wide")

st.title("📅 Gerenciador de Agendamentos de Crawlers")

# Carrega os agendamentosx
df = carregar_agendamentos()

# 🔷 Card com total de agendamentos
col1, col2 = st.columns(2)
with col1:
    st.metric("Total de Agendamentos", len(df))
with col2:
    ativos = df[df["Status"].astype(str).str.lower() == "ativo"]

    st.metric("Agendamentos Ativos", len(ativos))

# ➕ Formulário para novo agendamento
with st.expander("➕ Novo Agendamento"):
    with st.form("form_novo_agendamento"):
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Nome do Fluxo")
            caminho = st.text_input("Caminho do Script ou FME")
            periodicidade = st.selectbox("Periodicidade", ["Diário", "Semanal", "Mensal", "Outro"])
        with col2:
            ativo = st.checkbox("Ativo", value=True)
            ultima_execucao = st.date_input("Última Execução (opcional)", value=None)

        enviar = st.form_submit_button("Salvar Agendamento")

        if enviar:
            nova_linha = {
                "Nome": nome,
                "Caminho": caminho,
                "Periodicidade": periodicidade,
                "Última Execução": ultima_execucao if ultima_execucao else "",
                "Ativo": ativo
            }
            df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
            salvar_agendamentos(df)
            st.success(f"✅ Agendamento '{nome}' salvo com sucesso!")
            st.experimental_rerun()


# 🔍 Campo de busca
st.subheader("Busca")

col1, col2 = st.columns([1, 1])  # Ajuste os pesos conforme quiser
with col1:
    termo_busca = st.text_input("Buscar", placeholder="Digite algo...", label_visibility="collapsed")
with col2:
    buscar = st.button("🔍 Buscar")

# Aplica filtro ao clicar no botão
if buscar and termo_busca:
    df_filtrado = df[df.apply(lambda row: termo_busca.lower() in str(row).lower(), axis=1)]
else:
    df_filtrado = df
st.subheader("📋 Tabela de Agendamentos")
st.dataframe(df_filtrado, use_container_width=True)



