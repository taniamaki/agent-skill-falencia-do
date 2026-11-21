@echo off
rem Coleta diaria de falencias/recuperacoes (tarefa "Coleta de falencias" do Agendador do Windows).
rem Comeca na data mais recente ja gravada na planilha e vai ate hoje, sem duplicar.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist logs mkdir logs
echo ===== %date% %time% >> logs\coleta.log
"C:\Users\mtani\anaconda3\python.exe" -I "C:\Users\mtani\OneDrive\Documentos\Testinho\.claude\skills\diarios-falencias\scripts\coletar.py" --desde-ultima --saida "%~dp0." >> logs\coleta.log 2>&1

rem Copia api\ e falencias\ para o repositorio da skill e envia ao GitHub (so commita se algo mudou).
set REPO=C:\Users\mtani\OneDrive\Documentos\Testinho\.claude\skills\diarios-falencias
set GIT="C:\Program Files\Git\cmd\git.exe"
echo --- GitHub >> logs\coleta.log
robocopy "%~dp0." "%REPO%\falencias" /E /XD logs /NFL /NDL /NJH /NJS >> logs\coleta.log
robocopy "%~dp0..\api" "%REPO%\api" /E /XD __pycache__ /NFL /NDL /NJH /NJS >> logs\coleta.log
cd /d "%REPO%"
%GIT% add -A api falencias >> "%~dp0logs\coleta.log" 2>&1
%GIT% diff --cached --quiet || (%GIT% commit -q -m "Atualiza dados (%date%)" && %GIT% push -q) >> "%~dp0logs\coleta.log" 2>&1
