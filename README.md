# 🛠️ FME Flow Scheduler via Excel and Python

This project provides a lightweight, Python-based scheduling system to automate the execution of `.bat` files (typically used to run FME Desktop workflows) based on a shared Excel spreadsheet hosted on SharePoint.

## 📌 Project Purpose

The main goal is to centralize and simplify the scheduling and execution of multiple FME workflows developed by different team members, **without relying on expensive or complex tools like Airflow, Jenkins, or external orchestrators**.

By leveraging a shared Excel file, users can independently configure and manage their flows — defining scheduling frequency, execution time, and enabling or disabling flows — in a transparent and collaborative way.

---

## ⚙️ How It Works

1. A shared Excel file (hosted on SharePoint or synced via OneDrive) contains all scheduling instructions.
2. A Python script runs in the background (as a Windows Service or Task Scheduler job) on a Windows Server where FME Desktop is installed.
3. The script:
   - Reads the Excel file periodically
   - Checks whether a flow is due for execution
   - Executes the associated `.bat` file if conditions are met
   - Updates the "Last Execution" field in the spreadsheet to prevent duplicate runs

---

## 📁 Excel File Structure

The Excel file should contain the following columns:

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

