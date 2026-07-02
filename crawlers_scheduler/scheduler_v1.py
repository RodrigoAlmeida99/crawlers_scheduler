import pandas as pd
import subprocess
import time
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine
from controller import refresh_cache, update_schedule
import os
import sys
import pytz
import unicodedata
import logging
from logging.handlers import RotatingFileHandler
import traceback

# === LOGGING CONFIG ===
LOG_DIR = (Path(__file__).parent.parent / 'logs')
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / 'scheduler.log'

logger = logging.getLogger("scheduler")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=3, encoding='utf-8')
formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
handler.setFormatter(formatter)
logger.handlers.clear()
logger.addHandler(handler)
logger.propagate = False  # garante que nada “vaze” e duplique

CACHE_PATH = str(Path(__file__).parent.parent / 'cache' / 'scheduler_cache.pkl')
CONTROLLER_PATH = str(Path(__file__).parent / 'controller.py')
FME_EXE = r"C:\Program Files\FME-Form\fme.exe"

# Fila e limite global
process_queue = []
MAX_CONCURRENT = 2

# Mapa de processos por agendamento
running = {}  # { schedule_id: {"proc": Popen, "log": Path, "started_at": datetime} }

def load_cache():
    if not os.path.exists(CACHE_PATH):
        logger.info("Cache não encontrado. Gerando com controller.py...")
        try:
            subprocess.run([sys.executable, CONTROLLER_PATH], check=True)
        except Exception:
            logger.exception("Falha ao gerar cache via controller.py")
            raise
    try:
        df = pd.read_pickle(CACHE_PATH)
        return df
    except Exception:
        logger.exception("Falha ao ler o CACHE_PATH")
        raise

def _norm(s: str) -> str:
    """Normaliza string: tira acento, põe em minúsculo e remove espaços extras"""
    if s is None:
        return ''
    s = str(s).strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return s

def reap_running():
    global running
    finished = []
    for sid, info in list(running.items()):
        p = info["proc"]
        rc = p.poll()
        if rc is not None:  # processo terminou
            logger.info(f"[id={sid}] FME terminou com exit_code={rc}, log={info['log']}")
            try:
                update_schedule(sid, {'status': 'Ativo' if rc == 0 else 'Erro'})
            except Exception:
                logger.exception(f"[id={sid}] Falha ao atualizar status após término")
            finished.append(sid)
            try:
                # fecha handle do log se ainda estiver aberto
                if hasattr(info, "f_out"):
                    f = info["f_out"]
                    try:
                        f.flush()
                        f.close()
                    except Exception:
                        pass
            except Exception:
                pass
    for sid in finished:
        running.pop(sid, None)

def path_transformer(caminho_original: str) -> Path:
    """
    Resolve o caminho do fluxo .fmw considerando:
    - variações OneDrive / bibliotecas PT/EN (como antes)
    - novo layout de sync no servidor: após "Alvarez and Marsal" vem diretamente
      "Market Intelligence & Research - Fluxos"
    - mapeamento bidirecional entre o prefixo "General - Market Intelligence & Research\\04. Crawlers\\Fluxos"
      e "Market Intelligence & Research - Fluxos"
    Em caso de falha, levanta ValueError com amostra dos candidatos testados.
    """
    import re

    def _clean_seg(s: str) -> str:
        # normaliza espaços internos múltiplos e tira espaços nas pontas
        return re.sub(r"\s{2,}", " ", s.strip())

    def _clean_parts(p: Path) -> Path:
        return Path(*[_clean_seg(seg) for seg in p.parts])

    def _casefold_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_clean_seg(s).casefold() for s in parts)

    def _find_subseq(haystack: tuple[str, ...], needle: tuple[str, ...]) -> int | None:
        """Retorna índice inicial onde 'needle' ocorre em 'haystack' (case-insensitive), ou None."""
        H = _casefold_parts(haystack)
        N = _casefold_parts(needle)
        if not N or len(N) > len(H):
            return None
        for i in range(len(H) - len(N) + 1):
            if H[i:i+len(N)] == N:
                return i
        return None

    def _replace_subseq(parts: tuple[str, ...], old: tuple[str, ...], new: tuple[str, ...]) -> tuple[str, ...]:
        """Substitui a primeira ocorrência de 'old' por 'new' (case-insensitive)."""
        idx = _find_subseq(parts, old)
        if idx is None:
            return parts
        return parts[:idx] + new + parts[idx+len(old):]

    raw = str(caminho_original).strip().strip('"').strip("'")
    p_in = _clean_parts(Path(raw))

    if p_in.exists():
        return p_in

    partes = tuple(p_in.parts)

    # Descobre a posição de "Alvarez and Marsal" (referência)
    idx_company = None
    for i, seg in enumerate(partes):
        if "alvarez and marsal" in _clean_seg(seg).casefold():
            idx_company = i
            break

    # Se não encontrou o ponto de ancoragem, devolve p_in (para logging/erro posterior)
    if idx_company is None:
        return p_in

    # --- Prefixos antigos x novos (subcaminhos após a empresa) ---
    # A) formato antigo (como salvo no banco)
    LEGACY_PREFIX = (
        "Alvarez and Marsal",
        "General - Market Intelligence & Research",
        "04. Crawlers",
        "Fluxos",
    )
    # B) formato novo (sync do servidor)
    NEW_PREFIX = (
        "Alvarez and Marsal",
        "Market Intelligence & Research - Fluxos",
    )

    # Também manter as bibliotecas PT/EN usadas no seu código original
    LIB_PT = "Documentos - Market Intelligence & Research"
    LIB_EN = "Market Intelligence & Research - Documents"

    # Prepara uma lista de variantes relativas a partir do ponto da empresa
    rel_from_company_inclusive = partes[idx_company:]        # inclui "Alvarez and Marsal"
    rel_from_company_exclusive = partes[idx_company + 1:]    # exclui a empresa

    # Gera candidatos trocando entre LEGACY_PREFIX <-> NEW_PREFIX
    def _with_prefix_swaps(base_rel: tuple[str, ...]) -> set[Path]:
        cand = set()

        # 1) como está
        cand.add(Path(*base_rel))

        # 2) se começar por LEGACY (após a empresa), trocar por NEW
        if base_rel and "alvarez and marsal" in _clean_seg(base_rel[0]).casefold():
            # match a partir da empresa (sequência inclusiva)
            swapped = _replace_subseq(base_rel, LEGACY_PREFIX, NEW_PREFIX)
            cand.add(Path(*swapped))
        else:
            # caso base_rel NÃO inclua a empresa, tentamos com ambos prefixos
            cand.add(Path(*NEW_PREFIX, *base_rel))
            cand.add(Path(*LEGACY_PREFIX, *base_rel))

        # 3) bidirecional: se estiver no NEW, trocar por LEGACY
        cand.add(Path(*_replace_subseq(base_rel, NEW_PREFIX, LEGACY_PREFIX)))

        # 4) variantes de biblioteca PT/EN dentro do caminho (quando presentes)
        def _swap_libs(parts_t: tuple[str, ...]) -> set[tuple[str, ...]]:
            out = {parts_t}
            cf = _casefold_parts(parts_t)
            for i, s in enumerate(cf):
                if s == _clean_seg(LIB_PT).casefold():
                    tmp = list(parts_t); tmp[i] = LIB_EN; out.add(tuple(tmp))
                if s == _clean_seg(LIB_EN).casefold():
                    tmp = list(parts_t); tmp[i] = LIB_PT; out.add(tuple(tmp))
            return out

        # aplica variação PT/EN em cada candidato
        with_lib_swaps = set()
        for path_obj in list(cand):
            t = tuple(path_obj.parts)
            for swapped_t in _swap_libs(t):
                with_lib_swaps.add(Path(*swapped_t))

        cand = cand.union(with_lib_swaps)
        return {_clean_parts(p) for p in cand}

    rel_variants = set()
    for base_rel in (rel_from_company_inclusive, rel_from_company_exclusive):
        for v in _with_prefix_swaps(base_rel):
            rel_variants.add(v)

    # Raízes possíveis (como no seu código original)
    roots = []
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
            # Se root já contém "Alvarez and Marsal" e rel também começa com isso, evite duplicar
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

    # fallback: varrer por filename dentro das raízes que contenham "Alvarez and Marsal"
    try:
        filename = p_in.name
        if filename:
            for base in [r for r in roots if "alvarez and marsal" in r.as_posix().casefold()]:
                for hit in base.rglob(filename):
                    return _clean_parts(hit)
    except Exception:
        pass

    raise ValueError(
        "Não consegui resolver o caminho (considerando os novos prefixos). "
        "Últimos candidatos testados (amostra): " + "; ".join(tested[:10])
    )

def exec_bat_file_checker(line, now):
    """
    Decide SE deve disparar este agendamento.
    Normaliza 'frequencia' por _norm (diario, semanal, mensal, semestral).
    """
    schedule_id = line['id']

    status_norm = _norm(line.get('status', ''))
    if status_norm == 'executando' or schedule_id in running:
        return False

    # frequencia normalizada sem acentos
    freq = _norm(line.get('frequencia', 'manual'))
    # hora alvo
    try:
        schedule_time = pd.to_datetime(str(line['hora'])).time()
    except Exception:
        logger.warning(f"[id={schedule_id}] Hora inválida: {line.get('hora')}. Não dispara.")
        return False

    # rotas de status explícito
    if status_norm == 'inativo':
        return False
    if status_norm == 'exec':
        # NÃO mudar pra 'Ativo' aqui; vamos só sinalizar disparo
        return True

    # primeira execução: usa data_inicio + hora
    last = line.get('ultima_execucao')
    try:
        if pd.isnull(last):
            schedule_str = f"{line['data_inicio']} {line['hora']}"
            schedule = pd.to_datetime(schedule_str, errors='coerce')
            if schedule is None or pd.isnull(schedule):
                logger.warning(f"[id={schedule_id}] data_inicio/hora inválidos: {line.get('data_inicio')} {line.get('hora')}")
                return False
            # localiza se estiver naive
            if schedule.tzinfo is None or schedule.tzinfo.utcoffset(schedule) is None:
                schedule = pytz.timezone('America/Sao_Paulo').localize(schedule)
            return schedule <= now
    except Exception:
        logger.exception(f"[id={schedule_id}] Erro calculando primeira execução")
        return False

    # parse last
    try:
        last = pd.to_datetime(last)
    except Exception:
        logger.warning(f"[id={schedule_id}] ultima_execucao inválida: {last}")
        return False

    # regras por frequência
    if freq == 'manual':
        return False
    if freq == 'diario':
        return (now.time() >= schedule_time) and (last.date() < now.date())
    if freq == 'semanal':
        mesma_semana = last.isocalendar()[1] == now.isocalendar()[1] and last.year == now.year
        mesmo_dia_semana = last.weekday() == now.weekday()
        return (mesmo_dia_semana and not mesma_semana and now.time() >= schedule_time)
    if freq == 'mensal':
        mesmo_mes = (last.month == now.month and last.year == now.year)
        # data_inicio pode ser string
        try:
            di = pd.to_datetime(line['data_inicio'])
            dia_alvo = int(di.day)
        except Exception:
            dia_alvo = now.day  # fallback conservador
        return (not mesmo_mes) and (now.day == dia_alvo) and (now.time() >= schedule_time)
    if freq == 'semestral':
        meses_passados = (now.year - last.year) * 12 + (now.month - last.month)
        try:
            di = pd.to_datetime(line['data_inicio'])
            dia_alvo = int(di.day)
        except Exception:
            dia_alvo = now.day
        return (meses_passados >= 6) and (now.day == dia_alvo) and (now.time() >= schedule_time)

    # frequência desconhecida → não dispara
    logger.warning(f"[id={schedule_id}] Frequencia desconhecida: {line.get('frequencia')}")
    return False

def execute_with_queue(caminho_fluxo, schedule_id, now):
    global process_queue, running

    # Limpa processos concluídos
    process_queue = [p for p in process_queue if p.poll() is None]

    while len(process_queue) >= MAX_CONCURRENT:
        logger.info(f"[Fila] cheia ({len(process_queue)}). Aguardando vaga...")
        time.sleep(2)
        process_queue = [p for p in process_queue if p.poll() is None]

    try:
        # 0) valida FME_EXE
        if not Path(FME_EXE).exists():
            logger.error(f"[id={schedule_id}] FME_EXE não encontrado: {FME_EXE}")
            update_schedule(schedule_id, {'status': 'Erro'})
            return False

        # 1) resolve caminho
        try:
            caminho_fluxo_resolvido = path_transformer(caminho_fluxo)
        except Exception as e:
            logger.error(f"[id={schedule_id}] path_transformer falhou para '{caminho_fluxo}': {e}")
            update_schedule(schedule_id, {'status': 'Erro'})
            return False

        if not caminho_fluxo_resolvido.exists():
            logger.error(f"[id={schedule_id}] Arquivo .fmw não encontrado: {caminho_fluxo_resolvido}")
            update_schedule(schedule_id, {'status': 'Erro'})
            return False

        comando = [FME_EXE, str(caminho_fluxo_resolvido)]
        cwd = str(caminho_fluxo_resolvido.parent)
        logger.info(f"[id={schedule_id}] Disparando FME | cmd={' '.join(comando)} | cwd={cwd}")

        run_ts = now.strftime("%Y%m%d-%H%M%S")
        flow_name = Path(caminho_fluxo_resolvido).stem
        flow_log = (LOG_DIR / f"fme_{schedule_id}_{flow_name}_{run_ts}.log")
        f_out = open(flow_log, "a", encoding="utf-8", buffering=1)

        CREATE_NO_WINDOW = 0x08000000
        processo = subprocess.Popen(
            comando,
            shell=False,
            stdout=f_out,
            stderr=f_out,
            cwd=cwd,
            creationflags=CREATE_NO_WINDOW
        )

        # Marcar como executando APÓS Popen OK
        try:
            update_schedule(schedule_id, {'status': 'Executando', 'ultima_execucao': now,})
        except Exception:
            logger.exception(f"[id={schedule_id}] Falha ao atualizar status para Executando")

        running[schedule_id] = {"proc": processo, "log": flow_log, "f_out": f_out}
        process_queue.append(processo)

        return True

    except Exception:
        logger.exception(f"[id={schedule_id}] Falha inesperada ao executar fluxo")
        try:
            update_schedule(schedule_id, {'status': 'Erro'})
        except Exception:
            logger.exception(f"[id={schedule_id}] Falha ao atualizar status após exceção")
        return False

def main():
    logger.info("=== Scheduler iniciado ===")
    try:
        refresh_cache()
    except Exception:
        logger.exception("Falha no refresh_cache inicial")

    while True:
        try:
            df = load_cache()
            now = datetime.now(pytz.timezone("America/Sao_Paulo"))
            logger.info(f"Heartbeat: {len(df)} agendamentos | running={len(running)} | queue={len(process_queue)}")

            for _, linha in df.iterrows():
                sid = linha.get('id')
                try:
                    if exec_bat_file_checker(linha, now):
                        logger.info(f"[id={sid}] Disparo autorizado | freq={linha.get('frequencia')} | hora={linha.get('hora')} | last={linha.get('ultima_execucao')}")
                        execute_with_queue(linha['caminho'], sid, now)
                except Exception as e:
                    logger.exception(f"[id={sid}] Erro no loop de disparo")
                    # Não muda status aqui; o erro pode ser na regra, não no fluxo

            reap_running()
        except Exception:
            logger.exception("Falha no loop principal (fora do for)")

        time.sleep(5)

if __name__ == "__main__":
    main()
