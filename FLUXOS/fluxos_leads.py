"""
Fluxos de LEAD (antes do contrato): cadencias que param quando a pessoa responde.

  quentes        card em Lead Quente/Qualificado: toques no dia 0, 1, 3 e 6.
                 Respondeu: para e avisa a equipe. Disse que ja tem advogado/acao: vai para Perdido.
  fechamento     card em Pos-reuniao de fechamento: 12 toques em 25 dias. Respondeu ou saiu da etapa: para.
  reaquecimento  card em "Agora nao": uma mensagem aos 2, 4, 8 e 12 meses. Respondeu: volta para Lead Quente.
  urgencia       lead falou em leilao, penhora, execucao, oficial de justica, citacao...: avisa a equipe
                 para LIGAR JA (sem mandar nada ao lead).

Nunca falam com quem ja e cliente (tem caso no sistema) e nao disparam para card que ja estava na etapa
quando o sistema foi ligado (a primeira rodada so registra o funil).
"""
import re
from datetime import datetime, timedelta

from config import fluxos as CFG
from FLUXOS import textos

DIAS_QUENTES = [0, 1, 3, 6]
DIAS_FECHAMENTO = [0, 1, 2, 4, 6, 8, 10, 12, 14, 17, 20, 25]
DIAS_REAQUECIMENTO = [60, 120, 240, 365]

JA_TEM_ADVOGADO = re.compile(r'j[aá]\s+(tenho|tem|estou\s+com|to\s+com|t[oô]\s+com)\s+(um\s+)?advogad|'
                             r'j[aá]\s+(entrei|entramos|tenho)\s+(com\s+)?(uma\s+)?a[cç][aã]o|meu\s+advogado', re.I)
URGENTE = re.compile(r'leil[aã]o|penhor|execu[cç][aã]o|oficial de justi[cç]a|cita[cç][aã]o|intima[cç][aã]o|'
                     r'busca e apreens|consolida[cç][aã]o da propriedade|tomar (a |minha )?(terra|fazenda|propriedade|'
                     r'casa)|vence (amanh[aã]|hoje|essa semana)|negativ', re.I)


def _respostas(ctx, card, desde):
    return [m for m in ctx.crm.mensagens(card['telefone'])
            if m['quem'] == 'cliente' and m['quando'] and m['quando'] >= desde]


def _cadencia(ctx, card, nome_fluxo, dias, texto, ao_responder):
    pessoa = ctx.pessoa(card['telefone'], card['nome'])
    if not pessoa:
        print(f"   [{nome_fluxo}] {card['nome']}: card sem telefone")
        return
    f = ctx.fluxo(pessoa, nome_fluxo, inicio=card['desde'], reiniciar_se_mudou=True)
    if f['encerrado']:
        return
    if f['toques']:
        primeiro = datetime.fromisoformat(f['toques'][0].get('quando') or f['toques'][0]['data'])
        resp = _respostas(ctx, card, primeiro)
        if resp:
            ctx.encerrar(pessoa, nome_fluxo, 'a pessoa respondeu')
            ao_responder(ctx, card, pessoa, resp)
            return
    n = len(f['toques'])
    if n >= len(dias):
        ctx.encerrar(pessoa, nome_fluxo, 'cadência completa sem resposta')
        return
    if (ctx.hoje - card['desde']).days >= dias[n]:
        ctx.mandar(pessoa, nome_fluxo, texto(n + 1, card['nome']), toque=n + 1)


def _trecho(resp):
    return (resp[-1]['texto'] or f"[{resp[-1]['tipo']}]")[:160]


def quentes(ctx, cards):
    def respondeu(ctx, card, pessoa, resp):
        if any(JA_TEM_ADVOGADO.search(m['texto'] or '') for m in resp):
            ctx.mover(card, 'perdido')
            ctx.avisar_equipe(pessoa, 'ja_tem_advogado', f'disse que já tem advogado/ação: "{_trecho(resp)}"')
        else:
            ctx.avisar_equipe(pessoa, 'lead_respondeu', f'lead quente respondeu: "{_trecho(resp)}". Ligar.')
    for card in cards:
        if card['papel'] in ('lead_quente', 'qualificado') and not card['semente'] and not ctx.e_cliente(card):
            _cadencia(ctx, card, 'quentes', DIAS_QUENTES, textos.quentes, respondeu)


def fechamento(ctx, cards):
    def respondeu(ctx, card, pessoa, resp):
        ctx.avisar_equipe(pessoa, 'fechamento_respondeu', f'respondeu na cadência de fechamento: "{_trecho(resp)}"')
    em_fechamento = set()
    for card in cards:
        if card['papel'] == 'pos_reuniao' and not card['semente'] and not ctx.e_cliente(card):
            em_fechamento.add(card['chave'])
            _cadencia(ctx, card, 'fechamento', DIAS_FECHAMENTO, textos.fechamento, respondeu)
    # saiu da etapa: a cadencia acaba
    for k, p in ctx.estado['pessoas'].items():
        f = p['fluxos'].get('fechamento')
        if f and not f.get('encerrado') and k not in em_fechamento:
            ctx.encerrar(p, 'fechamento', 'card saiu da etapa de pós-reunião')


def reaquecimento(ctx, cards):
    def respondeu(ctx, card, pessoa, resp):
        ctx.mover(card, 'lead_quente')
        ctx.avisar_equipe(pessoa, 'reaquecido', f'voltou a falar depois do "agora não": "{_trecho(resp)}"')
    for card in cards:
        if card['papel'] == 'nao_agora' and not ctx.e_cliente(card):
            _cadencia(ctx, card, 'reaquecimento', DIAS_REAQUECIMENTO, textos.reaquecimento, respondeu)


def urgencia(ctx, cards):
    for card in cards:
        if card['papel'] not in CFG.ETAPAS_DE_LEAD or ctx.e_cliente(card):
            continue
        pessoa = ctx.pessoa(card['telefone'], card['nome'])
        if not pessoa:
            continue
        visto = pessoa.get('urgencia_visto_ate')
        desde = datetime.fromisoformat(visto) if visto else ctx.momento - timedelta(days=3)
        achou = next((m for m in _respostas(ctx, card, desde) if URGENTE.search(m['texto'] or '')), None)
        if achou:
            palavra = URGENTE.search(achou['texto']).group(0)
            ctx.avisar_equipe(pessoa, 'urgencia', f'LIGAR JÁ: falou em "{palavra}": "{achou["texto"][:160]}"')
        pessoa['urgencia_visto_ate'] = ctx.momento.isoformat(timespec='seconds')
