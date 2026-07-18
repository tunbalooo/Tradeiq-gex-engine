@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist ".env" copy ".env.example" ".env"
echo.
echo Edit .env and insert your Databento API key before live mode will work.
echo Starting TradeIQ at http://127.0.0.1:8000
python -m uvicorn backend.main:app --reload
