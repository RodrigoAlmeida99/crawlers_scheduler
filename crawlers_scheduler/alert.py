# monitor_logs_table.py
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from glob import glob
from typing import Iterable, Optional, Dict, Any, List, Tuple
from datetime import datetime, UTC
from dotenv import find_dotenv, load_dotenv

# você já tem estes dois em seu projeto:
from controller import select_tabeles  # deve retornar as linhas com status "Erro" (ou toda a tabela se você ajustar aí)
from scheduler import path_transformer  # <<< mantenha o nome/arquivo real da sua função
from applicationinsights import TelemetryClient
import time
import re
import json

# credenciais Azure
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)
INSTRUMENTATION_KEY  = os.getenv('Instrumentation_Key')

tc = TelemetryClient(INSTRUMENTATION_KEY)


ERROR_PATTERNS = [r"\bERROR\b", r"\bFATAL\b", r"\bEXCEPTION\b"]
DEDUP_TTL_SECONDS = 30  # evita “tempestade” re-enviando o mesmo erro em curto prazo
_last_fingerprints: Dict[str, float] = {}



def _extract_tagged_lines(log_tail: str, patterns: Iterable[str]) -> list[str]:
    """
    Retorna, na ordem, apenas as linhas que batem com os padrões (ERROR/FATAL/EXCEPTION),
    removendo duplicatas exatas e normalizando espaços.
    """
    if not log_tail:
        return []
    seen = set()
    out: list[str] = []
    for raw in log_tail.splitlines():
        if any(re.search(p, raw, re.IGNORECASE) for p in patterns):
            norm = _normalize_whitespace(raw)
            if norm and norm not in seen:
                seen.add(norm)
                out.append(norm)
    return out

# -------------------------------
# Utilitário: tail eficiente (sem ler o arquivo inteiro)
# -------------------------------
def _tail_file(path: Path, max_lines: int = 30, chunk_size: int = 4096, encoding_guess: str = "utf-8") -> str:
    """
    Lê eficientemente as últimas `max_lines` linhas de um arquivo potencialmente grande.
    Não carrega o arquivo inteiro em memória.
    """
    if not path.exists() or not path.is_file():
        return ""

    # Tenta uma leitura simples, caso o arquivo seja pequeno
    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    try:
        with path.open("rb") as f:
            # Começa do final do arquivo
            block_end = size
            lines: List[bytes] = []
            buffer = b""

            while block_end > 0 and len(lines) <= max_lines:
                block_start = max(0, block_end - chunk_size)
                block_len = block_end - block_start
                f.seek(block_start)
                chunk = f.read(block_len)
                buffer = chunk + buffer
                # Quebra por linhas
                lines = buffer.splitlines()
                block_end = block_start

            # Pega as últimas N linhas
            tail_bytes = b"\n".join(lines[-max_lines:])
    except Exception:
        # fallback: se der algum erro de leitura binária, tenta aberta direta em texto
        try:
            with path.open("r", encoding=encoding_guess, errors="replace") as ft:
                content = ft.read().splitlines()
                return "\n".join(content[-max_lines:])
        except Exception:
            return ""

    # Decodifica com heurística
    for enc in (encoding_guess, "latin-1", "utf-8", "cp1252"):
        try:
            return tail_bytes.decode(enc, errors="replace")
        except Exception:
            continue
    # Se nada funcionar, tenta binário->str forçada
    try:
        return tail_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""

def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _fingerprint_error(err: Dict[str, Any]) -> str:
    base = json.dumps(
        {
            "message": err.get("message", ""),
            "origin": err.get("origin", ""),
            "file_path": err.get("file_path", ""),
            "line_no": err.get("line_no", ""),
            "code": err.get("code", ""),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _should_send(fingerprint: str, now: float) -> bool:
    last = _last_fingerprints.get(fingerprint)
    if last is None or (now - last) >= DEDUP_TTL_SECONDS:
        _last_fingerprints[fingerprint] = now
        return True
    return False


def _safe_get(row: Any, key: str, default: Any = None) -> Any:
    """Acessa atributo/chave sem estourar quando row é dict, objeto simples, namedtuple, etc."""
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        if hasattr(row, key):
            return getattr(row, key)
    except Exception:
        pass
    return default



# ---------------------------------------------
# Adaptado: encontra log "irmão" e retorna texto
# ---------------------------------------------
def find_latest_log_text_for(caminho_fmw: str, max_lines: int = 30) -> Tuple[Optional[Path], str]:
    """
    Acha o .log mais recente associado ao .fmw informado (na mesma pasta ou subpastas) e
    retorna (path_do_log_encontrado, texto_das_últimas_max_lines_linhas).

    Regras de busca (na mesma pasta do .fmw):
      - base.log
      - base_*.log
      - base-*.log
      - base*_log.log
      - base*log.log
    Se não achar, tenta recursivo: **/base*.log
    """
    if not caminho_fmw:
        return None, ""

    # Usa o seu resolvedor absoluto (NÃO ALTERAR)
    abs_path: Optional[Path]
    try:
        abs_path = path_transformer(str(caminho_fmw))
    except Exception:
        abs_path = None

    if not abs_path:
        return None, ""

    caminho_norm = os.path.normpath(str(abs_path).strip().replace('"', ''))
    folder = os.path.dirname(caminho_norm)
    if not folder or not os.path.isdir(folder):
        return None, ""

    base_no_ext = os.path.splitext(os.path.basename(caminho_norm))[0]

    # padrões na pasta
    patterns = [
        os.path.join(folder, f"{base_no_ext}.log"),
        os.path.join(folder, f"{base_no_ext}_*.log"),
        os.path.join(folder, f"{base_no_ext}-*.log"),
        os.path.join(folder, f"{base_no_ext}*_log.log"),
        os.path.join(folder, f"{base_no_ext}*log.log"),
    ]

    candidates: List[Path] = []
    for pat in patterns:
        candidates.extend([Path(p) for p in glob(pat)])

    # fallback recursivo (caso o log esteja numa subpasta tipo "logs")
    if not candidates:
        rec_pat = os.path.join(folder, "**", f"{base_no_ext}*.log")
        candidates.extend([Path(p) for p in glob(rec_pat, recursive=True)])

    if not candidates:
        return None, ""

    # mais recente por mtime
    try:
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
    except Exception:
        latest = candidates[-1]

    text = _tail_file(latest, max_lines=max_lines)
    return latest, text


# ---------------------------------------------------
# Varredura total da tabela e agregação dos resultados
# ---------------------------------------------------
def scan_table_logs(max_lines: int = 30) -> List[Dict[str, Any]]:
    """
    Percorre TODAS as linhas retornadas por `select_tabeles()` (ajuste no seu controller
    para retornar a tabela inteira ou um subconjunto específico) e agrega:
      - id (se existir)
      - caminho (.fmw)
      - status (se existir)
      - log_path (resolvido)
      - log_tail (últimas N linhas)
      - log_mtime (timestamp do log)
    """
    rows = list(select_tabeles())  # Deve retornar iterável de dict-like (ou objetos com atributos)
    out: List[Dict[str, Any]] = []

    for row in rows:
        # Tenta acessar de forma flexível (dict ou objeto)
        get = (lambda k: getattr(row, k) if hasattr(row, k) else row.get(k))
        caminho = get("caminho")
        status = get("status")
        fluxo  = get("fluxo")
        row_id = get("id") if ("id" in row if isinstance(row, dict) else hasattr(row, "id")) else None

        log_path, log_tail = find_latest_log_text_for(str(caminho) if caminho else "", max_lines=max_lines)

        # pega mtime do log (se houver)
        log_mtime: Optional[str] = None
        if log_path and log_path.exists():
            try:
                ts = log_path.stat().st_mtime
                log_mtime = datetime.fromtimestamp(ts).isoformat(sep=" ", timespec="seconds")
            except Exception:
                log_mtime = None

        out.append(
            {
                "id": row_id,
                "status": status,
                "fluxo": fluxo,
                "caminho_fmw": caminho,
                "log_path": str(log_path) if log_path else None,
                "log_mtime": log_mtime,
                "log_tail": log_tail,
            }
        )
    return out



# ---------------------------------------------------
# Parser de erros a partir de log_tail
# ---------------------------------------------------
def _parse_error_line(line: str, file_path: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Extrai timestamp/level/msg quando possível.
    Suporta:
      2025-11-10 20:40:21|...|ERROR| Mensagem...
      2025-11-10 20:40:21 ERROR Mensagem...
    Fallback: qualquer linha contendo ERROR/FATAL/EXCEPTION.
    """
    raw = line.rstrip("\n")
    m = re.search(
        r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}).*?\b(?P<level>ERROR|FATAL|EXCEPTION)\b[:\s|-]*(?P<msg>.*)",
        raw,
        flags=re.IGNORECASE,
    )
    if not m:
        if any(re.search(p, raw, re.IGNORECASE) for p in ERROR_PATTERNS):
            return {
                "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "level": "ERROR",
                "message": _normalize_whitespace(raw),
                "origin": "logs_table_scan",
                "file_path": file_path,
                "line_no": None,
                "code": None,
            }
        return None

    ts = m.group("ts")
    level = m.group("level").upper()
    msg = _normalize_whitespace(m.group("msg"))

    line_no = None
    m_line = re.search(r"\bline\s+(\d+)\b", raw, flags=re.IGNORECASE)
    if m_line:
        line_no = int(m_line.group(1))

    code = None
    m_code = re.search(r"\b(?:ERR|ERROR|CODE)[:\s-]*(\w+)\b", raw, flags=re.IGNORECASE)
    if m_code:
        code = m_code.group(1)

    return {
        "timestamp": ts,
        "level": level,
        "message": msg,
        "origin": "logs_table_scan",
        "file_path": file_path,
        "line_no": line_no,
        "code": code,
    }
def extract_errors_from_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Para cada item (crawler/log), agrega TODAS as linhas marcadas (ERROR/FATAL/EXCEPTION)
    das últimas N linhas em UMA única mensagem.
    """
    collected: List[Dict[str, Any]] = []
    for item in results:
        log_tail = (item.get("log_tail") or "").strip()
        if not log_tail:
            continue

        tagged = _extract_tagged_lines(log_tail, ERROR_PATTERNS)
        if not tagged:
            continue

        file_path = item.get("log_path")
        header = [
            f"Ocorrências: {len(tagged)} linha(s) com ERROR",
            f"Log mtime: {item.get('log_mtime')}",
        ]
        message = "\n".join(header + ["-" * 60] + tagged)

        try:
            from datetime import UTC
            ts = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        except Exception:
            ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        err = {
            "timestamp": ts,
            "level": "ERROR",
            "message": message,
            "origin": "logs_table_scan_aggregated",
            "file_path": file_path,
            "line_no": None,
            "code": None,
            "keys": {
                "id": item.get("id"),
                "status": item.get("status"),
                "fmw": item.get("caminho_fmw"),
                "fluxo": item.get("fluxo"),
            },
        }
        collected.append(err)
    return collected


# ===================================
# Função pedida: azure_log_sender(*)
# ===================================
def azure_log_sender(errors: List[Dict[str, Any]], event_name: str = "PipelineError") -> None:
    """
    Envia **cada** erro individualmente ao Azure Application Insights
    com dedupe por fingerprint + TTL.
    """
    if tc is None:
        # sem TelemetryClient válido, apenas loga localmente
        for err in errors:
            print(f"[NO-AI] {err.get('level','ERROR')}: {err.get('message')}")
        return

    now = time.time()

    for err in errors:
        msg = (err.get("message") or "").strip()
        if not msg:
            continue

        fp = _fingerprint_error(err)
        if not _should_send(fp, now):
            continue  # duplicado em curto prazo

        keys = err.get("keys") or {}

        props = {
            "Level": err.get("level", "ERROR"),
            "Message": msg,
            "Origin": err.get("origin", "unknown"),
            "Timestamp": err.get("timestamp") or datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "FilePath": err.get("file_path"),
            "LineNo": str(err.get("line_no")) if err.get("line_no") is not None else None,
            "Code": err.get("code"),

            # 🔽🔽🔽 "colunas" que vamos usar no e-mail
            "Fluxo":  keys.get("fluxo"),
            "Status": keys.get("status"),
            "Fmw":    keys.get("fmw"),
            "CrawlerId": keys.get("id"),
        }

        
        for k, v in keys.items():
            props[f"Key.{k}"] = v

        exc_type = err.get("exception_type")
        stack = err.get("stack")

        if exc_type or stack:
            tc.track_exception(
                type_name=exc_type or "ApplicationError",
                value=msg,
                stack=stack,
                properties={k: v for k, v in props.items() if v is not None},
            )
        else:
            tc.track_trace(name=msg, properties={k: v for k, v in props.items() if v is not None})
            tc.track_event(event_name, properties={k: v for k, v in props.items() if v is not None})

    tc.flush()

# ---------------------------------------------------
# Exemplo de uso “direto”
# ---------------------------------------------------
if __name__ == "__main__":
    results = scan_table_logs(max_lines=30)

    # imprime no console (debug)
    for item in results:
        print("=" * 80)
        print(f"ID: {item['id']}")
        print(f"Status: {item['status']}")
        print(f"FMW: {item['caminho_fmw']}")
        print(f"LOG: {item['log_path']}  (mtime={item['log_mtime']})")
        print("-" * 80)
        print(item["log_tail"])
        print()

    # extrai erros individuais e envia ao Azure
    errors = extract_errors_from_results(results)
    azure_log_sender(errors, event_name="LogsTableError")