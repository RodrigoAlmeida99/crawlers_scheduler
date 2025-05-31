# 🛠️ FME Flow Scheduler via PostgresSQL and Python

This project provides a lightweight, Python-based scheduling system to automate the execution of `.bat` files (typically used to run FME Desktop workflows) based on a shared Excel spreadsheet hosted on SharePoint.

## 📌 Project Purpose

The main goal is to centralize and simplify the scheduling and execution of multiple FME workflows developed by different team members, **without relying on expensive or complex tools like Airflow, Jenkins, or external orchestrators**.

By leveraging a shared Excel file, users can independently configure and manage their flows — defining scheduling frequency, execution time, and enabling or disabling flows — in a transparent and collaborative way.

---

## ⚙️ How It Works

## 🔄 Project Overview

This project automates the scheduling and execution of data flows using Python and FME Desktop, now integrated with a PostgreSQL database and local cache for improved reliability and performance.

### 📌 Key Components

1. **PostgreSQL Database**  
   All scheduling instructions are stored in a PostgreSQL table, replacing the previous Excel-based approach.

2. **Python Script (Scheduled Execution)**  
   A Python script runs periodically in the background (via Task Scheduler or Windows Service) on a Windows Server where FME Desktop is installed. It performs the following tasks:
   - Loads scheduling data from a `.pkl` cache file.
   - The cache is refreshed from the PostgreSQL database using SQLAlchemy when necessary.
   - Checks if a flow is due for execution based on schedule time and frequency.
   - Executes the corresponding `.bat` file linked to the flow.
   - Updates the `last_execution` timestamp in the database to prevent duplicate runs.

3. **Local Cache (`.pkl`)**  
   A serialized cache file (`scheduler_cache.pkl`) is used to minimize repeated database queries and optimize runtime performance. The cache is updated via the `refresh_cache()` function when needed.


---

## 📁 Table  Structure

The Table should contain the following columns:

| Column Name             | Description                                                                 |
|-------------------------|-----------------------------------------------------------------------------|
| **Fluxo**               | Identifier for the scheduled flow (unique name)                            |
| **Caminho**             | Full path to the `.bat` file to execute                                     |
| **Tabela no banco**     | Optional: database table impacted (for documentation)                      |
| **Schema**              | Optional: database schema used (for documentation)                         |
| **Data início agendamento** | The start date of the scheduling cycle                                  |
| **Hora agendamento**    | Time of day when the execution should happen                                |
| **Frequência**          | Supported values: `diário`, `semanal`, `mensal`, `semestral`, `manual`     |
| **Status**              | Must be set to `ativo` to allow execution                                  |
| **Ultima Execucao**     | Timestamp of the last successful execution (auto-updated by the script)    |

---

## ⏱️ Supported Frequencies

| Frequency     | Behavior                                                                 |
|---------------|--------------------------------------------------------------------------|
| `manual`      | Never auto-executes; only logs or UI tools may trigger it manually       |
| `diário`      | Executes once per day at the specified time                              |
| `semanal`     | Executes once per week on the same weekday as the start date             |
| `mensal`      | Executes once per month on the same day-of-month as the start date       |
| `semestral`   | Executes every 6 months from the last execution date                     |

---

## 🔧 Requirements

- Windows Server (or Windows Desktop)
- Python 3.9+
- FME Desktop installed
- [pandas](https://pandas.pydata.org/) installed (`pip install pandas`)
- File synchronization via OneDrive or mapped SharePoint directory
- [streamlit](https://docs.streamlit.io/get-started/installation) installed (`pip install streamlit`)
- [sqlalchemy](https://pypi.org/project/SQLAlchemy/) installed (`pip install SQLAlchemy`)

