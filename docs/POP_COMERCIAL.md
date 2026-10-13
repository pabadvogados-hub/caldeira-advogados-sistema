# POP - Comercial e Captação (Caldeira Advogados Associados)

Do anúncio até o "fechou": SDR → Closer → Relatório de Triagem → fase de contratação.
Espelha o FLUXO INICIAL do Fluxo do Serviço (Cliente envia mensagem → SDR responde e agenda → Closer faz reunião e
fecha → contrato ao Financeiro e relatório ao Gestor) e as rotinas de marketing combinadas na implantação.

Comandos: `python COMERCIAL/main.py <comando>` (ajuda: `python COMERCIAL/main.py -h`).

## Visão geral

| Etapa | Quem | O que a automação faz | O que continua humano |
|---|---|---|---|
| Lead chega (anúncio no Meta, calculadora de juros, Instagram, indicação) | Marketing | Radar mostra onde anunciar; relatório diário diz o que performa | Criar/ajustar anúncios e orçamento no Gerenciador |
| SDR responde e qualifica | SDR (IA no Atende Direito) | Responde na hora, faz as perguntas uma a uma, agenda a reunião, deixa nota interna | Assumir os URGENTES e os fora do foco |
| Nota e resumo do lead | SDR | `sdr` lê a conversa exportada: nota 0-100, faltantes, próxima pergunta, **Resumo para o Closer** com proposta sugerida | Conferir o resumo |
| Reunião de fechamento | Closer | Roteiro em `docs/ROTEIRO_CLOSER.md` (o que colher por operação, objeções, gravação) | Conduzir, negociar, fechar |
| Relatório de Triagem ao Gestor | Closer | `CONTRATACAO/main.py novo` monta o relatório da transcrição da reunião | Gestor decide a estratégia |
| Contrato ao Financeiro | Closer | `RESUMO PARA O FINANCEIRO.txt` + cobrança no Asaas (fase de contratação) | Financeiro confere |
| Auditoria do atendimento | Gestor | `auditoria-atendimento`: tempo de resposta, sem resposta, origem, quem fecha mais, fluxo | Reunião de sexta, correções |

## Passo a passo do lead

1. **Lead chama no WhatsApp** (Atende Direito). O agente SDR (prompt em `COMERCIAL/prompt_sdr_atende_direito.md`)
   responde em segundos, qualifica e oferece a reunião. Urgente (execução, leilão, vencimento em poucos dias):
   passa na hora para um humano.
2. **Nota e resumo**: exportar a conversa (Atende Direito ou WhatsApp → Exportar conversa → sem mídia) e rodar
   `python COMERCIAL/main.py sdr "conversa.txt"`.
   Sai em `SAIDA/sdr/`: `.json` (dados), `Resumo para o Closer.txt` (colar no CRM) e `.docx` (timbrado).
   - **QUALIFICADO** (nota ≥ 60, produtor rural com dívida rural confirmada, ou previdenciário com dados): Closer liga.
   - **EM QUALIFICACAO**: o SDR manda a "próxima pergunta" sugerida e roda de novo.
   - **FORA DO FOCO**: humano avalia (não é produtor, dívida não rural, outro assunto).
   - Sem `ANTHROPIC_API_KEY` (ou `--sem-ia`): pré-análise por palavras-chave, **nunca** marca como qualificado.
3. **Proposta**: o resumo traz o pacote sugerido (Extrajudicial / Extrajudicial + Judicial / Embargos à execução /
   Previdenciário rural / Avaliar). Valores vêm da tabela `PROPOSTAS` em `COMERCIAL/config_comercial.py`;
   enquanto o escritório não preencher, saem como `[DEFINIR PELO ESCRITÓRIO]`.
4. **Reunião do Closer** gravada, seguindo `docs/ROTEIRO_CLOSER.md`.
5. **Fechou**: `CADASTRO.txt` + `python CONTRATACAO/main.py novo ...` (POP da fase de contratação).
   Contrato ao Financeiro e Relatório de Triagem ao Gestor no mesmo dia.
6. **Registrar o resultado no CRM** (fechou / perdido + motivo / retorno marcado). A auditoria cobra isso.

## Rotinas

| Quando | Comando | Quem lê | O que fazer com o resultado |
|---|---|---|---|
| Todo dia, 8h | `python COMERCIAL/main.py meta-ads --dias 1` | Responsável pelo tráfego (esposa do titular) | Ler ALERTAS e O QUE AVALIAR; mudanças feitas **à mão** no Gerenciador de Anúncios |
| Segunda, 8h | `python COMERCIAL/main.py meta-ads --dias 7` | Responsável pelo tráfego + titular | Decidir verba da semana (aumentar no máximo 20% a cada 2-3 dias no que funciona) |
| Sexta, 16h | `python COMERCIAL/main.py auditoria-atendimento --dias 7` | Gestor + SDR + Closers | Reunião de sexta: tempo de resposta, leads sem resposta, fluxo não seguido, quem fecha mais |
| Dia 5 de cada mês | `python COMERCIAL/main.py meta-ads --dias 30` e `python COMERCIAL/main.py radar --uf RO,MT` | Titular + tráfego | Comparar custo por lead por região com o radar; ajustar cidades/raio dos anúncios |
| Quando mudar o número | `python COMERCIAL/main.py calculadora --whatsapp 5569XXXXXXXXX` | - | Publicar de novo o `COMERCIAL/calculadora/index.html` |

Saídas em `SAIDA/meta_ads/`, `SAIDA/auditoria_atendimento/`, `SAIDA/radar/` (arquivo `.txt` para ler no celular,
`.html` para abrir no navegador, `.json` para histórico).

**Agendar no Windows** (Agendador de Tarefas; ajustar o caminho do Python e da pasta):
```
schtasks /Create /TN "Caldeira Meta Ads diario" /SC DAILY /ST 08:00 /TR "cmd /c cd /d C:\CALDEIRA_ADVOGADOS && python COMERCIAL\main.py meta-ads --dias 1"
schtasks /Create /TN "Caldeira Auditoria atendimento" /SC WEEKLY /D FRI /ST 16:00 /TR "cmd /c cd /d C:\CALDEIRA_ADVOGADOS && python COMERCIAL\main.py auditoria-atendimento --dias 7"
schtasks /Create /TN "Caldeira Radar mensal" /SC MONTHLY /D 5 /ST 07:00 /TR "cmd /c cd /d C:\CALDEIRA_ADVOGADOS && python COMERCIAL\main.py radar"
```

## Indicadores do comercial

| Indicador | Fonte | Como calcular |
|---|---|---|
| Custo por lead (CPL) | `meta-ads` | gasto ÷ (conversas iniciadas + formulários) |
| Tempo da 1ª resposta | `auditoria-atendimento` | mediana; meta 15 min, ideal 5 min |
| Taxa de qualificação | `auditoria-atendimento` | qualificados ÷ conversas, por origem e por SDR |
| Taxa de fechamento | `auditoria-atendimento` | fechados ÷ qualificados, por Closer |
| **Custo por contrato** | os dois | gasto no Meta no mês ÷ contratos fechados vindos do Meta no mês |
| Leads sem resposta | `auditoria-atendimento` | conversas sem nenhuma resposta (e há mais de 24h) |

## Radar de crédito rural

`python COMERCIAL/main.py radar [--uf RO,MT] [--ano 2025] [--mt-todo]`
- Fonte: SICOR/Banco Central (contratos de crédito rural emitidos no ano, por município) + IBGE. Dado público.
- Índice 0-100 = 40% quantidade de contratos + 35% valor financiado + 25% custeio de soja e bovinos
  (pesos em `config_comercial.RADAR`). No MT a sugestão considera só o **Norte Mato-grossense** (`--mt-todo` libera).
- O servidor do Banco Central oscila: o radar baixa mês a mês, guarda os meses prontos em `SAIDA/radar/cache/`
  e, se algum mês falhar, sai marcado **INCOMPLETO**. Basta rodar de novo.
- Limite: é volume de crédito tomado, não inadimplência por município nem nome de ninguém. Serve para escolher
  **onde mostrar anúncio institucional**, nunca para abordar pessoas (Provimento 205).

## Calculadora de juros (captação)

`COMERCIAL/calculadora/index.html`: página única, sem internet, responsiva. O produtor informa valor, taxa (a.m. ou
a.a.), número de parcelas (anuais, semestrais ou mensais), Price ou SAC, carência (juros pagos ou somados) e, se
quiser, custos da liberação e uma taxa para comparar. Mostra parcela, total pago, total de juros, taxa efetiva anual,
custo efetivo anual e tabela. Texto informativo sobre prorrogação (MCR 2.6.4 e Súmula 298/STJ) sem promessa, aviso
de que não é consultoria, botão de WhatsApp (com o resumo da simulação, se a pessoa marcar). Não coleta dados.
Publicar no site do escritório e usar o link nos anúncios e na bio do Instagram.

## Auditoria do atendimento - de onde vem o dado

1. **API Flow do Atende Direito** (`ATENDE_DIREITO_FLOW_TOKEN`): conversas e mensagens com horário → mede tudo.
   Primeiro uso: conferir 3 conversas no painel (nomes de campo tratados de forma defensiva).
2. **API antiga** (`ATENDE_DIREITO_TOKEN`, a mesma do envio de mensagens): só lista contatos; **não traz o
   histórico**, então não mede tempo de resposta. O relatório sai parcial e avisa.
3. **CSV exportado** (`--csv arquivo.csv`, separador `;` ou `,`). Colunas reconhecidas (o nome pode variar):
   `contato`, `telefone`, `origem`, `atendente` (SDR), `closer`, `primeira_mensagem` (DD/MM/AAAA HH:MM),
   `primeira_resposta`, `qualificado` (sim/não), `reuniao_agendada`, `fechou`, `etiquetas` (ou status/etapa),
   `motivo_perda`. Modelo: `COMERCIAL/exemplos/ATENDIMENTO_EXEMPLO.csv`.
4. `--exemplo`: dados fictícios.

Para a auditoria saber quem fechou, as **etiquetas/etapas do CRM** precisam usar as palavras de
`config_comercial.ATENDIMENTO` (ex.: "Fechou", "Contrato assinado", "Qualificado", "Reunião agendada", "Perdido").

## Checklist do anúncio (Provimento 205/2021) - antes de publicar

- [ ] Informativo e sóbrio: explica um direito ou um problema do produtor; não "vende" causa.
- [ ] Sem promessa de resultado, sem "garantia", sem "100%", sem "causa ganha", sem prazo de resultado.
- [ ] Sem preço, desconto, gratuidade ou "primeira consulta grátis" como chamariz.
- [ ] Sem sensacionalismo, medo exagerado ou ataque a banco/concorrente; sem casos de clientes identificáveis.
- [ ] Identificação do escritório e do advogado responsável (nome e OAB) no perfil/página de destino.
- [ ] Chamada discreta ("Tire suas dúvidas com a equipe", "Converse com o escritório").
- [ ] Segmentação por região e interesse é permitida; contato ativo com pessoa que não procurou o escritório, não.

## Travas de segurança

- **Meta Ads:** o relatório deste módulo só lê. Pausar anúncio, ajustar orçamento (no máximo 20% por vez) ou duplicar (nasce pausado) só pelo `python MARKETING/main.py acoes --aplicar`, com token próprio `META_ACCESS_TOKEN_ACOES` e confirmação digitada item a item. Ver `docs/POP_MARKETING_TRAFEGO.md`.
- **Atende Direito: somente leitura** na auditoria; o SDR de IA roda dentro do Atende Direito, com o prompt aprovado.
- Nada é enviado ao cliente por estes comandos. Sem credencial, o comando para ou usa `--exemplo`.
- SDR sem IA nunca marca lead como qualificado. Nenhum valor de honorário é inventado.
- Credenciais só no `config/.env` (nunca no código).

## Variáveis do `config/.env` usadas aqui

```
ANTHROPIC_API_KEY=            # SDR de IA (sdr)
MODELO_SDR=                   # opcional; padrão = MODELO_EXTRACAO ou claude-sonnet-5
META_ACCESS_TOKEN=            # token de Usuário do Sistema com ads_read (Business Manager do escritório)
META_AD_ACCOUNT_ID=           # id da conta de anúncio (com ou sem act_)
META_API_VERSION=             # opcional; padrão v26.0 (versões antigas são desligadas pelo Meta)
ATENDE_DIREITO_FLOW_TOKEN=    # opcional; API Flow (mede tempo de resposta)
ATENDE_DIREITO_TOKEN=         # já existe (API antiga; auditoria parcial)
```
