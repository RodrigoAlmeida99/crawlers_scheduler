import streamlit as st
import pandas as pd
import os
from datetime import datetime
from controller import insert_scheduler, refresh_cache, list_schemas, update_schedule
import subprocess
from pathlib import Path
import sys
from streamlit import rerun

# Caminho real da planilha Excel
CACHE_PATH = (Path(__file__).parent / ".." / "cache" / "scheduler_cache.pkl").resolve()
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
    ativos = df[df["status"].astype(str).str.lower() == "ativo"]

    st.metric("Agendamentos Ativos", len(ativos))

# ➕ Formulário para novo agendamento
with st.expander("➕ Novo Agendamento"):
    with st.form("form_novo_agendamento"):
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Nome do Fluxo")
            caminho = st.text_input("Caminho do Script ou FME")
            frequencia = st.selectbox("Periodicidade", ["Diário", "Semanal", "Mensal", "Semestral", "Manual"])
            status = st.selectbox("Status", ["Ativo", "Inativo", "Exec"])
        with col2:
            tabela = st.text_input("Nome da Tabela no Banco", "")
            schemas_disponiveis = list_schemas()
            schema_opcoes = ["Selecione um schema"] + schemas_disponiveis
            schema_banco = st.selectbox("Schema no Banco", schema_opcoes)
            data_inicio = st.date_input("Data de Início")
            hora = st.time_input("Hora de Agendamento")

        enviar = st.form_submit_button("Salvar Agendamento")

        if enviar:
            campos_obrigatorios = [nome, caminho, frequencia, status, data_inicio, hora]
            if not all(campos_obrigatorios):
                st.warning("⚠️ Preencha todos os campos obrigatórios antes de salvar.")
            elif schema_banco == "Selecione um schema":
                st.warning("⚠️ Por favor, selecione um schema válido.")
            else:
                dados = {
                    "fluxo": nome,
                    "caminho": caminho,
                    "tabela_banco": tabela or None,
                    "schema": schema_banco,
                    "data_inicio": data_inicio,
                    "hora": hora,
                    "frequencia": frequencia,
                    "status": status,
                    "ultima_execucao": None
                }

                insert_scheduler(dados)
                refresh_cache()
                st.success(f"✅ Fluxo '{nome}' salvo com sucesso!")
                from streamlit import rerun
                rerun()

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
# Cabeçalho da "tabela"

# Cabeçalho da "tabela"
colunas = st.columns([2, 3, 2, 2, 2, 2, 2, 2, 2])
cabecalhos = ["Fluxo", "Caminho", "Tabela", "Schema", "Início", "Hora", "Frequência", "Status", "Ações"]
for col, titulo in zip(colunas, cabecalhos):
    col.markdown(f"<div style='border-bottom: 1px solid #666; padding-bottom: 4px;'><strong>{titulo}</strong></div>", unsafe_allow_html=True)

# Linhas com dados
for idx, row in df_filtrado.iterrows():
    cols = st.columns([2, 3, 2, 2, 2, 2, 2, 2, 2])

    cols[0].write(row["fluxo"])
    cols[1].write(row["caminho"])
    cols[2].write(row["tabela_banco"] or "-")
    cols[3].write(row["schema"] or "-")
    cols[4].write(str(row["data_inicio"]))
    cols[5].write(str(row["hora"]))
    cols[6].write(row["frequencia"])
    cols[7].write(row["status"])

    col_run, col_edit = cols[8].columns(2)

    # Botão RUN
    if col_run.button("Rodar Agora", key=f"run_{row['id']}"):
        update_schedule(row["id"], {"status": "Exec"})
        st.success("🔁 Agendamento marcado como 'Exec'")
        rerun()

    # Botão EDITAR (ativa edição via session_state)
    editando = st.session_state.get(f"editando_{row['id']}", False)

    if editando:
        if col_edit.button("❌", key=f"cancel_btn_{row['id']}"):
            st.session_state[f"editando_{row['id']}"] = False
            rerun()
    else:
        if col_edit.button("✏️ Editar", key=f"edit_btn_{row['id']}"):
            st.session_state[f"editando_{row['id']}"] = True
            rerun()
    if st.session_state.get(f"editando_{row['id']}", False):
        with st.form(f"form_editar_{row['id']}"):
            st.markdown(f"### ✏️ Editar Agendamento ID {row['id']}")

            novo_fluxo = st.text_input("Fluxo", value=row["fluxo"])
            novo_caminho = st.text_input("Caminho", value=row["caminho"])
            nova_tabela = st.text_input("Tabela no banco", value=row["tabela_banco"] or "")
            novo_schema = st.text_input("Schema", value=row["schema"] or "")
            nova_data = st.date_input("Data de Início", value=row["data_inicio"])
            nova_hora = st.time_input("Hora", value=row["hora"])
            nova_freq = st.selectbox("Frequência", ["Diário", "Semanal", "Mensal", "Semestral", "Manual", "Outro"],
                                     index=["Diário", "Semanal", "Mensal", "Semestral", "Manual", "Outro"].index(row["frequencia"]))
            novo_status = st.selectbox("Status", ["Ativo", "Inativo", "Exec"],
                                       index=["Ativo", "Inativo", "Exec"].index(row["status"]))

            salvar = st.form_submit_button("💾 Salvar")

            if salvar:
                update_schedule(row["id"], {
                    "fluxo": novo_fluxo,
                    "caminho": novo_caminho,
                    "tabela_banco": nova_tabela,
                    "schema": novo_schema,
                    "data_inicio": nova_data,
                    "hora": nova_hora,
                    "frequencia": nova_freq,
                    "status": novo_status
                })
                st.session_state[f"editando_{row['id']}"] = False
                st.success("✅ Agendamento atualizado com sucesso!")
                rerun()