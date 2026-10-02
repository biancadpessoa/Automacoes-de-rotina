@echo off
rem Dois cliques aqui instalam o Clockwork automatico (sem depender da politica de scripts do Windows)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_clockwork.ps1"
