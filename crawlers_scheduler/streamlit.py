import streamlit as st
import pandas as pd
import os
from datetime import datetime
from controller import insert_scheduler, refresh_cache
import subprocess
from pathlib import Path
import sys

# Caminho real da planilha Excel
CACHE_PATH = str(Path(__file__).parent.parent / 'cache'  / 'scheduler_cache.pkl')
CONTROLLER_PATH = str(Path(__file__).parent / 'controller.py')

def load_cache():
    if not os.path.exists(CACHE_PATH):
        print("⚠️ Cache não encontrado. Gerando com controller.py...")
        subprocess.run([sys.executable, CONTROLLER_PATH], check=True)
    
    return pd.read_pickle(CACHE_PATH)


# Configurações da página
st.set_page_config(page_title="Gerenciador de Agendamentos", layout="wide")

st.title("📅 Gerenciador de Agendamentos de Crawlers")

# Carrega os agendamentosx
df = load_cache()

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
            frequencia = st.selectbox("Periodicidade", ["Diário", "Semanal", "Mensal", "Semestral", "Manual", "Outro"])
            tabela = st.text_input("Nome da Tabela no Banco", "")
        with col2:
            status = st.selectbox("Status", ["Ativo", "Inativo", "Exec"])
            schema_banco = st.text_input("Schema no Banco", "")
            data_inicio = st.date_input("Data de Início")
            hora = st.time_input("Hora de Agendamento")

        enviar = st.form_submit_button("Salvar Agendamento")

        if enviar:
            dados = {
                "fluxo": nome,
                "caminho": caminho,
                "tabela_banco": tabela or None,
                "schema": schema_banco or None,
                "data_inicio": data_inicio,
                "hora": hora,
                "frequencia": frequencia,
                "status": status,
                "ultima_execucao": None
            }

            insert_scheduler(dados)      # Insere no banco
            refresh_cache()              # Atualiza o .pkl
            st.success(f"✅ Fluxo '{nome}' salvo com sucesso!")
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



