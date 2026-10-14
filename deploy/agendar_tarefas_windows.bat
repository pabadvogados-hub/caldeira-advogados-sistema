@echo off
REM =============================================================================
REM  Agenda TODAS as rotinas automaticas no Agendador de Tarefas do Windows,
REM  na pasta "Caldeira" do Agendador. Logs em logs\ (um arquivo por rotina).
REM
REM    deploy\agendar_tarefas_windows.bat            cria ou atualiza (pode rodar de novo)
REM    deploy\agendar_tarefas_windows.bat /listar    mostra o que esta agendado
REM    deploy\agendar_tarefas_windows.bat /remover   apaga todas as rotinas "Caldeira"
REM    acrescente /sem-pausa para nao esperar uma tecla no final
REM
REM  IMPORTANTE:
REM  - Rodar na maquina que fica LIGADA no escritorio, com o usuario que usa o sistema.
REM  - As rotinas rodam com o usuario conectado. Para rodar com a sessao bloqueada/
REM    deslogada: Agendador > pasta Caldeira > tarefa > Propriedades > "Executar
REM    estando o usuario conectado ou nao".
REM  - Se as rotinas forem para a VPS (docs\DEPLOY_VPS.md), rode /remover aqui:
REM    as duas maquinas juntas mandariam mensagem em dobro para o cliente.
REM  - Modulo que ainda nao existe na maquina e pulado sem erro (rodar_rotina.bat).
REM =============================================================================
setlocal EnableExtensions
cd /d "%~dp0.."
set "PASTA=%cd%"
set "MODO=criar"
set "SEMPAUSA="
if /I "%~1"=="/sem-pausa" set "SEMPAUSA=1"
if /I "%~2"=="/sem-pausa" set "SEMPAUSA=1"
if /I "%~1"=="/remover" set "MODO=remover"
if /I "%~1"=="/listar" (
  schtasks /Query /FO CSV /NH | findstr /I /C:"Caldeira"
  goto fim
)
if not exist "%PASTA%\logs" mkdir "%PASTA%\logs"
set ERROS=0

if "%MODO%"=="criar" (
  echo Agendando as rotinas em "%PASTA%" ...
  REM remove as tarefas antigas do agendar_acompanhamento_windows.bat, agora na pasta Caldeira
  for %%H in (09 13 17) do schtasks /Delete /F /TN "Caldeira Contratacao %%H" >nul 2>&1
) else (
  echo Removendo as rotinas da pasta Caldeira do Agendador...
)

REM            NOME NO AGENDADOR                          FREQ     DIAS                  HORA   LOG                              COMANDO
call :tarefa "Contratacao - acompanhar 09h"               DAILY    ""                    09:00  contratacao_acompanhar           "CONTRATACAO\main.py acompanhar --enviar"
call :tarefa "Contratacao - acompanhar 13h"               DAILY    ""                    13:00  contratacao_acompanhar           "CONTRATACAO\main.py acompanhar --enviar"
call :tarefa "Contratacao - acompanhar 17h"               DAILY    ""                    17:00  contratacao_acompanhar           "CONTRATACAO\main.py acompanhar --enviar"
call :tarefa "Fluxos - atendimento 09h30"                 DAILY    ""                    09:30  fluxos                           "FLUXOS\main.py rodar --enviar"
call :tarefa "Fluxos - atendimento 11h30"                 DAILY    ""                    11:30  fluxos                           "FLUXOS\main.py rodar --enviar"
call :tarefa "Fluxos - atendimento 14h30"                 DAILY    ""                    14:30  fluxos                           "FLUXOS\main.py rodar --enviar"
call :tarefa "Fluxos - atendimento 17h30"                 DAILY    ""                    17:30  fluxos                           "FLUXOS\main.py rodar --enviar"
call :tarefa "Extrajudicial - acompanhar"                 DAILY    ""                    08:30  extrajudicial_acompanhar         "EXTRAJUDICIAL\main.py acompanhar --enviar"
call :tarefa "Controladoria - varredura"                  DAILY    ""                    07:30  controladoria_varredura          "CONTROLADORIA\main.py varredura --dias 3"
call :tarefa "Controladoria - relatorio clientes dia 01"  MONTHLY  "1"                   08:00  controladoria_relatorio_clientes "CONTROLADORIA\main.py relatorio-clientes --dias 15"
call :tarefa "Controladoria - relatorio clientes dia 16"  MONTHLY  "16"                  08:00  controladoria_relatorio_clientes "CONTROLADORIA\main.py relatorio-clientes --dias 15"
call :tarefa "Gestao - pauta semanal"                     WEEKLY   "MON"                 07:00  gestao_pauta                     "GESTAO\main.py pauta"
call :tarefa "Gestao - auditoria semanal"                 WEEKLY   "FRI"                 16:00  gestao_auditoria                 "GESTAO\main.py auditoria"
call :tarefa "Comercial - meta ads"                       DAILY    ""                    07:00  comercial_meta_ads               "COMERCIAL\main.py meta-ads --dias 1"
call :tarefa "Comercial - radar mensal"                   MONTHLY  "1"                   07:15  comercial_radar                  "COMERCIAL\main.py radar"
call :tarefa "Comercial - auditoria atendimento"          WEEKLY   "FRI"                 15:00  comercial_auditoria_atendimento  "COMERCIAL\main.py auditoria-atendimento --dias 7"
call :tarefa "Marketing - criativos Meta Ads"             DAILY    ""                    07:15  marketing_criativos              "MARKETING\trafego.py criativos --dias 7"
call :tarefa "Marketing - funil do mes anterior"          MONTHLY  "2"                   08:00  marketing_funil                  "MARKETING\trafego.py funil"
call :tarefa "Financeiro - cobranca honorarios"           WEEKLY   "MON,TUE,WED,THU,FRI" 10:00  financeiro_cobranca              "FINANCEIRO\main.py cobranca --enviar"
call :tarefa "Financeiro - inadimplencia"                 WEEKLY   "MON"                 08:00  financeiro_inadimplencia         "FINANCEIRO\main.py inadimplencia"
call :tarefa "Financeiro - honorarios novos"              WEEKLY   "MON,TUE,WED,THU,FRI" 18:00  financeiro_honorarios_novos      "FINANCEIRO\main.py honorarios-novos"
call :tarefa "Financeiro - fechamento mes anterior"       MONTHLY  "5"                   08:00  financeiro_fechamento            "FINANCEIRO\main.py fechamento"
call :tarefa "Sistema - healthcheck"                      DAILY    ""                    06:50  healthcheck                      "deploy\vps\healthcheck.py"

echo.
if "%MODO%"=="remover" (
  echo Pronto. Rotinas removidas.
  goto fim
)
if %ERROS% GTR 0 (
  echo ATENCAO: %ERROS% tarefa^(s^) nao foram criadas. Rode como Administrador
  echo ^(botao direito no arquivo ^> Executar como administrador^).
) else (
  echo Pronto. Conferir em: Agendador de Tarefas ^> Biblioteca ^> Caldeira
)
echo Logs de cada rotina: %PASTA%\logs\
echo Rodar uma rotina agora, para testar:  schtasks /Run /TN "Caldeira\Financeiro - inadimplencia"
goto fim

REM -----------------------------------------------------------------------------
REM :tarefa  NOME  FREQUENCIA  DIAS  HORA  LOG  COMANDO
REM -----------------------------------------------------------------------------
:tarefa
if "%MODO%"=="remover" (
  schtasks /Delete /F /TN "Caldeira\%~1" >nul 2>&1 && echo   removida  %~1
  goto :eof
)
set "DIAS="
if not "%~3"=="" set "DIAS=/D %~3"
schtasks /Create /F /TN "Caldeira\%~1" /SC %~2 %DIAS% /ST %~4 /TR "\"%PASTA%\deploy\rodar_rotina.bat\" %~5 %~6" >nul
if errorlevel 1 (
  echo   FALHOU    %~1
  set /a ERROS+=1
) else (
  echo   OK        %~1  [%~2 %~3 %~4]
)
goto :eof

:fim
if not defined SEMPAUSA pause
endlocal
