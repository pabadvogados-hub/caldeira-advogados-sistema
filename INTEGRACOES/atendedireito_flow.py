"""
Atende Direito - FLOW API (https://api.atendedireito.app, doc em /docs).

E a API que permite os FLUXOS automaticos do escritorio: ler o que o cliente escreveu, saber em que
etapa do funil (CRM) o card esta, mover o card, etiquetar, anotar e mandar mensagem pelo canal certo.
A API antiga (atendedireito_integration.py, app.atendedireito.com.br) so manda texto por telefone.

Credenciais no config/.env:
  ATENDE_DIREITO_FLOW_TOKEN   token do workspace (header X-Flow-Token). Nao e o mesmo da API antiga.
  ATENDE_DIREITO_FLOW_CANAL   id do canal de WhatsApp CONECTADO por onde as mensagens saem
  ATENDE_DIREITO_FLOW_FUNIL   id do funil (pipeline) de clientes do escritorio

Pegadinhas conhecidas desta API:
  - So entrega no canal que tem conexao de WhatsApp VIVA (/whatsapp/connections com connection_state
    'connected'). Canal ativo sem conexao aceita a mensagem e ela fica presa na fila sem erro nenhum;
    quando a conexao volta, a fila sai de uma vez (cuidado com mensagem duplicada).
  - send_status / remote_message_id vem nulos ate em mensagem entregue: nao servem de prova de entrega.
  - sender_type: 'contact' = cliente, 'agent' = pessoa no painel, 'bot' = enviado pela API, 'system' = evento.
  - Documento so por URL publica http (media_url); nao ha upload nem base64.
"""
import logging
import os

import requests

log = logging.getLogger('integracoes.atendedireito_flow')

BASE_URL = 'https://api.atendedireito.app'


def configurado():
    v = os.getenv('ATENDE_DIREITO_FLOW_TOKEN', '')
    return bool(v) and not v.startswith('SEU') and 'AQUI' not in v.upper()


def _headers():
    tok = os.getenv('ATENDE_DIREITO_FLOW_TOKEN')
    if not tok:
        return None
    return {'X-Flow-Token': tok, 'Content-Type': 'application/json'}


def _req(metodo, caminho, *, params=None, json=None, timeout=30):
    h = _headers()
    if not h:
        log.warning('ATENDE_DIREITO_FLOW_TOKEN ausente no .env')
        return None
    try:
        r = requests.request(metodo, BASE_URL + caminho, headers=h, params=params, json=json, timeout=timeout)
    except requests.RequestException as e:
        log.warning(f'{metodo} {caminho}: {e}')
        return None
    if r.status_code not in (200, 201, 204):
        log.warning(f'{metodo} {caminho} -> {r.status_code}: {r.text[:200]}')
        return None
    if r.status_code == 204 or not r.text:
        return {}
    try:
        return r.json()
    except ValueError:
        return {'raw': r.text}


def _data(resp):
    if isinstance(resp, dict) and 'data' in resp:
        return resp['data']
    return resp


def _lista(resp):
    d = _data(resp)
    if isinstance(d, dict):
        d = d.get('items') or d.get('data') or d.get('messages') or d.get('conversations') or []
    return d or []


def digitos(tel):
    return ''.join(c for c in str(tel or '') if c.isdigit())


def mesmo_telefone(a, b):
    """Compara pelos 8 ultimos digitos: casa com/sem 55, DDD e nono digito."""
    da, db = digitos(a)[-8:], digitos(b)[-8:]
    return len(da) == 8 and da == db


# ============================================================
# CANAIS E SAUDE DA CONEXAO
# ============================================================

def listar_canais():
    return _lista(_req('GET', '/api/flow/channels'))


def listar_conexoes_whatsapp():
    return _lista(_req('GET', '/api/flow/whatsapp/connections'))


def canal_conectado():
    """(ok, texto). ok=False quando o canal do .env nao tem conexao viva: NAO mandar nada."""
    canal = os.getenv('ATENDE_DIREITO_FLOW_CANAL')
    if not canal:
        return False, 'ATENDE_DIREITO_FLOW_CANAL não configurado'
    for c in listar_conexoes_whatsapp():
        ids = {c.get('channel_id'), c.get('id'), (c.get('channel') or {}).get('id')}
        if canal in ids:
            estado = c.get('connection_state') or c.get('status')
            return estado == 'connected', f'canal {canal}: {estado or "sem conexão"}'
    return False, f'canal {canal} sem conexão de WhatsApp'


# ============================================================
# CONTATOS
# ============================================================

def buscar_contatos(texto):
    return _lista(_req('POST', '/api/flow/contacts/search', json={'query': texto}))


def contato_por_telefone(telefone):
    """Contato do workspace com o mesmo celular (procura pelos ultimos digitos)."""
    d = digitos(telefone)
    if len(d) < 8:
        return None
    for termo in (d[-11:], d[-9:], d[-8:]):
        for c in buscar_contatos(termo) or []:
            if mesmo_telefone(c.get('phone') or c.get('phone_number') or c.get('number'), d):
                return c
    return None


def mensagens_do_contato(contact_id, limite=200):
    return _lista(_req('GET', f'/api/flow/contacts/{contact_id}/messages', params={'limit': limite}))


def textos_do_cliente(telefone, limite=200):
    """Textos (e audios ja transcritos, quando a plataforma transcreve) que o CLIENTE mandou."""
    c = contato_por_telefone(telefone)
    if not c:
        return []
    saida = []
    for m in mensagens_do_contato(c.get('id'), limite):
        if (m.get('sender_type') or '') != 'contact':
            continue
        texto = m.get('content') or m.get('text') or m.get('body') or m.get('transcription') or ''
        if isinstance(texto, dict):
            texto = texto.get('text') or texto.get('body') or ''
        if str(texto).strip():
            saida.append(str(texto))
    return saida


def add_nota_contato(contact_id, texto):
    return _req('POST', f'/api/flow/contacts/{contact_id}/notes', json={'content': texto})


def listar_tags():
    return _lista(_req('GET', '/api/flow/tags'))


def add_tag_contato(contact_id, tag_id):
    return _req('POST', f'/api/flow/contacts/{contact_id}/tags/{tag_id}')


# ============================================================
# CONVERSAS E MENSAGENS
# ============================================================

def conversas_do_contato(contact_id):
    return _lista(_req('GET', '/api/flow/conversations/filter', params={'contact_id': contact_id, 'limit': 20}))


def enviar_texto(telefone, texto):
    """
    Manda texto pelo canal do .env. (ok, detalhe). Recusa se o canal nao estiver conectado,
    para a mensagem nao ficar presa na fila e sair dobrada depois.
    """
    ok, estado = canal_conectado()
    if not ok:
        return False, estado
    c = contato_por_telefone(telefone)
    if not c:
        return False, 'contato não encontrado no Atende Direito'
    payload = {'contact_id': c.get('id'), 'channel_id': os.getenv('ATENDE_DIREITO_FLOW_CANAL'),
               'message_type': 'text', 'content': texto}
    conv = next((x for x in conversas_do_contato(c.get('id')) if x.get('channel_id') == payload['channel_id']), None)
    if conv:
        payload['conversation_id'] = conv.get('id')
    r = _req('POST', '/api/flow/messages/send', json=payload)
    return (r is not None), ('enviada' if r is not None else 'API recusou o envio')


# ============================================================
# FUNIL (CRM): etapas e cards
# ============================================================

def listar_pipelines():
    return _lista(_req('GET', '/api/flow/pipelines'))


def board_do_pipeline(pipeline_id):
    return _data(_req('GET', f'/api/flow/pipelines/{pipeline_id}/board')) or {}


def etapas(pipeline_id):
    """{nome_da_etapa: id} do funil."""
    board = board_do_pipeline(pipeline_id)
    lista = board if isinstance(board, list) else (board.get('stages') or board.get('pipeline_stages')
                                                   or board.get('columns') or [])
    return {(e.get('name') or '').strip(): e.get('id') for e in lista if isinstance(e, dict)}


def negocios_do_pipeline(pipeline_id, limite=100):
    out, pagina = [], 1
    while pagina <= 50:
        lote = _lista(_req('GET', '/api/flow/businesses',
                           params={'pipeline_id': pipeline_id, 'page': pagina, 'limit': limite}))
        if not lote:
            break
        out.extend(lote)
        if len(lote) < limite:
            break
        pagina += 1
    return out


def mover_negocio(business_id, stage_id):
    return _req('PUT', f'/api/flow/businesses/{business_id}/stage', json={'pipeline_stage_id': stage_id})


def criar_negocio(pipeline_id, contact_id, stage_id):
    return _data(_req('POST', f'/api/flow/pipelines/{pipeline_id}/business/create',
                      json={'contact_id': contact_id, 'pipeline_stage_id': stage_id}))


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
    import ambiente  # noqa: F401
    print('Configurado:', configurado())
    if configurado():
        print('Canal:', canal_conectado())
        for p in listar_pipelines():
            print('Funil:', p.get('id'), p.get('name'))
