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


CACHE_PATH = str(Path(__file__).parent.parent / 'cache'  / 'scheduler_cache.pkl')
CONTROLLER_PATH = str(Path(__file__).parent / 'controller.py')

def load_cache():
    if not os.path.exists(CACHE_PATH):
        print("Cache não encontrado. Gerando com controller.py...")
        subprocess.run([sys.executable, CONTROLLER_PATH], check=True)

    
    return pd.read_pickle(CACHE_PATH)

def path_transformer(caminho_original: str) -> Path:
    caminho = Path(caminho_original)

    # Extrai o nome do fluxo (último diretório antes do arquivo)
    nome_fluxo = caminho.stem  # sem .bat

    # Monta novo caminho base a partir do usuário atual
    usuario_home = Path.home()

    novo_caminho = (
        usuario_home /
        "Alvarez and Marsal" /
        "Market Intelligence & Research - Documents" /
        "General" /
        "04. Crawlers" /
        "Fluxos" /
        nome_fluxo /
        nome_fluxo
    )
    return novo_caminho

def exec_bat_file_checker(line, now):
    schedule_time = pd.to_datetime(str(line['hora'])).time()
    data_flow_name = line['fluxo']
    freq = line['frequencia'].lower()
    last = line.get('ultima_execucao')
    status = line['status'].strip().lower()
    schedule_id = line['id']
     # --- STATUS: INATIVO ---
    if status == 'inativo':
        return False

    # --- STATUS: EXEC (execução imediata e reset para "Ativo") ---
    if status == 'exec':
        # Atualiza o status no banco para voltar para "Ativo"
        update_schedule(schedule_id, {'status': 'Ativo'})
        return True



    if pd.isnull(last):
        schedule_str = f"{line['data_inicio']} {line['hora']}"
        schedule = pd.to_datetime(schedule_str).tz_localize('America/Sao_Paulo')
        return schedule <= now

    last = pd.to_datetime(last)

    if freq == 'manual':
        return False

    if freq == 'diário':
        return now.time() >= schedule_time and last.date() < now.date()

    if freq == 'semanal':
        mesma_semana = last.isocalendar()[1] == now.isocalendar()[1]
        mesmo_dia_semana = last.weekday() == now.weekday()
        return mesmo_dia_semana and not mesma_semana and now.time() >= schedule_time

    if freq == 'mensal':
        mesmo_mes = last.month == now.month and last.year == now.year
        mesmo_dia = last.day == now.day
        return not mesmo_mes and now.day == line['data_inicio'].day and now.time() >= schedule_time

    if freq == 'semestral':
        meses_passados = (now.year - last.year) * 12 + (now.month - last.month)
        mesmo_dia = last.day == now.day
        return meses_passados >= 6 and now.day == line['data_inicio'].day and now.time() >= schedule_time
    
    return False

def exec_flow(caminho):
    print(f"Executando: {caminho}")
    try:
        caminho = path_transformer(caminho)
        subprocess.Popen(str(caminho), shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return True
    except Exception as e:
        print(f"Erro ao executar: {e}")
        return False


def main():
    refresh_cache()
    while True:
            df = load_cache()

            br_tz = pytz.timezone("America/Sao_Paulo")
            now = datetime.now(br_tz)
            for idx, linha in df.iterrows():
                if exec_bat_file_checker(linha, now):
                    sucesso = exec_flow(linha['caminho'])
                    if sucesso:
                        agendamento_id = linha['id']
                        # Atualiza no banco
                        update_schedule(agendamento_id, {'ultima_execucao': now})

        # Atualiza o cache após todos os updates
            

            time.sleep(2)  # Espera 5 minutos


if __name__ == "__main__":
    main()