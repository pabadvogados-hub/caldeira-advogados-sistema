# Caldeira Advogados Associados - Automações

Ecossistema de IA do escritório, instalado nas máquinas (**Windows e Mac**) e no servidor do próprio escritório (e
opcionalmente numa VPS 24h). Cobre o fluxo inteiro do serviço, do primeiro contato do produtor à finalização do processo.

| Módulo | O que faz |
|---|---|
| `COMERCIAL/` | SDR de IA, roteiro do Closer, radar de crédito rural por município, calculadora de juros, Meta Ads, auditoria de atendimento |
| `FLUXOS/` | Fluxos do atendimento pelo funil do Atende Direito: cadências de lead, "ligar já", boas-vindas, cobrança de assinatura e de documentos, avisos de fase ao cliente (`docs/FLUXOS.md`) |
| `CONTRATACAO/` | Relatório de Triagem da reunião, contrato + procuração + declaração no timbrado, ZapSign, ADVBOX, Asaas, cobrança de documentos |
| `EXTRAJUDICIAL/` | Notificação a cada banco, rascunho no Gmail, prazo de resposta, consumidor.gov, parecer de proposta |
| `JUDICIAL/` | Checklist pré-protocolo, inicial mandamental com tutela, agravo, réplica, embargos, contrarrazões |
| `CONTROLADORIA/` | Intimações do DJEN, prazos com D-3, tarefas no ADVBOX, avisos e relatório ao cliente, planilha, finalização |
| `MARKETING/` | Calendário editorial, posts e artes do Instagram, checagem do Provimento 205, plano de campanha no Meta por região, análise dos anúncios, funil com custo por contrato, landing page, backup completo da conta de anúncios e réplica de campanhas com IA (nasce pausada) |
| `GESTAO/` | Pauta de segunda, auditoria de sexta, gargalos da equipe |
| `FINANCEIRO/` | Régua de cobrança de honorários, inadimplência, fechamento mensal |

| | Windows | Mac |
|---|---|---|
| Instalar e testar | `deploy\instalar_windows.bat` | `bash deploy/mac/instalar_mac.sh` (ou duplo clique em `deploy/mac/Instalar no Mac.command`) |
| Conferir sem mudar nada | `deploy\instalar_windows.bat /checar` | `bash deploy/mac/instalar_mac.sh --checar` |
| Ligar as rotinas automáticas | `deploy\agendar_tarefas_windows.bat` | `bash deploy/mac/agendar_tarefas_mac.sh` (ou `Agendar rotinas no Mac.command`) |
| Pasta do servidor no `config/.env` | `Z:\CLIENTES` ou `\\SERVIDOR\CLIENTES` | `/Volumes/CLIENTES` (conectar em `smb://SERVIDOR/CLIENTES`) |

Caso fictício de ponta a ponta: `python CONTRATACAO/main.py exemplo`. Cada máquina tem o seu `config/.env`.
**As rotinas automáticas ficam ligadas em UMA máquina só** (um Windows, um Mac ou a VPS); nas demais, só os
comandos sob demanda - senão o cliente recebe mensagem em dobro.

- Guia da equipe: `docs/COMECE_AQUI.md`
- Mapa fase → comando → cargo → rotina → credencial: `docs/MAPA_DO_SISTEMA.md`
- O que falta configurar: `docs/ONBOARDING.md`
- VPS: `docs/DEPLOY_VPS.md`

A IA não protocola e não envia nada ao banco. Toda saída passa por revisão humana.
