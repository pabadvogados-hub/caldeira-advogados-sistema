"""
FLUXOS AUTOMATICOS DO ATENDIMENTO - Caldeira Advogados Associados

Os mesmos fluxos do atendimento automatizado de escritorio de contencioso de volume, adaptados ao
bancario/agro e ao Atende Direito: o card muda de etapa no funil, o fluxo certo comeca; a pessoa
responde, a cadencia para; o caso anda, a cobranca acaba.

    python FLUXOS/main.py rodar                 SIMULACAO: mostra o que cada fluxo faria (nada sai, nada e gravado)
    python FLUXOS/main.py rodar --enviar        de verdade (rotina agendada)
    python FLUXOS/main.py rodar --so documentos,assinatura
    python FLUXOS/main.py etapas                etapas reais do funil x papeis do config/fluxos.py
    python FLUXOS/main.py status                quem esta em qual fluxo
    python FLUXOS/main.py parar --telefone 69999999999 [--motivo "..."]   tira a pessoa de TODOS os fluxos
    python FLUXOS/main.py voltar --telefone 69999999999                   devolve a pessoa aos fluxos
    python FLUXOS/main.py exemplo               roda tudo com dados ficticios (nada sai da maquina)

Fluxos (ligar/desligar em config/fluxos.py, ATIVOS): assinatura, documentos, boas_vindas, avisos_fase,
fechamento, quentes, reaquecimento, urgencia. Regras gerais em FLUXOS/nucleo.py; detalhes em docs/FLUXOS.md.

Credenciais: ATENDE_DIREITO_FLOW_TOKEN, ATENDE_DIREITO_FLOW_CANAL, ATENDE_DIREITO_FLOW_FUNIL (funil e
conversas); sem a Flow API, so os fluxos de cliente rodam, enviando pela API antiga (ATENDE_DIREITO_TOKEN).
ZAPSIGN_API_TOKEN (assinatura); FLUXOS_TEL_EQUIPE (WhatsApp que recebe os avisos internos).
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
import ambiente  # noqa: E402,F401  (carrega .env e caminhos)

from config import fluxos as CFG  # noqa: E402
from FLUXOS import fluxos_clientes, fluxos_leads  # noqa: E402
from FLUXOS.nucleo import Contexto, chave  # noqa: E402

ORDEM_FLUXOS = [   # clientes primeiro: o limite de 1 mensagem/dia por pessoa favorece o que importa mais
    ('assinatura', 'casos', fluxos_clientes.assinatura),
    ('documentos', 'casos', fluxos_clientes.documentos),
    ('boas_vindas', 'cards', fluxos_clientes.boas_vindas),
    ('avisos_fase', 'casos', fluxos_clientes.avisos_fase),
    ('fechamento', 'cards', fluxos_leads.fechamento),
    ('quentes', 'cards', fluxos_leads.quentes),
    ('reaquecimento', 'cards', fluxos_leads.reaquecimento),
    ('urgencia', 'cards', fluxos_leads.urgencia),
]


def atualizar_cards(ctx):
    """Le o funil, grava desde quando cada card esta na etapa e marca os cards da primeira rodada (semente)."""
    try:
        cards = ctx.crm.cards() if ctx.crm.funil_configurado() else []
    except Exception as e:  # noqa: BLE001
        print(f'   não consegui ler o funil ({str(e)[:100]}): fluxos de funil pulados nesta rodada')
        return []
    snap = ctx.estado['cards']
    primeira = ctx.estado.get('semeado_em') is None
    for c in cards:
        s = snap.get(str(c['id']))
        if not s or s.get('etapa') != c['etapa']:
            snap[str(c['id'])] = s = {'etapa': c['etapa'], 'desde': ctx.hoje.isoformat(), 'semente': primeira}
        c['desde'], c['semente'], c['chave'] = date.fromisoformat(s['desde']), s.get('semente', False), chave(c['telefone'])
    if primeira and cards:
        ctx.estado['semeado_em'] = ctx.hoje.isoformat()
        print(f'   primeira rodada: registrei {len(cards)} cards do funil; quem já estava nas etapas não recebe '
              'cadência de lead (só quem entrar daqui para frente)')
    return cards


def preparar(ctx, casos, cards):
    tel_clientes = {chave((c.get('qualificacao') or {}).get('telefone')) for _, c in casos.listar()} - {''}
    por_tel = {c['chave']: c for c in cards if c.get('chave')}
    ctx.e_cliente = lambda card: card.get('chave') in tel_clientes
    ctx.card_por_telefone = lambda tel: por_tel.get(chave(tel))


def rodar(ctx, casos, so=None):
    print(f"=== FLUXOS | {ctx.momento:%d/%m/%Y %H:%M} | {'ENVIO' if ctx.enviar else 'SIMULAÇÃO (nada sai)'} ===")
    cards = atualizar_cards(ctx)
    preparar(ctx, casos, cards)
    for nome, fonte, funcao in ORDEM_FLUXOS:
        if nome not in CFG.ATIVOS or (so and nome not in so):
            continue
        if fonte == 'cards' and not cards:
            continue
        print(f'\n-- {nome}')
        try:
            funcao(ctx, cards if fonte == 'cards' else casos)
        except Exception as e:  # noqa: BLE001 - um fluxo com erro nao derruba os outros
            print(f'   ERRO no fluxo {nome}: {e}')
            ctx.evento('erro', {}, str(e), fluxo=nome)
    if ctx.enviar:
        ctx.salvar()
    tipos = {}
    for ev in ctx.resumo:
        tipos[ev['tipo']] = tipos.get(ev['tipo'], 0) + 1
    print(f'\n=== fim: {tipos or "nada a fazer"} ===')
    return ctx


def cmd_etapas():
    from FLUXOS.crm import CRMAtendeDireito
    crm = CRMAtendeDireito()
    if not crm.funil_configurado():
        raise SystemExit('Configure ATENDE_DIREITO_FLOW_TOKEN e ATENDE_DIREITO_FLOW_FUNIL no config/.env')
    reais = crm.etapas_reais()
    print('Etapas do funil no Atende Direito:')
    for n in reais:
        print(f'  - {n}')
    print('\nPapéis do config/fluxos.py:')
    for papel, nome in CFG.ETAPAS.items():
        ok = nome in reais
        print(f"  {'OK ' if ok else 'FALTA'} {papel:24} -> {nome}")
    print('\nPapel com FALTA: ajuste o nome em config/fluxos.py (ETAPAS) ou crie a etapa no funil.')


def cmd_status(ctx):
    pessoas = ctx.estado['pessoas']
    if not pessoas:
        print('Ninguém em fluxo ainda.')
        return
    for k, p in pessoas.items():
        ativos = [f"{n}({len(f['toques'])})" for n, f in p['fluxos'].items() if not f.get('encerrado') and f.get('toques') is not None]
        print(f"{p.get('nome', '')[:30]:30} {p.get('telefone', ''):15} {'PARADO' if p.get('parado') else '':7} "
              f"último envio {p.get('ultimo_envio', '-'):10} ativos: {', '.join(ativos) or '-'}")


def cmd_parar(ctx, telefone, motivo, voltar=False):
    p = ctx.pessoa(telefone)
    if not p:
        raise SystemExit('Telefone inválido.')
    p['parado'] = not voltar
    p['parado_motivo'] = '' if voltar else (motivo or 'pedido da equipe')
    if not voltar:
        for nome in list(p['fluxos']):
            ctx.encerrar(p, nome, f'parado pela equipe: {p["parado_motivo"]}')
    ctx.salvar()
    print(f"{'Devolvido aos fluxos' if voltar else 'Parado em TODOS os fluxos'}: {p.get('nome') or telefone}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog='FLUXOS', description='Fluxos automáticos do atendimento')
    ap.add_argument('comando', choices=['rodar', 'etapas', 'status', 'parar', 'voltar', 'exemplo'])
    ap.add_argument('--enviar', action='store_true')
    ap.add_argument('--so', help='fluxos separados por vírgula')
    ap.add_argument('--telefone')
    ap.add_argument('--motivo')
    a = ap.parse_args(argv)

    if a.comando == 'exemplo':
        from FLUXOS import exemplo
        return exemplo.rodar_exemplo()
    if a.comando == 'etapas':
        return cmd_etapas()
    from FLUXOS.crm import CRMAtendeDireito
    ctx = Contexto(CRMAtendeDireito(), enviar=a.enviar)
    if a.comando == 'status':
        return cmd_status(ctx)
    if a.comando in ('parar', 'voltar'):
        if not a.telefone:
            raise SystemExit('Informe --telefone')
        return cmd_parar(ctx, a.telefone, a.motivo, voltar=a.comando == 'voltar')
    rodar(ctx, fluxos_clientes.CasosSistema(), so=set(a.so.split(',')) if a.so else None)
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
