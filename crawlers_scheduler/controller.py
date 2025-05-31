import os
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Date, Time, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from schema import Agendamento, Base
from pathlib import Path

CACHE_PATH = str(Path(__file__).parent.parent / 'cache'  / 'scheduler_cache.pkl')

credenciais = {"host":os.getenv("host"),
                   "database":os.getenv("database"),
                   "port":os.getenv("port"),
                   "user":os.getenv("user"),
                   "password":os.getenv("password")}
        

conexao = 'postgresql://' + credenciais['user'] + ':' + credenciais['password'] + '@' + credenciais['host'] + ':' + credenciais['port'] + '/' + credenciais['database']
engine = create_engine(conexao)
Session = sessionmaker(bind=engine)
session = Session()


def refresh_cache():
    df = pd.read_sql_table('agendamentos', con=engine, schema='meu_schema')
    df.to_pickle(CACHE_PATH)
    print("✅ Cache atualizado com sucesso!")



def insert_scheduler(dados: dict):
    try:
        novo = Agendamento(**dados)
        session.add(novo)
        session.commit()
        print(f"✅ Agendamento inserido com ID {novo.id}")
    except Exception as e:
        session.rollback()
        print(f"❌ Erro ao inserir: {e}")

def update_schedule(id_agendamento: int, campos: dict):
    try:
        agendamento = session.query(Agendamento).filter_by(id=id_agendamento).first()
        if agendamento is None:
            print(f"❌ Agendamento ID {id_agendamento} não encontrado.")
            return
        for campo, valor in campos.items():
            setattr(agendamento, campo, valor)
        session.commit()
        print(f"✅ Agendamento ID {id_agendamento} atualizado.")
    except Exception as e:
        session.rollback()
        print(f"❌ Erro ao atualizar: {e}")



if __name__ == "__main__":
    refresh_cache()