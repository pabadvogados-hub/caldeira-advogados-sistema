# Mapa do sistema - Caldeira Advogados Associados

Onde cada parte do fluxo do escritório está no sistema: módulo, comando, quem usa, o que roda sozinho
e quais chaves do `config/.env` cada coisa precisa. Guia de boas-vindas da equipe: `docs/COMECE_AQUI.md`.

> Regra de ouro: a IA não protocola e não envia nada ao banco. Toda peça, notificação e relatório passa por
> revisão humana. Sem a chave no `.env`, a etapa fica em **modo seguro** (nada sai do escritório).

## O fluxo do escritório

```
Fluxo inicial        1 Onboarding     2 Formalização     3 Extrajudicial    4 Judicial      5 Acompanhamento    6 Finalização
SDR -> Closer fecha  -> triagem e     -> contrato,        -> notificação     -> inicial e    -> publicações,     -> encerramento,
(COMERCIAL,             reunião          procuração,         aos bancos         recursos        prazos, relatório   arquivo e
 CONTRATACAO novo)      (CONTRATACAO)    ZapSign, Asaas     (EXTRAJUDICIAL)    (JUDICIAL)      ao cliente          êxito
                                         (CONTRATACAO,                                          (CONTROLADORIA,     (CONTROLADORIA,
                                          FINANCEIRO)                                            GESTAO, FINANCEIRO)  FINANCEIRO)
```

## Fase -> módulo -> comando -> cargo -> rotina -> credenciais

Comandos rodados na pasta do sistema (`python MODULO/main.py ...`). "Sob demanda" = alguém pede.
Iguais no Windows e no Mac; no Mac, antes, `source .venv/bin/activate` (ou use `.venv/bin/python` no lugar de
`python`). Caminho de pasta do cliente: `Z:\CLIENTES\...` no Windows, `/Volumes/CLIENTES/...` no Mac.

| Fase | O que acontece | Comando | Cargo responsável | Rotina automática | Credenciais |
|---|---|---|---|---|---|
| Fluxo inicial | Resultado das campanhas (leads, custo) | `COMERCIAL/main.py meta-ads --dias 1` | SDR / Gestor | diário 7h | `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID` |
| Fluxo inicial | Radar de crédito rural por município | `COMERCIAL/main.py radar` | Gestor / Comercial | mensal, dia 1, 7h15 | - |
| Fluxo inicial | Qualificação e resposta ao lead | `COMERCIAL/main.py sdr conversa.txt` | SDR | sob demanda | `ANTHROPIC_API_KEY` |
| Fluxo inicial | Auditoria do atendimento (SDR/Closer) | `COMERCIAL/main.py auditoria-atendimento --dias 7` | Gestor | sexta 15h | `ANTHROPIC_API_KEY` |
| Fluxo inicial | Calculadora para a proposta | `COMERCIAL/main.py calculadora` | Closer | sob demanda | - |
| Fluxo inicial | Plano de campanha do Meta (regiões do radar, orçamento, ângulos, teste A/B de 14 dias) | `MARKETING/trafego.py plano --orcamento-mensal 3000` | Gestor / quem monitora | sob demanda | radar gerado (`COMERCIAL/main.py radar`); `META_ACCESS_TOKEN` opcional (confere interesses) |
| Fluxo inicial | Análise por anúncio: escalar, manter, pausar, trocar criativo | `MARKETING/trafego.py criativos --dias 7` | quem monitora as campanhas | diário 7h15 | `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID` (+ `ANTHROPIC_API_KEY` para a leitura da IA) |
| Fluxo inicial | Ações na conta com trava (pausar, orçamento ±20%, duplicar PAUSADO) | `MARKETING/trafego.py acoes --dias 7 --aplicar` | Gestor (confirma item a item) | nunca automático | `META_ACCESS_TOKEN_ACOES` (ads_management) |
| Fluxo inicial | Backup e mapa completo da conta de anúncios (todas as campanhas, públicos, textos, mídia, 37 meses de resultado) | `MARKETING/main.py backup [--videos]` | quem monitora as campanhas | sob demanda (sugestão: semanal) | `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID` |
| Fluxo inicial | Replicar campanha a partir do backup, com revisão da IA (região, gênero, textos no Provimento 205); nasce PAUSADA | `MARKETING/main.py replicar --listar` / `--campanha <id> [--ia] [--aplicar]` | Gestor (digita SIM) | nunca automático | `META_ACCESS_TOKEN_ACOES`; `ANTHROPIC_API_KEY` para `--ia`; destino só contas do `.env` |
| Fluxo inicial | Funil do mês: gasto -> conversas -> reuniões -> contratos (CAC, ROI) | `MARKETING/trafego.py funil --mes MM/AAAA` | Gestor / titular | mensal, dia 2, 8h (mês anterior) | Meta (ou `--gasto`), `--csv` do atendimento ou `ATENDE_DIREITO_FLOW_TOKEN`, `PASTA_CLIENTES_RAIZ` |
| Fluxo inicial | Página do produtor rural (landing) e links com UTM | `MARKETING/trafego.py landing` e `utm --campanha ... --conjunto ... --anuncio ...` | Marketing | sob demanda | - |
| Fluxo inicial | Closer fechou: pasta, triagem, contrato, procuração, declaração | `CONTRATACAO/main.py novo "TRANSCRICAO" "CNH" ... --cadastro CADASTRO.txt` | Closer | sob demanda | `ANTHROPIC_API_KEY`, `PASTA_CLIENTES_RAIZ` |
| 1 Onboarding | Relatório de Triagem (gatilhos, bancos, linha do tempo) e situação dos casos | `CONTRATACAO/main.py painel` | Gestor Jurídico, Estagiário | sob demanda | `PASTA_CLIENTES_RAIZ` |
| 2 Formalização | Envio para assinatura + ADVBOX + Asaas + WhatsApp | `CONTRATACAO/main.py enviar "PASTA"` | Estagiário | sob demanda | `ZAPSIGN_API_TOKEN`, `ATENDE_DIREITO_TOKEN`, `ADVBOX_API_TOKEN`, `ASAAS_API_TOKEN` |
| 2 Formalização | Confere assinaturas (e cobra documentos, se o fluxo `documentos` do FLUXOS estiver desligado) | `CONTRATACAO/main.py acompanhar --enviar` | Estagiário | diário 9h, 13h e 17h | `ZAPSIGN_API_TOKEN`, `ATENDE_DIREITO_TOKEN`, `PASTA_CLIENTES_RAIZ` |
| Fluxo inicial a 3 | Fluxos do atendimento pelo funil do Atende Direito: cadência de lead quente e pós-reunião, reaquecimento, "ligar já" (leilão/penhora), boas-vindas e documentos do contrato, cobrança de assinatura e de documentos do caso, avisos de fase ao cliente (detalhes em `docs/FLUXOS.md`) | `FLUXOS/main.py rodar --enviar` (simulação sem `--enviar`; `etapas`, `status`, `parar`) | SDR, Closer, Estagiário (recebem os avisos) | diário 9h30, 11h30, 14h30, 17h30 | `ATENDE_DIREITO_FLOW_TOKEN`, `ATENDE_DIREITO_FLOW_CANAL`, `ATENDE_DIREITO_FLOW_FUNIL`, `FLUXOS_TEL_EQUIPE`, `ZAPSIGN_API_TOKEN` |
| 2 Formalização | Contrato novo sem cobrança no Asaas | `FINANCEIRO/main.py honorarios-novos` | Financeiro | seg a sex 18h | `PASTA_CLIENTES_RAIZ` (+ `ASAAS_API_TOKEN` para conferir) |
| 2 Formalização | Régua de cobrança dos honorários | `FINANCEIRO/main.py cobranca --enviar` | Financeiro | seg a sex 10h | `ASAAS_API_TOKEN`, `ATENDE_DIREITO_TOKEN` |
| 3 Extrajudicial | Notificação extrajudicial aos bancos | `EXTRAJUDICIAL/main.py notificar "PASTA"` | Adv. Extrajudicial | sob demanda | `ANTHROPIC_API_KEY` |
| 3 Extrajudicial | Prazo de resposta dos bancos, cobranças internas | `EXTRAJUDICIAL/main.py acompanhar --enviar` | Adv. Extrajudicial | diário 8h30 | `PASTA_CLIENTES_RAIZ`, `ATENDE_DIREITO_TOKEN` |
| 3 Extrajudicial | Situação das notificações | `EXTRAJUDICIAL/main.py painel` | Adv. Extrajudicial, Gestor | sob demanda | `PASTA_CLIENTES_RAIZ` |
| 4 Judicial | O que falta para a inicial | `JUDICIAL/main.py checklist "PASTA"` | Adv. Judicial | sob demanda | `PASTA_CLIENTES_RAIZ` |
| 4 Judicial | Petição inicial (minuta para revisão) | `JUDICIAL/main.py inicial "PASTA"` | Adv. Judicial / Coordenador | sob demanda | `ANTHROPIC_API_KEY` |
| 4 Judicial | Agravo, réplica, embargos, contrarrazões, manifestação | `JUDICIAL/main.py agravo` (ou `replica`, `embargos`, `contrarrazoes`, `manifestacao`) | Adv. Judicial / Coordenador | sob demanda | `ANTHROPIC_API_KEY` |
| 5 Acompanhamento | Publicações e andamentos do dia, prazos | `CONTROLADORIA/main.py varredura --dias 3` | Coordenador Jurídico | diário 7h30 | `ADVBOX_API_TOKEN`, `OABS_MONITORADAS`, `ANTHROPIC_API_KEY` |
| 5 Acompanhamento | Relatório quinzenal ao cliente (só gera; envio depois da revisão) | `CONTROLADORIA/main.py relatorio-clientes --dias 15` | Coordenador Jurídico | dias 1 e 16, 8h | `ADVBOX_API_TOKEN`, `ANTHROPIC_API_KEY` |
| 5 Acompanhamento | Planilha de processos / processos parados | `CONTROLADORIA/main.py planilha` e `parados` | Coordenador, Gestor | sob demanda | `ADVBOX_API_TOKEN` |
| 5 Acompanhamento | Pauta da semana | `GESTAO/main.py pauta` | Gestor Jurídico | segunda 7h | `ADVBOX_API_TOKEN` |
| 5 Acompanhamento | Auditoria da semana / gargalos | `GESTAO/main.py auditoria` e `gargalos` | Gestor Jurídico, titular | sexta 16h / sob demanda | `ADVBOX_API_TOKEN` |
| 5 Acompanhamento | Inadimplência por cliente (XLSX) | `FINANCEIRO/main.py inadimplencia` | Financeiro | segunda 8h | `ASAAS_API_TOKEN` |
| 5 Acompanhamento | Fechamento do mês (Asaas x ADVBOX) | `FINANCEIRO/main.py fechamento MM/AAAA` | Financeiro, titular | dia 5, 8h (mês anterior) | `ASAAS_API_TOKEN`, `ADVBOX_API_TOKEN` |
| 6 Finalização | Encerrar o caso e arquivar | `CONTROLADORIA/main.py finalizar "PASTA"` | Coordenador Jurídico | sob demanda | `ADVBOX_API_TOKEN`, `PASTA_CLIENTES_RAIZ` |
| 6 Finalização | Honorários de êxito | cobrança criada no Asaas pelo Financeiro; a régua (`cobranca`) acompanha | Financeiro | seg a sex 10h | `ASAAS_API_TOKEN`, `ATENDE_DIREITO_TOKEN` |
| Sistema | Saúde das integrações, aviso por WhatsApp se algo cair | `python deploy/vps/healthcheck.py` | quem cuida do sistema | Windows: diário 6h50 / VPS: de hora em hora | `ALERTA_WHATSAPP`, `ATENDE_DIREITO_TOKEN` |

Cada módulo tem mais subcomandos do que os da tabela (ex.: `EXTRAJUDICIAL` tem `rascunho`, `bancos`,
`registrar-envio`, `registrar-resposta`, `proposta`, `decisao`, `relatorio-gestor`; `CONTROLADORIA` tem
`avisos-cliente`): a lista completa sai com `python MODULO/main.py -h`, e o topo de cada `main.py` explica.
O módulo GESTAO ainda está em construção; módulo que não existe na máquina é pulado pelas rotinas sem erro.

## Rotinas automáticas

Agendadas em UM lugar só: **ou** num Windows do escritório (`deploy\agendar_tarefas_windows.bat`), **ou** num
Mac do escritório (`bash deploy/mac/agendar_tarefas_mac.sh`, launchd, agentes `br.com.caldeira.*`), **ou** na VPS
(`docs/DEPLOY_VPS.md`). Em duas ao mesmo tempo, o cliente receberia mensagem em dobro. As outras máquinas
(Windows ou Mac) usam só os comandos sob demanda. Os três agendadores têm a mesma agenda e os mesmos comandos
(no Mac, os horários de uma mesma rotina ficam num agente só: 17 agentes = as 23 tarefas do Windows).

| Rotina | Quando | Manda mensagem ao cliente? | Log |
|---|---|---|---|
| Contratação: acompanhar | todo dia 9h, 13h, 17h | sim (links e documentos faltando, máx. 1 por dia) | `logs/contratacao_acompanhar.log` |
| Fluxos do atendimento | todo dia 9h30, 11h30, 14h30, 17h30 (envia só seg a sáb, 8h às 20h) | sim (máx. 1 por pessoa por dia, somando os fluxos) | `logs/fluxos.log` |
| Extrajudicial: acompanhar | todo dia 8h30 | conforme o módulo (`--enviar`) | `logs/extrajudicial_acompanhar.log` |
| Controladoria: varredura | todo dia 7h30 | não | `logs/controladoria_varredura.log` |
| Controladoria: relatório aos clientes | dias 1 e 16, 8h | não (só gera; envio após revisão) | `logs/controladoria_relatorio_clientes.log` |
| Gestão: pauta | segunda 7h | não | `logs/gestao_pauta.log` |
| Gestão: auditoria | sexta 16h | não | `logs/gestao_auditoria.log` |
| Comercial: Meta Ads | todo dia 7h | não | `logs/comercial_meta_ads.log` |
| Comercial: radar | dia 1, 7h15 | não | `logs/comercial_radar.log` |
| Comercial: auditoria do atendimento | sexta 15h | não | `logs/comercial_auditoria_atendimento.log` |
| Marketing: criativos do Meta Ads | todo dia 7h15 | não (só lê a conta) | `logs/marketing_criativos.log` |
| Marketing: funil do mês anterior | dia 2, 8h | não | `logs/marketing_funil.log` |
| Financeiro: cobrança (régua) | segunda a sexta 10h | sim (régua, máx. 1 por dia) | `logs/financeiro_cobranca.log` |
| Financeiro: inadimplência | segunda 8h | não | `logs/financeiro_inadimplencia.log` |
| Financeiro: honorários novos | segunda a sexta 18h | não | `logs/financeiro_honorarios_novos.log` |
| Financeiro: fechamento do mês anterior | dia 5, 8h | não | `logs/financeiro_fechamento.log` |
| Healthcheck | Windows e Mac 6h50 / VPS de hora em hora | só para `ALERTA_WHATSAPP` | `logs/healthcheck.log` |

Conferir o que está agendado: Windows `deploy\agendar_tarefas_windows.bat /listar`; Mac
`bash deploy/mac/agendar_tarefas_mac.sh --listar`. Desligar: `/remover` ou `--remover`.

Horários no fuso de Rondônia (America/Porto_Velho); no Windows e no Mac valem o relógio da máquina (deixar no
fuso de Porto Velho). O Mac das rotinas precisa ficar ligado, com o usuário logado e com o servidor conectado; se
estava dormindo no horário, a rotina roda quando ele acorda. Na VPS, as rotinas que mandam mensagem ao cliente
**não** são recuperadas se a VPS estiver fora do ar no horário (para não sair mensagem de madrugada); os
relatórios são recuperados quando ela volta.

## Régua de cobrança dos honorários (FINANCEIRO)

| Toque | Quando | Mensagem |
|---|---|---|
| Lembrete | 3 dias antes do vencimento (ou até a véspera, se a rotina não rodou) | lembrete |
| Vence hoje | no dia do vencimento | lembrete |
| D+1 | 1 a 4 dias de atraso | "ainda não identificamos o pagamento" |
| D+5 | 5 a 14 dias de atraso | "continua em aberto, podemos conversar" |
| D+15 | 15 a 29 dias de atraso | "pedimos que regularize ou fale com o financeiro" |
| depois disso | 30+ dias | sai da régua: contato humano (relatório de inadimplência) |

Cada toque sai uma vez por cobrança; o cliente recebe no máximo 1 mensagem por dia (os toques do dia vão
juntos). Quem está em `FINANCEIRO/clientes_nao_cobrar.txt` nunca recebe. Régua ajustável em
`config/regras_financeiras.py`.

## Onde ver os resultados

| O quê | Onde |
|---|---|
| Documentos do cliente (triagem, contrato, notificação, peças) | pasta do cliente em `PASTA_CLIENTES_RAIZ/AGRONEGOCIO/NOME DO CLIENTE/` (o `caso.json` grava os caminhos relativos a essa pasta, então abre igual no Windows e no Mac) |
| Relatórios do Financeiro | `SAIDA/FINANCEIRO/` (`COBRANCA/`, `INADIMPLENCIA/`, `FECHAMENTO/AAAA-MM/`, `HONORARIOS_NOVOS/`) |
| Relatórios dos outros módulos | `SAIDA/<MODULO>/` |
| O que cada rotina fez | `logs/<rotina>.log` |
| Avisos do healthcheck | `logs/healthcheck_alertas.log` (e WhatsApp de `ALERTA_WHATSAPP`) |

`SAIDA/`, `logs/` e `CLIENTES/` têm dado de cliente e nunca vão para o repositório.

## Variáveis do `config/.env`

Copiar de `config/.env.example` e preencher na máquina (canal seguro, nunca por e-mail ou WhatsApp).
Sem a chave, a etapa correspondente fica em modo seguro. **Cada máquina (Windows ou Mac) tem o seu `config/.env`**;
o que muda de uma para outra é o jeito de escrever os caminhos (`PASTA_CLIENTES_RAIZ` etc.).

| Variável | Para quê | Quem usa | Obrigatória? |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | IA (Claude) do escritório | todos os módulos com IA | sim |
| `MODELO_TRIAGEM`, `MODELO_EXTRACAO`, `MODELO_PECAS` | modelo da IA por tarefa | CONTRATACAO, JUDICIAL, EXTRAJUDICIAL | não (tem padrão) |
| `MODELO_SDR`, `MODELO_CONTROLADORIA` | modelo da IA do SDR e da varredura | COMERCIAL, CONTROLADORIA | não (tem padrão) |
| `PASTA_CLIENTES_RAIZ` | pasta dos clientes (servidor ou Drive sincronizado). Windows `Z:\CLIENTES` ou `\\SERVIDOR\CLIENTES`; Mac `/Volumes/CLIENTES` (após conectar em `smb://SERVIDOR/CLIENTES`) | CONTRATACAO, EXTRAJUDICIAL, JUDICIAL, CONTROLADORIA, FINANCEIRO | sim |
| `PASTA_ARQUIVO_CLIENTES` | onde ficam os casos finalizados | CONTROLADORIA | conferir no módulo |
| `ZAPSIGN_API_TOKEN` | assinatura digital | CONTRATACAO | para enviar contratos |
| `ADVOGADO_RESPONSAVEL_NOME`, `ADVOGADO_RESPONSAVEL_EMAIL` | signatário do escritório no ZapSign | INTEGRACOES/zapsign | não |
| `ATENDE_DIREITO_TOKEN` | WhatsApp com o cliente | CONTRATACAO, EXTRAJUDICIAL, FINANCEIRO, healthcheck | para mandar mensagem |
| `NOME_ESCRITORIO` | assinatura das mensagens | INTEGRACOES/atendedireito | não |
| `ADVBOX_API_TOKEN` | ADVBOX (clientes, processos, tarefas, financeiro) | CONTRATACAO, CONTROLADORIA, GESTAO, FINANCEIRO | sim |
| `ADVBOX_TIPO_PROCESSO`, `ADVBOX_FASE_INICIAL` | tipo e fase do processo novo no ADVBOX | CONTRATACAO | não |
| `ADVBOX_USER_RESPONSAVEL`, `ADVBOX_TIPO_TAREFA_PADRAO`, `ADVBOX_INTERVALO_GET` | remetente/tipo padrão das tarefas e ritmo das consultas | INTEGRACOES/advbox, CONTROLADORIA | não |
| `ASAAS_API_TOKEN` | cobrança de honorários | CONTRATACAO, FINANCEIRO, healthcheck | para cobrar |
| `OABS_MONITORADAS` | OABs para buscar publicações (DJEN) | CONTROLADORIA | sim, para a varredura |
| `PRAZO_INTERNO_DIAS_ANTES`, `FERIADOS_EXTRAS`, `RELATORIO_CLIENTE_DIAS` | ajustes de prazos e do relatório | CONTROLADORIA | não |
| `PRAZO_RESPOSTA_BANCO_DIAS`, `EMAIL_RESPOSTAS_BANCOS` | prazo de resposta e e-mail das respostas dos bancos | EXTRAJUDICIAL | conferir no módulo |
| `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID`, `META_API_VERSION` | campanhas do Meta Ads | COMERCIAL | para o relatório de campanhas |
| `META_ACCESS_TOKEN_ACOES` | token SEPARADO com `ads_management`, só para `acoes --aplicar` e `replicar --aplicar` | MARKETING/meta_acoes.py, MARKETING/meta_replicar.py | não (sem ele, nada é alterado na conta) |
| `META_AD_ACCOUNTS_RESERVA` | contas reserva (`act_...` separadas por vírgula) aceitas como destino da réplica | MARKETING/meta_replicar.py | não |
| `MODELO_MARKETING` | modelo da IA da leitura dos criativos e das variações de texto | MARKETING | não (padrão: `MODELO_SDR`) |
| `MARKETING_LANDING_URL`, `MARKETING_CALCULADORA_URL` | endereços publicados da landing e da calculadora (links com UTM) | MARKETING | não |
| `ALERTA_WHATSAPP` | número que recebe os avisos do healthcheck (precisa ser contato no Atende Direito) | deploy/vps/healthcheck.py | recomendada |
| `SOFFICE_PATH` | caminho do LibreOffice, se estiver fora do lugar padrão (Windows `C:\Program Files\LibreOffice`, Mac `/Applications/LibreOffice.app`, Homebrew) | NUCLEO (PDF) | não |
| `PDF_CONVERSOR` | `libreoffice` = não usar o Word para o PDF (Mac sem Word, ou Mac das rotinas) | NUCLEO (PDF) | não |
| `TESSERACT_CMD` | OCR de documento escaneado, se estiver fora do lugar padrão (Windows `C:\Program Files\Tesseract-OCR`, Mac `/opt/homebrew/bin` ou `/usr/local/bin`) | CONTRATACAO | não |

Lista montada a partir do código em 29/09/2026. O `config/.env.example` é a referência final de cada módulo.
