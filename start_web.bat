@echo off
REM MusicLibraryOptimizer — start localhost web UI + API
REM Frontend: http://127.0.0.1:5173  Backend: http://127.0.0.1:8000  (also http://127.0.0.1:8000/ serves built web/dist)

start "MLO API" /min cmd /c "C:\Users\dillydallier\AppData\Local\Python\pythoncore-3.14-64\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload"
timeout /t 3
start "MLO Web" /min cmd /c "cd /d %~dp0web && npm run dev -- --host 127.0.0.1 --port 5173"
timeout /t 4
start http://127.0.0.1:5173
echo Started. Close the two minimized consoles to stop.
pause
