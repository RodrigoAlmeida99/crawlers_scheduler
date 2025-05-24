import pandas as pd
import subprocess
import time
from datetime import datetime
from pathlib import Path


scheduler_excel = Path(__file__).parent.parent / 'source' / 'Crawlers_scheduler.xlsx'
last_exec = {}
df = pd.read_excel(scheduler_excel)



def main():
    while True:
            for _, linha in df.iterrows():
                    print(linha)
            
            time.sleep(300)  # Espera 5 minutos

if __name__ == "__main__":
    main()