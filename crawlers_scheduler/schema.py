from sqlalchemy import create_engine, Column, Integer, String, Date, Time, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
    
credenciais = {"host":os.getenv("host"),
                   "database":os.getenv("database"),
                   "port":os.getenv("port"),
                   "user":os.getenv("user"),
                   "password":os.getenv("password")}
        

conexao = 'postgresql://' + credenciais['user'] + ':' + credenciais['password'] + '@' + credenciais['host'] + ':' + credenciais['port'] + '/' + credenciais['database']
    
engine = create_engine(conexao)
Base = declarative_base()

class Agendamento(Base):
    __tablename__ = 'crawler_scheduler'
    __table_args__ = {'schema': 'market_intelligence'}

    id = Column(Integer, primary_key=True)
    fluxo = Column(String(100), nullable=False)                # nome identificador do fluxo
    caminho = Column(String(255), nullable=False)              # caminho do .bat
    tabela_banco = Column(String(100))                         # opcional: nome da tabela
    schema = Column(String(100))                               # opcional: schema no banco
    data_inicio = Column(Date, nullable=False)                 # data de início do agendamento
    hora = Column(Time, nullable=False)                        # hora do agendamento
    frequencia = Column(String(20), nullable=False)            # diário, semanal, mensal, etc
    status = Column(String(20), default='ativo')               # ativo, inativo, etc
    ultima_execucao = Column(DateTime)                         # auto-atualizado após execução

# Cria a tabela no banco se não existir
Base.metadata.create_all(engine)

# Criação da sessão para interagir com o banco
Session = sessionmaker(bind=engine)
session = Session()
