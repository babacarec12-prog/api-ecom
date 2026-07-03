@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI Commerce API
echo Démarrage de Django et du tunnel ngrok...
echo Gardez cette fenêtre ouverte pendant les tests WhatsApp.
echo.
".venv\Scripts\python.exe" -u start.py
echo.
echo Le service s'est arrêté. Consultez le message ci-dessus.
pause
