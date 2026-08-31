@echo off
cd "C:\Users\PC\Documents\Default Project\Installux-ChatBot"
python app.py > server.log 2>&1
timeout /t 5 >nul
echo Server started on port 8509