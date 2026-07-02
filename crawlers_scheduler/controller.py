import os
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Date, Time, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from schema import Scheduler_table, Base
from pathlib import Path
from sqlalchemy import text
from dotenv import load_dotenv, find_dotenv

dotenv_path = find_dotenv()
load_dotenv(dotenv_path)





CACHE_PATH = str(Path(__file__).parent.parent / 'cache'  / 'scheduler_cache.pkl')

credenciais = {"host":os.getenv("host"),
                   "database":os.getenv("database"),
                   "port":os.getenv("port"),
                   "user_name":os.getenv("user_name"),
                   "password_":os.getenv("password_")}
        

conexao = 'postgresql://' + credenciais['user_name'] + ':' + credenciais['password_'] + '@' + credenciais['host'] + ':' + credenciais['port'] + '/' + credenciais['database']
    
engine = create_engine(conexao)
Session = sessionmaker(bind=engine)
session = Session()


def refresh_cache():
    df = pd.read_sql_table('crawler_scheduler', con=engine, schema='market_intelligence')
    df.to_pickle(CACHE_PATH)
    print("Cache atualizado com sucesso!")



def insert_scheduler(dados: dict):
    try:
        novo = Scheduler_table(**dados)
        session.add(novo)
        session.commit()
        print(f"Agendamento inserido com ID {novo.id}")
    except Exception as e:
        session.rollback()
        print(f"Erro ao inserir: {e}")

def update_schedule(schedule_id: int, attributes: dict):
    try:
        schedule = session.query(Scheduler_table).filter_by(id=schedule_id).first()
        if schedule is None:
            print(f"Agendamento ID {schedule_id} não encontrado.")
            return
        for attribute, value in attributes.items():
            setattr(schedule, attribute, value)
        session.commit()
        print(f"Agendamento ID {schedule_id} atualizado.")
        refresh_cache()
    except Exception as e:
        session.rollback()
        print(f"Erro ao atualizar: {e}")

def delete_schedule(schedule_id: int):
    try:
        session.query(Scheduler_table).filter(Scheduler_table.id == schedule_id).delete(synchronize_session=False)
        session.commit()
        print(f"Agendamento ID {schedule_id} removido.")
        refresh_cache()
    except Exception as e:
        session.rollback()
        print(f"Erro ao deletar: {e}")


def list_schemas():
    try:
        with engine.connect() as conn:
            resultado = conn.execute(text("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
                ORDER BY schema_name;
            """))
            return [row[0] for row in resultado.fetchall()]
    except Exception as e:
        print(f"Erro ao listar schemas: {e}")
        return []

def select_tabeles():
    try: 
        with engine.connect() as conn:
            resultado = conn.execute(text("""
                SELECT *
                FROM market_intelligence.crawler_scheduler
                WHERE status = 'Erro'
            """))
            return [dict(row._mapping) for row in resultado]
    except Exception as e:
        print(f"Erro ao listar tabelas: {e}")
        return []


if __name__ == "__main__":
    refresh_cache()
