"""
Depois que os links de assinatura saem:

1. assinaturas(): consulta o ZapSign; documento assinado e baixado para 00 CONTRATACAO.
2. cobrar_documentos(): confere a pasta do cliente contra o checklist e cobra o que falta
   pelo WhatsApp, no maximo 1 mensagem por dia, nos dias D+1, D+3 e D+7 da assinatura.
   Chegou tudo: agradece uma vez e para. Passou do 3o toque: alerta o Gestor Juridico.
3. painel(): situacao de todos os casos em contratacao.

Agendar `python CONTRATACAO/main.py acompanhar --enviar` 3x ao dia (ver deploy/).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
import ambiente  # noqa: E402,F401  (carrega .env e caminhos)
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mensagens  # noqa: E402
from envio import _tem, whatsapp  # noqa: E402
from pasta_cliente import CONTRATACAO, arquivos_por_item, listar_casos, salvar_caso  # noqa: E402
from relatorio_triagem import status_documentos  # noqa: E402

REGUA_DIAS = (1, 3, 7)


def _hoje():
    return date.today().isoformat()


def assinaturas(base, caso):
    links = caso.get('zapsign') or []
    pendentes = [l for l in links if l.get('status') != 'assinado']
    if not pendentes or not _tem('ZAPSIGN_API_TOKEN'):
        return False
    from zapsign_integration import baixar_pdf_assinado, buscar_documento
    mudou = False
    for l in pendentes:
        doc = buscar_documento(l['token'])
        if not doc or doc.get('status') != 'signed':
            continue
        pdf = baixar_pdf_assinado(doc.get('signed_file')) if doc.get('signed_file') else None
        if pdf:
            nome = caso['qualificacao']['nome'].title()
            destino = os.path.join(base, CONTRATACAO, f"{nome} - {l['documento']} (ASSINADO).pdf")
            with open(destino, 'wb') as f:
                f.write(pdf)
        l['status'], l['assinado_em'] = 'assinado', _hoje()
        mudou = True
        print(f"   {caso['qualificacao']['nome']}: {l['documento']} ASSINADO")
    if links and all(l.get('status') == 'assinado' for l in links) and not caso.get('assinado_em'):
        caso['assinado_em'] = _hoje()
        caso['etapa'] = 'COBRANCA DE DOCUMENTOS'
    return mudou


def faltando(base, caso):
    caso['documentos_status'] = status_documentos(caso['triagem'], arquivos_por_item(base))
    return [s for s in caso['documentos_status']
            if s['obrigatorio'] and s['situacao'] != 'NA PASTA'
            and not (s['id'] == 'procuracao' and caso.get('zapsign'))]  # procuracao ja segue pelo ZapSign


def cobrar_documentos(base, caso, enviar=False):
    falta = faltando(base, caso)
    nome = caso['qualificacao']['nome']
    if not falta:
        if not caso.get('documentos_completos_em'):
            caso['documentos_completos_em'] = _hoje()
            caso['etapa'] = 'DOCUMENTOS COMPLETOS'
            txt = mensagens.documentos_completos(nome)
            print(f'   {nome}: documentos COMPLETOS')
            if enviar:
                whatsapp(caso['qualificacao'].get('telefone'), txt)
        return
    inicio = caso.get('assinado_em') or caso.get('enviado_em')
    if not inicio:
        return  # ainda nao mandou os links: a cobranca comeca depois
    dias = (date.today() - date.fromisoformat(inicio)).days
    toques = caso.setdefault('toques_documentos', [])
    if toques and toques[-1]['data'] == _hoje():
        return  # no maximo 1 mensagem por dia
    devidos = [d for d in REGUA_DIAS if dias >= d]
    if len(toques) >= len(REGUA_DIAS):
        if not caso.get('alerta_gestor_em'):
            caso['alerta_gestor_em'] = _hoje()
            print(f'   ALERTA GESTOR: {nome} completou a regua e ainda faltam {len(falta)} documento(s)')
        return
    if len(devidos) <= len(toques):
        return
    n = len(toques) + 1
    txt = mensagens.cobranca_documentos(nome, falta, n)
    ok = whatsapp(caso['qualificacao'].get('telefone'), txt) if enviar else False
    toques.append({'data': _hoje(), 'toque': n, 'faltando': [f['id'] for f in falta], 'enviado': ok})
    print(f'   {nome}: cobranca {n}/{len(REGUA_DIAS)} de documentos ({len(falta)} faltando)'
          + ('' if enviar else ' [simulado]'))


def _fluxos_cobram_documentos():
    """Com o fluxo 'documentos' ligado em config/fluxos.py, quem cobra e o FLUXOS (evita cobranca em dobro)."""
    try:
        from config.fluxos import ATIVOS
        return 'documentos' in ATIVOS
    except ImportError:
        return False


def acompanhar(enviar=False):
    casos = listar_casos()
    if not casos:
        print('Nenhum caso em contratacao.')
        return
    so_assinaturas = _fluxos_cobram_documentos()
    if so_assinaturas:
        print('   (cobrança de documentos é feita pelo FLUXOS/main.py; aqui só confiro as assinaturas)')
    for base, caso in casos:
        if caso.get('etapa') == 'ENCERRADO':
            continue
        assinaturas(base, caso)
        if so_assinaturas:
            salvar_caso(base, caso)
            continue
        if enviar:
            cobrar_documentos(base, caso, enviar=True)
        else:
            falta = faltando(base, caso)
            print(f"   {caso['qualificacao']['nome']}: {len(falta)} documento(s) faltando [simulado, nada enviado]")
        salvar_caso(base, caso)


def painel():
    casos = listar_casos()
    if not casos:
        print('Nenhum caso em contratacao.')
        return
    hoje = date.today()
    print(f"\n{'CLIENTE':32} {'ETAPA':24} {'DIAS':>4} {'FALTA':>5} {'NOTIFICACAO':>11} {'INICIAL':>10}  ALERTA")
    for base, caso in casos:
        falta = faltando(base, caso)
        inicio = date.fromisoformat(caso.get('data_contrato') or date.today().isoformat())
        prazos = {p['id']: p['data'] for p in caso.get('prazos') or []}
        alerta = []
        for marco in ('notificacao', 'inicial'):
            if not prazos.get(marco):
                continue
            limite = datetime.strptime(prazos[marco], '%d/%m/%Y').date()
            if (limite - hoje).days < 0:
                alerta.append(f'{marco} VENCIDA')
            elif (limite - hoje).days <= 3:
                alerta.append(f'{marco} em {(limite - hoje).days}d')
        if caso.get('alerta_gestor_em'):
            alerta.append('regua esgotada')
        print(f"{caso['qualificacao']['nome'][:32]:32} {caso.get('etapa', '')[:24]:24} {(hoje - inicio).days:>4} "
              f"{len(falta):>5} {prazos.get('notificacao', '-'):>11} {prazos.get('inicial', '-'):>10}  {'; '.join(alerta)}")
