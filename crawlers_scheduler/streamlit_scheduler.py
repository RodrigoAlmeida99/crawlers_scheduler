import streamlit as st
import pandas as pd
import os
from datetime import datetime
from controller import insert_scheduler, refresh_cache, list_schemas, update_schedule, delete_schedule
import subprocess
from pathlib import Path
from glob import glob
import sys
from streamlit import rerun
import base64
from dotenv import load_dotenv, find_dotenv
import os
from collections import deque

dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

# Caminho real da planilha Excel
CACHE_PATH = (Path(__file__).parent / ".." / "cache" / "scheduler_cache.pkl").resolve()
CONTROLLER_PATH = str(Path(__file__).parent / 'controller.py')

def render_log_modal(log_path: Path):
    """Abre o log em um popover largo (fallback de modal)."""
    if not (isinstance(log_path, Path) and log_path.exists()):
        st.session_state["log_modal_open"] = False
        st.warning("Log não encontrado.")
        return

    # usamos um placeholder para abrir o popover automaticamente
    host = st.empty()
    with host.popover(f"📝 Log — {log_path.name}", use_container_width=True):
        colA, colB, colC, colD = st.columns([1, 1, 2, 1])
        with colA:
            only_err = st.checkbox("Somente erros/avisos", key="log_only_err")
        with colB:
            refresh = st.button("Atualizar")
        with colC:
            st.caption(f"Arquivo: {log_path}")
        with colD:
            close = st.button("Fechar", type="primary")

        st.markdown('<div class="log-modal-header"></div>', unsafe_allow_html=True)
        if refresh:
            st.cache_data.clear()

        texto = _tail_file(log_path, n=2000)
        if only_err:
            texto = "\n".join([ln for ln in texto.splitlines()
                               if any(k in ln for k in ("ERROR|", "FATAL|", "WARN"))])

        st.markdown(
            f'<div class="log-modal-body">{texto or "(log vazio)"}'
            '</div>',
            unsafe_allow_html=True
        )

        with open(log_path, "rb") as f:
            st.download_button(
                "⬇️ Baixar log completo",
                data=f,
                file_name=log_path.name,
                mime="text/plain",
                use_container_width=True
            )

        if close:
            st.session_state["log_modal_open"] = False
            st.session_state["log_modal_path"] = None
            rerun()


def find_latest_log_for(caminho_fmw: str) -> Path | None:
    """
    Retorna o Path do .log mais recente associado ao .fmw informado.
    Usa path_transformer_reader(caminho) para obter o caminho absoluto.
    Regras de busca (na mesma pasta do .fmw):
      - base.log
      - base_*.log
      - base-*.log
      - base*_log.log         (ex.: ore_projection_to_SQL_log.log)
      - base*log.log
    Se não achar, tenta recursivo: **/base*.log
    """
    if not caminho_fmw:
        return None

    # usa seu resolvedor absoluto
    abs_path = path_transformer_reader(str(caminho_fmw))  # <<< usa sua função
    if not abs_path:
        return None

    caminho_norm = os.path.normpath(str(abs_path).strip().replace('"', ''))
    folder = os.path.dirname(caminho_norm)
    if not folder or not os.path.isdir(folder):
        return None

    base_no_ext = os.path.splitext(os.path.basename(caminho_norm))[0]

    # padrões na pasta
    patterns = [
        os.path.join(folder, f"{base_no_ext}.log"),
        os.path.join(folder, f"{base_no_ext}_*.log"),
        os.path.join(folder, f"{base_no_ext}-*.log"),
        os.path.join(folder, f"{base_no_ext}*_log.log"),  # cobre *_log.log (seu caso)
        os.path.join(folder, f"{base_no_ext}*log.log"),   # cobre *log.log genérico
    ]

    candidates: list[Path] = []
    for pat in patterns:
        candidates.extend([Path(p) for p in glob(pat)])

    # fallback recursivo (caso log esteja numa subpasta tipo "logs")
    if not candidates:
        rec_pat = os.path.join(folder, "**", f"{base_no_ext}*.log")
        candidates.extend([Path(p) for p in glob(rec_pat, recursive=True)])

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)

def _tail_file(path: Path, n: int = 200, encoding: str = "utf-8") -> str:
    """Lê apenas as últimas n linhas de um arquivo, de forma eficiente."""
    dq = deque(maxlen=n)
    with path.open("r", encoding=encoding, errors="replace") as f:
        for line in f:
            dq.append(line.rstrip("\n"))
    return "\n".join(dq)


def path_transformer_reader(caminho_original: str) -> Path:
    """
    Resolve o caminho do fluxo .fmw (ou qualquer arquivo base para localizar o .log) considerando:
    - variações OneDrive / bibliotecas PT/EN
    - mapeamento bidirecional entre:
        LEGACY: "Alvarez and Marsal\\General - Market Intelligence & Research\\04. Crawlers\\Fluxos"
        NOVO:   "Alvarez and Marsal\\Market Intelligence & Research - Fluxos"
    Em caso de falha, retorna o caminho limpo original (para diagnóstico) e
    no chamador você trata a inexistência.
    """
    import re

    def _clean_seg(s: str) -> str:
        return re.sub(r"\s{2,}", " ", s.strip())

    def _clean_parts(p: Path) -> Path:
        return Path(*[_clean_seg(seg) for seg in p.parts])

    def _casefold_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_clean_seg(s).casefold() for s in parts)

    def _find_subseq(haystack: tuple[str, ...], needle: tuple[str, ...]) -> int | None:
        H = _casefold_parts(haystack)
        N = _casefold_parts(needle)
        if not N or len(N) > len(H):
            return None
        for i in range(len(H) - len(N) + 1):
            if H[i:i+len(N)] == N:
                return i
        return None

    def _replace_subseq(parts: tuple[str, ...], old: tuple[str, ...], new: tuple[str, ...]) -> tuple[str, ...]:
        idx = _find_subseq(parts, old)
        if idx is None:
            return parts
        return parts[:idx] + new + parts[idx+len(old):]

    raw = str(caminho_original).strip().strip('"').strip("'")
    p_in = _clean_parts(Path(raw))

    # 0) se já existe, retorna direto
    if p_in.exists():
        return p_in

    partes = tuple(p_in.parts)

    # ancora em "Alvarez and Marsal"
    idx_company = None
    for i, seg in enumerate(partes):
        if "alvarez and marsal" in _clean_seg(seg).casefold():
            idx_company = i
            break
    if idx_company is None:
        # sem âncora → devolve como está (quem chamou decide o que fazer)
        return p_in

    # Prefixos
    LEGACY_PREFIX = (
        "Alvarez and Marsal",
        "General - Market Intelligence & Research",
        "04. Crawlers",
        "Fluxos",
    )
    NEW_PREFIX = (
        "Alvarez and Marsal",
        "Market Intelligence & Research - Fluxos",
    )

    LIB_PT = "Documentos - Market Intelligence & Research"
    LIB_EN = "Market Intelligence & Research - Documents"

    rel_from_company_inclusive = partes[idx_company:]        # inclui empresa
    rel_from_company_exclusive = partes[idx_company + 1:]    # exclui empresa

    def _with_prefix_swaps(base_rel: tuple[str, ...]) -> set[Path]:
        cand = set()
        # como veio
        cand.add(Path(*base_rel))

        # Se já inclui a empresa, tentamos substituições in-place
        if base_rel and "alvarez and marsal" in _clean_seg(base_rel[0]).casefold():
            cand.add(Path(*_replace_subseq(base_rel, LEGACY_PREFIX, NEW_PREFIX)))
            cand.add(Path(*_replace_subseq(base_rel, NEW_PREFIX, LEGACY_PREFIX)))
        else:
            # se não inclui, tentamos prefixar dos dois jeitos
            cand.add(Path(*NEW_PREFIX, *base_rel))
            cand.add(Path(*LEGACY_PREFIX, *base_rel))

        # swaps de biblioteca PT/EN
        def _swap_libs(parts_t: tuple[str, ...]) -> set[tuple[str, ...]]:
            out = {parts_t}
            cf = _casefold_parts(parts_t)
            for i, s in enumerate(cf):
                if s == _clean_seg(LIB_PT).casefold():
                    tmp = list(parts_t); tmp[i] = LIB_EN; out.add(tuple(tmp))
                if s == _clean_seg(LIB_EN).casefold():
                    tmp = list(parts_t); tmp[i] = LIB_PT; out.add(tuple(tmp))
            return out

        with_lib_swaps = set()
        for path_obj in list(cand):
            t = tuple(path_obj.parts)
            for swapped_t in _swap_libs(t):
                with_lib_swaps.add(Path(*swapped_t))

        cand = cand.union(with_lib_swaps)
        return {_clean_parts(p) for p in cand}

    rel_variants: set[Path] = set()
    for base_rel in (rel_from_company_inclusive, rel_from_company_exclusive):
        rel_variants |= _with_prefix_swaps(base_rel)

    # raízes prováveis
    roots: list[Path] = []
    odc = os.environ.get("OneDriveCommercial")
    od  = os.environ.get("OneDrive")
    if odc: roots.append(Path(odc).expanduser())
    if od:  roots.append(Path(od).expanduser())
    roots.append((Path.home() / "OneDrive - Alvarez and Marsal").expanduser())
    roots.append((Path.home() / "Alvarez and Marsal").expanduser())
    roots.append(Path.home().expanduser())

    tested: list[str] = []
    for root in roots:
        for rel in rel_variants:
            # evita duplicar "Alvarez and Marsal" no caminho final
            if ("alvarez and marsal" in root.name.casefold()
                and len(rel.parts) > 0
                and "alvarez and marsal" in rel.parts[0].casefold()):
                candidate = root.parent / Path(*rel.parts[1:])
            else:
                candidate = root / rel
            candidate = _clean_parts(candidate)
            tested.append(str(candidate))
            if candidate.exists():
                return candidate

    # fallback: procura por filename (útil quando recebemos apenas o .fmw)
    try:
        filename = p_in.name
        if filename:
            for base in [r for r in roots if "alvarez and marsal" in r.as_posix().casefold()]:
                for hit in base.rglob(filename):
                    return _clean_parts(hit)
    except Exception:
        pass

    # Sem sucesso: devolve o original normalizado (o chamador pode diagnosticar)
    return p_in


def path_transformer(caminho_completo):
    # Remove aspas e normaliza separadores
    caminho_limpo = caminho_completo.strip().replace('"', '')
    caminho_normalizado = os.path.normpath(caminho_limpo)

    # Quebra em partes (agora funciona mesmo com barra invertida)
    partes = caminho_normalizado.split(os.sep)

    try:
        idx = next(i for i, parte in enumerate(partes) if "Alvarez and Marsal" in parte)
        partes_filtradas = partes[idx:]  # Mantém da pasta desejada em diante
        return os.path.join(*partes_filtradas)
    except StopIteration:
        return caminho_normalizado



def load_cache():
    if not os.path.exists(CACHE_PATH):
        print("⚠️ Cache não encontrado. Gerando com controller.py...")
        subprocess.run([sys.executable, CONTROLLER_PATH], check=True)
    
    return pd.read_pickle(CACHE_PATH)


# Configurações da página
st.set_page_config(page_title="Gerenciador de Agendamentos", layout="wide")


logo_path = Path(__file__).parent / ".." / "assets" / "A&M_Corporate_White.png"
def get_base64_image(image_path):
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

logo_base64 = get_base64_image(logo_path)
st.markdown(
    f"""
    <div style='display: flex; align-items: center; gap: 15px; margin-bottom: 20px;'>
        <img src="data:image/png;base64,{logo_base64}" width="50">
        <h1 style='margin: 0; padding: 0;'>Gerenciador de Agendamentos de Crawlers</h1>
    </div>
    """,
    unsafe_allow_html=True
)


# --- Estado para controle do modal de log ---
if "log_modal_open" not in st.session_state:
    st.session_state["log_modal_open"] = False
if "log_modal_path" not in st.session_state:
    st.session_state["log_modal_path"] = None

# --- CSS para modal mais largo e header “flutuante” ---
st.markdown("""
<style>
/* Popover largo (simula modal) */
div[data-testid="stPopover"] div[role="dialog"] {
  width: 90vw !important;
  max-width: 1200px !important;
}

/* Cabeçalho fixo e corpo com rolagem */
.log-modal-header {
  position: sticky;
  top: 0;
  background: var(--background-color);
  padding: 0.5rem 0;
  z-index: 10;
  border-bottom: 1px solid rgba(128,128,128,0.2);
}
.log-modal-body {
  max-height: 65vh;
  overflow: auto;
  border: 1px solid rgba(128,128,128,0.25);
  border-radius: 8px;
  padding: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12.5px;
  white-space: pre-wrap;
}
</style>
""", unsafe_allow_html=True)


# Carrega os agendamentosx
df = load_cache()



# 🔷 Card com total de agendamentos
col1, col2 = st.columns(2)
with col1:
    st.metric("Total de Agendamentos", len(df))
with col2:
    ativos = df[df["status"].astype(str).str.lower() == "ativo"]

    st.metric("Agendamentos Ativos", len(ativos))
# ➕ Formulário para novo agendamento (layout corrigido)
industries = [
    "Agribusiness",
    "Cities/Social Infra",
    "Cross-Industry",
    "Data Centers",
    "Energy",
    "Logistics",
    "Manufacture",
    "Macroeconomics",
    "Mining & Metals",
    "Oil & Gas and Renewables",
    "Real Estate",
    "Sanitation & Waste Management",
    "Telecommunications",
    "Not Applicable",
]

with st.expander("➕ Novo Agendamento"):
    # estado para múltiplas tabelas
    if "novo_ag_tables_count" not in st.session_state:
        st.session_state["novo_ag_tables_count"] = 1  # pelo menos 1 campo

    # ── Cabeçalho das Tabelas + Ações (fora do form, mas DENTRO do expander) ──
    col_space, col_title, col_add, col_rem = st.columns([1, 1.4, 0.9, 0.9])
    with col_space:
        st.empty()  # coluna “espelho” para alinhar com o schema
    with col_title:
        st.markdown("**Tabelas de destino (uma por campo)**")
    with col_add:
        add_tbl = st.button(
            "➕ Incluir mais uma",
            key="btn_add_tbl_novo",
            help="Adicionar mais um campo de tabela (não envia o formulário)",
            use_container_width=True,
        )
    with col_rem:
        rem_tbl = st.button(
            "➖ Remover último",
            key="btn_rem_tbl_novo",
            help="Remover o último campo de tabela (não envia o formulário)",
            use_container_width=True,
        )

    # handlers dos botões (não repita estes blocos)
    if add_tbl:
        st.session_state["novo_ag_tables_count"] = min(50, st.session_state["novo_ag_tables_count"] + 1)
    if rem_tbl:
        last_idx = st.session_state["novo_ag_tables_count"] - 1
        if last_idx > 0:
            last_key = f"novo_tbl_{last_idx}"
            if last_key in st.session_state:
                del st.session_state[last_key]
            st.session_state["novo_ag_tables_count"] = max(1, last_idx)

    # ── FORM (sempre renderiza) ────────────────────────────────────────────────
    with st.form("form_novo_agendamento", clear_on_submit=True):
        # linha superior
        c1, c2 = st.columns(2)
        with c1:
            nome = st.text_input("Nome do Fluxo")
            caminho = st.text_input("Caminho do Script ou FME")
            frequencia = st.selectbox("Periodicidade", ["Diário", "Semanal", "Mensal", "Semestral", "Manual"])
            status = st.selectbox("Status", ["Ativo", "Inativo", "Exec"])
        with c2:
            industry = st.selectbox("Industry", industries, index=industries.index("Not Applicable"))
            data_inicio = st.date_input("Data de Início")
            hora = st.time_input("Hora de Agendamento")

        st.divider()

        # parte de baixo: schema (esq.) + múltiplas tabelas (dir.)
        b1, b2 = st.columns([1, 1])
        with b1:
            schemas_disponiveis = list_schemas() or []
            extra_schemas = ["data_lake"]  # <<< adiciona aqui os schemas “extras”
            # une, deduplica e ordena case-insensitive
            schemas_merged = sorted(set(schemas_disponiveis) | set(extra_schemas), key=str.lower)
            schema_opcoes = ["Selecione um schema"] + schemas_merged
            schema_banco = st.selectbox("Schema no Banco", schema_opcoes)
        with b2:
            tabelas_inputs = []
            for i in range(st.session_state["novo_ag_tables_count"]):
                key = f"novo_tbl_{i}"
                tabelas_inputs.append(
                    st.text_input(
                        f"Tabela {i+1}",
                        key=key,
                        placeholder="ex.: market_intelligence.minha_tabela"
                    )
                )

        enviar = st.form_submit_button("Salvar Agendamento")

        if enviar:
            # validações
            campos_obrigatorios = [nome, caminho, frequencia, status, data_inicio, hora, industry]
            if not all(campos_obrigatorios):
                st.warning("⚠️ Preencha todos os campos obrigatórios antes de salvar.")
            elif schema_banco == "Selecione um schema":
                st.warning("⚠️ Por favor, selecione um schema válido.")
            else:
                tabelas_limpo = [t.strip() for t in tabelas_inputs if t and t.strip()]
                tabela_csv = ", ".join(tabelas_limpo) if tabelas_limpo else None

                dados = {
                    "fluxo": nome,
                    "caminho": path_transformer(caminho),
                    "tabela_banco": tabela_csv,   # múltiplas tabelas → CSV
                    "schema": schema_banco,
                    "data_inicio": data_inicio,
                    "hora": hora,
                    "frequencia": frequencia,
                    "status": status,
                    "industry": industry,
                    "ultima_execucao": None,
                }

                insert_scheduler(dados)
                refresh_cache()
                st.cache_data.clear()

                # reset após salvar
                st.session_state["novo_ag_tables_count"] = 1
                for k in [k for k in st.session_state.keys() if k.startswith("novo_tbl_")]:
                    del st.session_state[k]

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

df_tree = df_filtrado.copy()
df_tree.columns = df_tree.columns.str.strip()
# Cabeçalho da "tabela"

# ========== NOVO BLOCO: TREE VIEW + DETALHES ==========
st.subheader("Agendamentos")

# Seleção atual no estado da sessão
if "selected_id" not in st.session_state:
    st.session_state["selected_id"] = None

# Layout 25% / 75%
left, right = st.columns([1, 3])

with left:
    st.markdown("### Navegação")
    if df_filtrado.empty:
        st.info("Nenhum item encontrado com o filtro atual.")
    else:
        # --- NOVO: separa erros do restante ---
        df_nav = df_filtrado.copy()
        mask_err = df_nav["status"].astype(str).str.casefold() == "erro"
        erro_df = df_nav[mask_err]
        ok_df   = df_nav[~mask_err]

        # Seção especial para ERROS (não organiza por industry)
        if not erro_df.empty:
            with st.expander("❗ Erros", expanded=False):
                # opcional: ordenar por schema e nome do fluxo
                for _, r in erro_df.sort_values(["schema", "fluxo"], na_position="last").iterrows():
                    leaf_key = f"leaf_err_{r.get('id', _)}"
                    label = f"🧩 {r['fluxo']} — {r.get('schema', '(sem schema)') or '(sem schema)'}"
                    if st.button(label, key=leaf_key, use_container_width=True):
                        st.session_state["selected_id"] = r.get("id", None)
                        from streamlit import rerun
                        rerun()

        # Árvore normal para itens NÃO ERRO (industry -> schema -> fluxo)
        for ind, df_ind in ok_df.groupby("industry", dropna=False):
            with st.expander(f"🏭 {ind or '(sem industry)'}", expanded=False):
                for sch, df_sch in df_ind.groupby("schema", dropna=False):
                    sch_label = f"🗂️ {sch or '(sem schema)'}"
                    with st.popover(sch_label, use_container_width=True):
                        for _, r in df_sch.iterrows():
                            leaf_key = f"leaf_{r.get('id', _)}"
                            if st.button(f"🧩 {r['fluxo']}", key=leaf_key):
                                st.session_state["selected_id"] = r.get("id", None)
                                from streamlit import rerun
                                rerun()

                                
with right:
    st.markdown("### 🧾 Detalhes do Fluxo")
    sel_id = st.session_state.get("selected_id", None)
    if sel_id is None:
        st.info("Selecione um fluxo na árvore à esquerda para ver os detalhes.")
    else:
        row_sel = df_filtrado.loc[df_filtrado["id"] == sel_id]
        if row_sel.empty:
            st.warning("O item selecionado não está no filtro atual.")
        else:
            row = row_sel.iloc[0]

            # Menu (3 pontinhos) no canto superior direito
            _menu_l, _menu_r = st.columns([11, 1])
            with _menu_r:
                with st.popover("⋮", use_container_width=True):
                    st.caption("Ações")
                    if st.button("Excluir agendamento", key=f"del_{row['id']}"):
                        try:
                            delete_schedule(int(row["id"]))
                            st.cache_data.clear()
                            st.session_state["selected_id"] = None
                            st.success("Agendamento excluído com sucesso.")
                            rerun()
                        except Exception as e:
                            st.error(f"Erro ao excluir: {e}")

            # Cabeçalho + status
            st.markdown(f"#### **{row['fluxo']}**")
            st.caption(f"Industry: {row.get('industry', '-')}")

            # --- NOVO: Tabelas em bullet points logo abaixo do Industry ---
            schema_val = str(row.get("schema", "") or "")
            raw_tables = str(row.get("tabela_banco", "") or "")
            tables = [t.strip() for t in raw_tables.split(",") if t.strip()]

            if tables:
                st.markdown("##### Tabelas")
                # se quiser prefixar o schema quando não informado na string, descomente a próxima linha:
                # tables = [t if "." in t else f"{schema_val}.{t}" for t in tables]
                bullets = "\n".join([f"- `{t}`" for t in tables])
                st.markdown(bullets)
            else:
                st.caption("— Sem tabelas definidas —")

            st.write("---")

            # Grid de metadados
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Status", str(row.get("status","-")))

                     # >>> bloco status details (logs)
            log_col1, log_col2 = st.columns([1, 5])
            with log_col1:
                ver_log = st.button("📄 Ver log recente", key=f"viewlog_{row['id']}",
                                    help="Abrir o log mais recente do fluxo")

            # abre modal (overlay central) com o log
            if ver_log:
                latest = find_latest_log_for(str(row.get("caminho", "")))
                if isinstance(latest, Path) and latest.exists():
                    st.session_state["log_modal_open"] = True
                    st.session_state["log_modal_path"] = latest
                    rerun()
                else:
                    st.warning("Não foi possível localizar o log (.log com o mesmo nome/sufixo do fluxo).")
                    # (mantém seu diagnóstico atual aqui, se quiser)

            # renderiza modal se marcado
            if st.session_state.get("log_modal_open") and st.session_state.get("log_modal_path"):
                render_log_modal(st.session_state["log_modal_path"])


            m2.metric("Frequência", str(row.get("frequencia","-")))
            m3.metric("Início", str(row.get("data_inicio","-")))
            m4.metric("Hora", str(row.get("hora","-")))

            st.markdown("##### Caminho")
            st.code(str(row.get("caminho","-")), language="text")

            st.markdown("##### Última Execução")
            st.write(str(row.get("ultima_execucao","-")))

            st.write("---")

   
            # Ações
            a1, a2, a3 = st.columns([1,1,2])
            with a1:
                if st.button("▶️ Rodar agora"):
                    update_schedule(int(row["id"]), {"status": "Exec"})
                    st.success("🔁 Agendamento marcado como 'Exec'")
                    from streamlit import rerun
                    rerun()
            with a2:
                if st.button("✏️ Editar"):
                    st.session_state[f"editando_{row['id']}"] = True
                    from streamlit import rerun
                    rerun()

            # --- LISTA FIXA DE INDUSTRIES (reusa a do "Novo Agendamento" se já existir) ---
            industries = globals().get("industries") or [
                "Agribusiness",
                "Cities/Social Infra",
                "Cross-Industry",
                "Data Centers",
                "Energy",
                "Logistics",
                "Manufacture",
                "Macroeconomics",
                "Mining & Metals",
                "Oil & Gas and Renewables",
                "Real Estate",
                "Sanitation & Waste Management",
                "Telecommunications",
                "Not Applicable",
            ]

            if st.session_state.get(f"editando_{row['id']}", False):
                with st.form(f"form_editar_{row['id']}"):
                    st.markdown(f"### ✏️ Editar Agendamento ID {row['id']}")

                    novo_fluxo = st.text_input("Fluxo", value=row["fluxo"])
                    novo_caminho = st.text_input("Caminho", value=row["caminho"])
                    nova_tabela = st.text_input("Tabelas", value=row["tabela_banco"] or "")
                    novo_schema = st.text_input("Schema", value=row["schema"] or "")
                    nova_data = st.date_input("Data de Início", value=row["data_inicio"])
                    nova_hora = st.time_input("Hora", value=row["hora"])

                    # Opções seguras + índice tolerante
                    freq_options = ["Diário", "Semanal", "Mensal", "Semestral", "Manual", "Outro"]
                    current_freq = str(row.get("frequencia") or "Manual")
                    freq_index = freq_options.index(current_freq) if current_freq in freq_options else freq_options.index("Manual")
                    nova_freq = st.selectbox("Frequência", freq_options, index=freq_index)

                    status_options = ["Ativo", "Inativo", "Exec", "Erro"]  # <- vírgula corrigida + inclui 'Erro'
                    current_status = str(row.get("status") or "Inativo")
                    status_index = status_options.index(current_status) if current_status in status_options else status_options.index("Inativo")
                    novo_status = st.selectbox("Status", status_options, index=status_index)

                    # Industry fixo
                    current_industry = str(row.get("industry") or "Not Applicable")
                    ind_index = industries.index(current_industry) if current_industry in industries else industries.index("Not Applicable")
                    novo_industry = st.selectbox("Industry", industries, index=ind_index)

                    st.write("---")
                    bsave, bcancel = st.columns([1, 1])
                    salvar = bsave.form_submit_button("💾 Salvar")
                    cancelar = bcancel.form_submit_button("Cancelar")

                    if cancelar:
                        st.session_state[f"editando_{row['id']}"] = False
                        from streamlit import rerun
                        rerun()

                    if salvar:
                        if not str(novo_industry).strip():
                            st.warning("⚠️ O campo 'Industry' é obrigatório.")
                        else:
                            update_schedule(int(row["id"]), {
                                "fluxo": novo_fluxo,
                                "caminho": novo_caminho,
                                "tabela_banco": (nova_tabela or "").strip() or None,
                                "schema": novo_schema,
                                "data_inicio": nova_data,
                                "hora": nova_hora,
                                "frequencia": nova_freq,
                                "status": novo_status,
                                "industry": novo_industry,
                            })
                            st.session_state[f"editando_{row['id']}"] = False
                            st.success("✅ Agendamento atualizado com sucesso!")
                            from streamlit import rerun
                            rerun()


with st.expander("📘 Tutorial: Como agendar um fluxo", expanded=False):
    st.markdown(
        """
        ### ✅ Passo a passo para agendar um fluxo

        **1. Salvar o fluxo no SharePoint**
        - Acesse a pasta de projetos no SharePoint:  
          `Alvarez and Marsal\\Market Intelligence & Research - Documents\\General\\04. Crawlers\\Fluxos`
        - Salve o arquivo FME (`.fmw`) na pasta apropriada.
        - Copie o **caminho completo** do arquivo e guarde como referência.

        **2. Registrar o fluxo na interface**
        - Clique em **"Novo Agendamento"**.
        - Preencha os campos:
          - Nome do fluxo  
          - Caminho do arquivo `.fmw`  
            *(ex: `C:\\Users\\user\\Alvarez and Marsal\\Market Intelligence & Research - Documents\\General\\04. Crawlers\\Fluxos\\arquivo.fmw`)*  
          - Schema e tabela no banco  
          - Horário e frequência de execução
        - Clique em **Salvar Agendamento** ✅
        """
    )
