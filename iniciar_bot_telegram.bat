@echo off
cd /d "%~dp0"
echo Iniciando bot de busqueda Telegram...
echo NO cierres esta ventana mientras uses el bot.
python telegram_search_bot.py
pause
