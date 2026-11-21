@echo off
rem Coleta diaria de falencias/recuperacoes (tarefa "Coleta de falencias" do Agendador do Windows).
rem Comeca na data mais recente ja gravada na planilha e vai ate hoje, sem duplicar.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist logs mkdir logs
echo ===== %date% %time% >> logs\coleta.log
"C:\Users\mtani\anaconda3\python.exe" -I "C:\Users\mtani\OneDrive\Documentos\Testinho\.claude\skills\diarios-falencias\scripts\coletar.py" --desde-ultima --saida "%~dp0." >> logs\coleta.log 2>&1
