import pandas as pd
import subprocess
import time
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine
from controller import refresh_cache, update_schedule
import os
import sys

CACHE_PATH = str(Path(__file__).parent.parent / 'cache'  / 'scheduler_cache.pkl')
CONTROLLER_PATH = str(Path(__file__).parent / 'controller.py')

def load_cache():
    if not os.path.exists(CACHE_PATH):
        print("⚠️ Cache não encontrado. Gerando com controller.py...")
        subprocess.run([sys.executable, CONTROLLER_PATH], check=True)

    
    return pd.read_pickle(CACHE_PATH)


def exec_bat_file_checker(line, now):
    schedule_time = pd.to_datetime(str(line['Hora agendamento'])).time()
    data_flow_name = line['Fluxo']
    freq = line['Frequência'].lower()
    last = line.get('Ultima Execucao')
    status = line['Status'].strip().lower()
    schedule_id = line['id']
     # --- STATUS: INATIVO ---
    if status == 'inativo':
        return False

    # --- STATUS: EXEC (execução imediata e reset para "Ativo") ---
    if status == 'Exec':
        # Atualiza o status no banco para voltar para "Ativo"
        update_schedule(schedule_id, {'status': 'Ativo'})
        return True



    if pd.isnull(last):
        schedule_str = f"{line['Data início agendamento']} {line['Hora agendamento']}"
        schedule = pd.to_datetime(schedule_str)
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
        return not mesmo_mes and now.day == line['Data início agendamento'].day and now.time() >= schedule_time

    if freq == 'semestral':
        meses_passados = (now.year - last.year) * 12 + (now.month - last.month)
        mesmo_dia = last.day == now.day
        return meses_passados >= 6 and now.day == line['Data início agendamento'].day and now.time() >= schedule_time
    
    return False

def exec_flow(caminho):
    print(f"Executando: {caminho}")
    try:
        subprocess.Popen(caminho, shell=True)
        return True
    except Exception as e:
        print(f"Erro ao executar: {e}")
        return False


def main():
    while True:
            df = load_cache()

            now = datetime.now()
            for idx, linha in df.iterrows():
                if exec_bat_file_checker(linha, now):
                    sucesso = exec_flow(linha['Caminho'])
                    if sucesso:
                        agendamento_id = linha['id']
                        # Atualiza no banco
                        update_schedule(agendamento_id, {'ultima_execucao': now})

        # Atualiza o cache após todos os updates
            refresh_cache()

            time.sleep(300)  # Espera 5 minutos


if __name__ == "__main__":
    main()