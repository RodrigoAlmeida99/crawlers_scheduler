import os
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Date, Time, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from schema import Scheduler_table, Base
from pathlib import Path
from sqlalchemy import text

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




if __name__ == "__main__":
    refresh_cache()