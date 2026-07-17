@echo off
setlocal
cd /d %~dp0
if not exist .venv (
  echo Creating Python environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
start "" http://127.0.0.1:8000
uvicorn backend.main:app --reload
