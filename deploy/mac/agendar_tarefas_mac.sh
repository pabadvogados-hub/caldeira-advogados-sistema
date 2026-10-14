#!/bin/bash
# =============================================================================
#  Agenda TODAS as rotinas automaticas no Mac (launchd), com os MESMOS horarios e
#  comandos do deploy/agendar_tarefas_windows.bat. Um agente por rotina em
#  ~/Library/LaunchAgents/br.com.caldeira.*.plist. Logs em logs/ (um por rotina).
#
#    bash deploy/mac/agendar_tarefas_mac.sh             cria ou atualiza (pode rodar de novo)
#    bash deploy/mac/agendar_tarefas_mac.sh --listar    mostra o que esta agendado
#    bash deploy/mac/agendar_tarefas_mac.sh --remover   apaga todas as rotinas br.com.caldeira.*
#    acrescente --sim para nao perguntar se esta e a maquina das rotinas
#    --so-gerar=PASTA  so escreve os .plist em PASTA (conferencia; nao agenda nada)
#
#  IMPORTANTE (mesma regra do Windows):
#  - As rotinas automaticas ficam ligadas em UMA maquina so: este Mac, OU um
#    Windows, OU a VPS. Duas maquinas agendadas = cliente recebe mensagem em DOBRO.
#    Antes de agendar aqui: "deploy\agendar_tarefas_windows.bat /remover" no Windows
#    e timers da VPS desligados (docs/DEPLOY_VPS.md).
#  - O Mac precisa ficar ligado, com o usuario logado e sem dormir nos horarios (o
#    launchd do usuario so roda com a sessao aberta; se o Mac estava dormindo, a
#    rotina roda quando ele acorda). A pasta do servidor (/Volumes/CLIENTES) precisa
#    estar conectada: Ajustes do Sistema > Geral > Itens de Inicio.
#  - Modulo que ainda nao existe na maquina e pulado sem erro (rodar_rotina.sh).
# =============================================================================
cd "$(dirname "$0")/../.." || exit 1
PASTA="$(pwd)"
AGENTES="$HOME/Library/LaunchAgents"
PREFIXO="br.com.caldeira"
GERADOR="$PASTA/deploy/mac/launchd_plists.py"
UID_ATUAL="$(id -u)"
MODO=criar
SIM=0
DESTINO_TESTE=""
for a in "$@"; do
  case "$a" in
    --listar) MODO=listar ;;
    --remover) MODO=remover ;;
    --sim) SIM=1 ;;
    --so-gerar=*) MODO=gerar; DESTINO_TESTE="${a#--so-gerar=}" ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) echo "Opcao desconhecida: $a (use --listar, --remover, --sim ou --help)"; exit 2 ;;
  esac
done

PY="$PASTA/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

# -----------------------------------------------------------------------------
# TABELA DAS ROTINAS - mesma agenda do deploy/agendar_tarefas_windows.bat
# (e de deploy/vps/systemd e deploy/vps/docker/crontab). Mudou la, muda aqui.
# FREQ: DAILY | WEEKLY | MONTHLY    DIAS: - | MON,TUE,... | dia do mes (1,16)
# -----------------------------------------------------------------------------
TABELA='
# LOG                              FREQ     DIAS                 HORAS              COMANDO
contratacao_acompanhar             DAILY    -                    09:00,13:00,17:00  CONTRATACAO/main.py acompanhar --enviar
fluxos                             DAILY    -                    09:30,11:30,14:30,17:30  FLUXOS/main.py rodar --enviar
extrajudicial_acompanhar           DAILY    -                    08:30              EXTRAJUDICIAL/main.py acompanhar --enviar
controladoria_varredura            DAILY    -                    07:30              CONTROLADORIA/main.py varredura --dias 3
controladoria_relatorio_clientes   MONTHLY  1,16                 08:00              CONTROLADORIA/main.py relatorio-clientes --dias 15
gestao_pauta                       WEEKLY   MON                  07:00              GESTAO/main.py pauta
gestao_auditoria                   WEEKLY   FRI                  16:00              GESTAO/main.py auditoria
comercial_meta_ads                 DAILY    -                    07:00              COMERCIAL/main.py meta-ads --dias 1
comercial_radar                    MONTHLY  1                    07:15              COMERCIAL/main.py radar
comercial_auditoria_atendimento    WEEKLY   FRI                  15:00              COMERCIAL/main.py auditoria-atendimento --dias 7
marketing_criativos                DAILY    -                    07:15              MARKETING/trafego.py criativos --dias 7
marketing_funil                    MONTHLY  2                    08:00              MARKETING/trafego.py funil
financeiro_cobranca                WEEKLY   MON,TUE,WED,THU,FRI  10:00              FINANCEIRO/main.py cobranca --enviar
financeiro_inadimplencia           WEEKLY   MON                  08:00              FINANCEIRO/main.py inadimplencia
financeiro_honorarios_novos        WEEKLY   MON,TUE,WED,THU,FRI  18:00              FINANCEIRO/main.py honorarios-novos
financeiro_fechamento              MONTHLY  5                    08:00              FINANCEIRO/main.py fechamento
healthcheck                        DAILY    -                    06:50              deploy/vps/healthcheck.py
'

remover_todas() {
  n=0
  for f in "$AGENTES/$PREFIXO".*.plist; do
    [ -e "$f" ] || continue
    rotulo="$(basename "$f" .plist)"
    launchctl bootout "gui/$UID_ATUAL/$rotulo" >/dev/null 2>&1 || launchctl unload "$f" >/dev/null 2>&1
    rm -f "$f"
    [ "$1" = "quieto" ] || echo "  removida  $rotulo"
    n=$((n + 1))
  done
  [ "$1" = "quieto" ] || [ "$n" -gt 0 ] || echo "  nada para remover: nenhuma rotina $PREFIXO.* neste Mac."
}

carregar() {
  rotulo="$(basename "$1" .plist)"
  launchctl bootout "gui/$UID_ATUAL/$rotulo" >/dev/null 2>&1
  for tentativa in 1 2 3; do
    launchctl bootstrap "gui/$UID_ATUAL" "$1" >/dev/null 2>&1 && return 0
    sleep 1
  done
  # macOS antigo: jeito classico
  launchctl unload "$1" >/dev/null 2>&1
  launchctl load -w "$1" >/dev/null 2>&1
}

# ------------------------------------------------------------------ so gerar (conferencia)
if [ "$MODO" = "gerar" ]; then
  mkdir -p "$DESTINO_TESTE" || exit 1
  printf '%s\n' "$TABELA" | "$PY" "$GERADOR" gerar --pasta "$PASTA" --destino "$DESTINO_TESTE" --prefixo "$PREFIXO" || exit 1
  "$PY" "$GERADOR" validar --destino "$DESTINO_TESTE" --prefixo "$PREFIXO"
  exit $?
fi

if [ "$(uname)" != "Darwin" ]; then
  echo "Este script e para Mac (launchd). No Windows: deploy\\agendar_tarefas_windows.bat. Na VPS: docs/DEPLOY_VPS.md"
  exit 1
fi

# ------------------------------------------------------------------ listar
if [ "$MODO" = "listar" ]; then
  echo "Rotinas agendadas neste Mac ($AGENTES):"
  "$PY" "$GERADOR" listar --destino "$AGENTES" --prefixo "$PREFIXO"
  echo
  echo "Carregadas no launchd agora (PID  ultimo-codigo  nome; codigo 0 = ultima vez deu certo):"
  launchctl list | grep "$PREFIXO" || echo "  nenhuma carregada."
  exit 0
fi

# ------------------------------------------------------------------ remover
if [ "$MODO" = "remover" ]; then
  echo "Removendo as rotinas $PREFIXO.* deste Mac..."
  remover_todas
  echo "Pronto. Nenhuma rotina automatica roda mais neste Mac."
  exit 0
fi

# ------------------------------------------------------------------ criar
echo "==============================================================="
echo "  Caldeira Advogados Associados - agendar rotinas (Mac)"
echo "  Pasta: $PASTA"
echo "==============================================================="
if [ ! -x "$PASTA/.venv/bin/python" ]; then
  echo "ERRO: .venv nao encontrada. Rode antes: bash deploy/mac/instalar_mac.sh"
  exit 1
fi
[ -f "$PASTA/config/.env" ] || echo "AVISO: config/.env ainda nao existe - as rotinas vao rodar em modo seguro (sem credenciais)."
case "$PASTA" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*|"$HOME/Library/Mobile Documents"*|"$HOME/Library/CloudStorage"*)
    echo "AVISO: o sistema esta em $PASTA."
    echo "       O macOS bloqueia rotinas automaticas nas pastas Documentos, Mesa, Downloads, iCloud e Drive"
    echo "       ('Operation not permitted' no log). Melhor mover para $HOME/CALDEIRA_ADVOGADOS e rodar de novo,"
    echo "       ou dar 'Acesso Total ao Disco' para /bin/bash e para a .venv em Ajustes > Privacidade e Seguranca."
    ;;
esac

echo
echo "REGRA: as rotinas automaticas ficam ligadas em UMA maquina so (este Mac OU um Windows OU a VPS)."
echo "       Duas maquinas agendadas = o cliente recebe WhatsApp e cobranca em DOBRO."
if [ "$SIM" -ne 1 ]; then
  if [ ! -t 0 ]; then
    echo "Sem terminal para confirmar. Rode de novo com --sim se esta for mesmo a maquina das rotinas."
    exit 1
  fi
  printf "Este Mac e a UNICA maquina que vai rodar as rotinas automaticas? [s/N] "
  read -r resposta
  case "$resposta" in
    s|S|sim|SIM|Sim) ;;
    *) echo "Nada foi agendado."; exit 0 ;;
  esac
fi

mkdir -p "$PASTA/logs" "$AGENTES"
remover_todas quieto   # recomeca do zero: rotina renomeada/retirada nao fica sobrando
echo
echo "Agendando..."
ERROS=0
ARQUIVOS="$(printf '%s\n' "$TABELA" | "$PY" "$GERADOR" gerar --pasta "$PASTA" --destino "$AGENTES" --prefixo "$PREFIXO")" || {
  echo "ERRO ao gerar os agentes do launchd."; exit 1; }
while IFS= read -r plist; do
  [ -n "$plist" ] || continue
  rotulo="$(basename "$plist" .plist)"
  if command -v plutil >/dev/null 2>&1 && ! plutil -lint "$plist" >/dev/null 2>&1; then
    echo "  FALHOU    $rotulo (plist invalido)"; ERROS=$((ERROS + 1)); continue
  fi
  if carregar "$plist"; then
    echo "  OK        $rotulo"
  else
    echo "  FALHOU    $rotulo"; ERROS=$((ERROS + 1))
  fi
done <<EOF
$ARQUIVOS
EOF

echo
if [ "$ERROS" -gt 0 ]; then
  echo "ATENCAO: $ERROS rotina(s) nao foram carregadas. Rode de novo; se continuar, veja logs/launchd.log."
else
  echo "Pronto. Horarios e comandos:"
  "$PY" "$GERADOR" listar --destino "$AGENTES" --prefixo "$PREFIXO"
fi
echo
echo "Logs de cada rotina: $PASTA/logs/"
echo "Rodar uma rotina agora, para testar:"
echo "  launchctl kickstart gui/$UID_ATUAL/$PREFIXO.financeiro-inadimplencia"
echo "Ver o que esta agendado:  bash deploy/mac/agendar_tarefas_mac.sh --listar"
echo "Desligar tudo neste Mac:  bash deploy/mac/agendar_tarefas_mac.sh --remover"
exit "$ERROS"
