"""
Fluxos automaticos do atendimento (FLUXOS/): quais estao ligados e quais etapas do funil do
Atende Direito disparam cada um.

ETAPAS: papel do fluxo -> NOME EXATO da etapa (coluna) no funil de clientes do Atende Direito.
Conferir os nomes com `python FLUXOS/main.py etapas` (lista as etapas reais do funil e mostra
quais papeis ficaram sem etapa). Papel sem etapa = o fluxo que depende dele fica desligado.

ORDEM: ordem das etapas no funil. A automacao so move card PARA FRENTE nessa ordem (nunca volta um
card que uma pessoa adiantou). Etapas de saida (perdido, nao_agora) aceitam vir de qualquer etapa.
"""

# Fluxos ligados. Tirar daqui desliga o fluxo sem mexer em codigo.
ATIVOS = [
    'assinatura',       # cobra a assinatura no ZapSign (D+1 a D+6; D+7 passa para a equipe)
    'documentos',       # cobra os documentos do caso depois da assinatura (substitui a cobranca do CONTRATACAO)
    'boas_vindas',      # card em "fechou": boas-vindas + documentos para o contrato; 5 dias sem nada -> ligar
    'avisos_fase',      # avisa o cliente quando a notificacao sai e quando a acao e protocolada
    'fechamento',       # pos-reuniao de fechamento: 12 toques em 25 dias, para quando o lead responde
    'quentes',          # lead quente/qualificado: D0, D1, D3, D6
    'reaquecimento',    # "agora nao": 2, 4, 8 e 12 meses
    'urgencia',         # lead falou em leilao/penhora/execucao: avisa a equipe para ligar ja
]

ETAPAS = {
    'lead_novo': 'Novo Lead',
    'lead_quente': 'Lead Quente',
    'qualificado': 'Qualificado',
    'reuniao': 'Reunião Agendada',
    'pos_reuniao': 'Pós-reunião de Fechamento',
    'fechou': 'Fechou! Documentos para o contrato',
    'ligar_reaquecer': 'Ligar: reaquecer documentos',
    'contrato_enviado': 'Contrato no ZapSign',
    'assinado': 'Assinado',
    'aguardando_documentos': 'Aguardando Documentos',
    'documentos_completos': 'Documentos Completos',
    'perdido': 'Perdido',
    'nao_agora': 'Agora não',
}

ORDEM = ['lead_novo', 'lead_quente', 'qualificado', 'reuniao', 'pos_reuniao', 'fechou', 'ligar_reaquecer',
         'contrato_enviado', 'assinado', 'aguardando_documentos', 'documentos_completos']
SAIDAS = ['perdido', 'nao_agora']

# etapas de lead (os fluxos de lead so olham estas)
ETAPAS_DE_LEAD = ['lead_novo', 'lead_quente', 'qualificado', 'reuniao', 'pos_reuniao']

# limites gerais
HORARIO = (8, 20)                # so envia das 8h as 20h ...
DIAS_DA_SEMANA = 6               # ... de segunda (0) a sabado (5)
MAX_ENVIOS_POR_RODADA = 20
HORAS_SILENCIO_SE_EQUIPE_ESCREVEU = 12
