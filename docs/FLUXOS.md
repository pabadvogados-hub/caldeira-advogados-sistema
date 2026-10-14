# Fluxos automáticos do atendimento (`FLUXOS/`)

O card muda de etapa no funil do Atende Direito e o fluxo certo começa. A pessoa responde e a cadência para.
O caso anda e a cobrança acaba. Tudo roda 4 vezes por dia (9h30, 11h30, 14h30 e 17h30) e, sem `--enviar`, só
mostra o que faria.

```
python FLUXOS/main.py rodar             simulação: o que cada fluxo faria hoje (nada sai, nada é gravado)
python FLUXOS/main.py rodar --enviar    de verdade (é o que a rotina agendada roda)
python FLUXOS/main.py etapas            etapas reais do funil x papéis de config/fluxos.py
python FLUXOS/main.py status            quem está em qual fluxo
python FLUXOS/main.py parar --telefone 69999999999 --motivo "pediu para não receber"
python FLUXOS/main.py exemplo           todos os fluxos com dados fictícios
```

## Os fluxos

| Fluxo | Quando começa | O que faz | Quando para |
|---|---|---|---|
| `quentes` | card entra em **Lead Quente** ou **Qualificado** | mensagens no dia 0, 1, 3 e 6 (a 1ª pergunta se já tem advogado ou ação) | a pessoa respondeu (avisa a equipe; "já tenho advogado" vai para **Perdido**) ou acabaram os toques |
| `fechamento` | card entra em **Pós-reunião de Fechamento** | 12 mensagens em 25 dias (D+0, 1, 2, 4, 6, 8, 10, 12, 14, 17, 20, 25), sem pressão | respondeu (avisa a equipe), card saiu da etapa ou acabaram os toques |
| `reaquecimento` | card em **Agora não** | 1 mensagem aos 2, 4, 8 e 12 meses | respondeu: volta para **Lead Quente** e avisa a equipe |
| `urgencia` | lead escreve "leilão", "penhora", "execução", "oficial de justiça", "citação", "vence amanhã"... | **não fala com o lead**: avisa a equipe "LIGAR JÁ" com a frase dele | 1 aviso por assunto a cada 3 dias |
| `boas_vindas` | card entra em **Fechou! Documentos para o contrato** | boas-vindas + pede CNH/RG e comprovante de endereço (ou o endereço escrito); lembrete 1x por dia | chegou foto/arquivo ou endereço com CEP (avisa a equipe); **5 dias sem nada**: card vai para **Ligar: reaquecer documentos** e a equipe liga |
| `assinatura` | contrato enviado ao ZapSign (`CONTRATACAO enviar`) | confere o ZapSign em cada rodada; D+1 a D+6 uma mensagem por dia | assinou: agradece, avisa a equipe, card vai para **Assinado**; **D+7**: passa para a equipe |
| `documentos` | contrato assinado | cobra **só o que o caso precisa**, a cada 2 dias, até 5 toques | documentos completos (agradece, caso vira DOCUMENTOS COMPLETOS, card vai para **Documentos Completos**); notificação enviada, fase judicial ou caso encerrado; 5 toques: passa para a equipe |
| `avisos_fase` | notificação ao banco enviada / ação protocolada | 1 aviso ao cliente em cada marco | cada marco só uma vez |

## Regras que valem para todos (e de onde vieram)

Cada regra abaixo veio de um erro real de cobrança automática em produção:

- **Simulação é o padrão.** Sem `--enviar` nada sai e nada é gravado.
- **1 mensagem por pessoa por dia**, somando todos os fluxos. A pessoa é o telefone (8 últimos dígitos): o mesmo
  cliente já apareceu duas vezes com o nome escrito diferente e recebeu cobrança em dobro.
- **Segunda a sábado, das 8h às 20h**; no máximo 20 envios por rodada.
- **Se alguém da equipe escreveu nas últimas 12h, o robô não manda**: a conversa é humana.
- **A primeira rodada só registra o funil.** Quem já estava nas etapas quando o sistema foi ligado não recebe
  cadência de lead; marcos antigos (notificação já enviada) não viram aviso.
- **Card só anda para frente** na ordem de `config/fluxos.py`. A automação nunca volta um card que uma pessoa adiantou.
- **Nunca fala de lead com quem já é cliente** (tem caso no sistema).
- **`parar --telefone`** tira a pessoa de TODOS os fluxos de uma vez.

Regras da cobrança de documentos (`FLUXOS/regras_documentos.py`):

- **Sem a análise da reunião (triagem), não cobra**: lista genérica mandada às cegas já pediu documento de outro tipo de
  caso a quem nunca teria aquilo. A equipe é avisada para gerar a triagem.
- **O que o cliente disse que não tem sai da lista**, na reunião ("NÃO TEM" na triagem) ou depois, pelo WhatsApp
  ("não tenho extrato", "o banco não me deu a cédula"). A equipe é avisada para combinar prova substituta.
- **Item condicional só com sinal** (laudo de frustração de safra, GTA, IR): só é cobrado quando o cliente disse que tem.
- **Senha gov.br nunca por mensagem**: a equipe pega por ligação. Mensagem que pede extrato leva o aviso "a gente nunca
  pede senha, código nem pagamento por aqui" (cliente tem medo de golpe).
- **"Já entreguei" não se cobra**: se não está na pasta, a equipe acha e guarda.
- **Fase do caso manda**: notificação enviada, fase judicial ou caso encerrado = cobrança encerrada.

## Configurar

1. `config/.env`: `ATENDE_DIREITO_FLOW_TOKEN` (Atende Direito > Configurações > API), `ATENDE_DIREITO_FLOW_CANAL` (id do
   canal de WhatsApp **conectado**), `ATENDE_DIREITO_FLOW_FUNIL` (id do funil de clientes), `FLUXOS_TEL_EQUIPE`
   (WhatsApp que recebe os avisos) e `ZAPSIGN_API_TOKEN`.
2. `python FLUXOS/main.py etapas`: confere se as etapas do funil têm os nomes de `config/fluxos.py` (`ETAPAS`). Ajuste
   os nomes lá ou crie as etapas no funil. Papel sem etapa = fluxo dele desligado.
3. `python FLUXOS/main.py rodar` (simulação) e leia o que sairia. Só então ligue a rotina.
4. Desligar um fluxo: tirar o nome dele de `ATIVOS` em `config/fluxos.py`.

Sem a Flow API (só `ATENDE_DIREITO_TOKEN`, a API antiga), rodam os fluxos de cliente que não dependem do funil
(assinatura, documentos, avisos), mas sem a leitura das conversas: não há poda pelo que o cliente escreveu nem a trava
"equipe escreveu nas últimas 12h".

Com o fluxo `documentos` ligado, o `CONTRATACAO/main.py acompanhar` só confere as assinaturas (para o cliente não receber
duas cobranças).

## Atendimento em tempo real: agente de IA do próprio Atende Direito

A primeira resposta ao lead, na hora, fica com o agente de IA do Atende Direito (Automação > flow com bloco "Agente de
IA"). Os fluxos acima entram depois, pelo funil. Roteiro para colar no agente:

```
Você é do atendimento do escritório Caldeira Advogados Associados, que defende produtor rural com dívida em banco
(custeio, investimento, CPR, cédula rural, execução, leilão de imóvel rural). Fale simples, como gente do campo,
em mensagens curtas (no máximo 3 linhas), sem emoji e sem juridiquês.

Seu papel é entender o caso e passar para a equipe. Pergunte, uma coisa por vez:
1. qual banco e que tipo de financiamento (custeio, investimento, CPR, cédula, cartão, empréstimo);
2. a situação hoje: parcela em dia, atrasada, renegociada, cobrança judicial, leilão marcado;
3. o que produz e onde (cultura ou criação, cidade e estado);
4. valor aproximado da dívida (se a pessoa souber);
5. se já tem advogado cuidando disso.

Nunca: prometa resultado, prazo ou valor; diga chance de ganhar; fale de honorário ou preço; peça documento, senha
ou foto agora; indique outro advogado.
Se a pessoa falar em leilão, penhora, oficial de justiça ou prazo vencendo, diga que vai pedir para alguém da equipe
ligar ainda hoje e encerre passando para o atendimento humano.
Quando tiver as 5 respostas, agradeça, diga que um especialista vai continuar o atendimento e passe para a equipe.
```
