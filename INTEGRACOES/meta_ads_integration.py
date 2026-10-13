"""
Integracao com a Meta Marketing API (Facebook/Instagram Ads) - SOMENTE LEITURA.

Regra do escritorio: a automacao NUNCA altera campanha, conjunto, anuncio ou orcamento.
Ela so le os numeros e recomenda; qualquer mudanca e decisao humana, feita no Gerenciador
de Anuncios. Por isso este modulo nao tem nenhuma funcao de escrita (POST).

Credenciais em config/.env:
  META_ACCESS_TOKEN    token de Usuario do Sistema (Business Manager > Usuarios do sistema),
                       com permissao ads_read na conta de anuncio do escritorio
  META_AD_ACCOUNT_ID   id da conta de anuncio (com ou sem o prefixo act_)
  META_API_VERSION     opcional (padrao v26.0)

Funcoes:
  configurado()                                      -> bool
  conta_padrao()                                     -> 'act_...' | None
  listar_contas()                                    -> [ {name, id, ...} ]
  listar_campanhas(conta=None, ativas=False)         -> [ {name, status, objective, ...} ]
  insights(obj_id, level, desde, ate, breakdowns)    -> [ linhas ]   (pagina sozinho)
  leads(actions)                                     -> int  (conversas iniciadas + formularios)
  conversas(actions) / formularios(actions)          -> int
"""
import json
import logging
import os

import requests

log = logging.getLogger('integracoes.meta_ads')

# acoes que contam como lead do escritorio
ACAO_CONVERSA = 'onsite_conversion.messaging_conversation_started_7d'   # conversa no WhatsApp/Messenger
ACOES_FORMULARIO = ('lead', 'onsite_conversion.lead_grouped', 'offsite_conversion.fb_pixel_lead')

CAMPOS_PADRAO = ('campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,'
                 'spend,impressions,reach,clicks,inline_link_clicks,ctr,cpc,frequency,actions')


def _base():
    return f"https://graph.facebook.com/{os.getenv('META_API_VERSION') or 'v26.0'}"


def get_token():
    tok = os.getenv('META_ACCESS_TOKEN', '')
    if not tok or tok.startswith('SEU') or 'AQUI' in tok.upper():
        return None
    return tok


def conta_padrao():
    conta = (os.getenv('META_AD_ACCOUNT_ID') or '').strip()
    if not conta:
        return None
    return conta if conta.startswith('act_') else f'act_{conta}'


def configurado():
    return bool(get_token() and conta_padrao())


class ErroMeta(RuntimeError):
    pass


def _get(caminho_ou_url, params=None):
    """GET na Graph API. Levanta ErroMeta com a mensagem da API em caso de erro."""
    tok = get_token()
    if not tok:
        raise ErroMeta('META_ACCESS_TOKEN nao configurado em config/.env')
    url = caminho_ou_url if caminho_ou_url.startswith('http') else f'{_base()}/{caminho_ou_url}'
    params = dict(params or {})
    if 'access_token=' not in url:
        params['access_token'] = tok
    try:
        r = requests.get(url, params=params, timeout=90)
    except requests.RequestException as e:
        raise ErroMeta(f'falha de rede na Meta API: {e}') from e
    if r.status_code != 200:
        try:
            msg = r.json().get('error', {}).get('message', r.text[:300])
        except ValueError:
            msg = r.text[:300]
        raise ErroMeta(f'Meta API {r.status_code}: {msg}')
    return r.json() or {}


def _paginar(caminho, params):
    dados = _get(caminho, params)
    linhas = list(dados.get('data', []))
    proxima = (dados.get('paging') or {}).get('next')
    paginas = 0
    while proxima and paginas < 50:
        dados = _get(proxima)
        linhas += dados.get('data', [])
        proxima = (dados.get('paging') or {}).get('next')
        paginas += 1
    return linhas


# ============================================================
# LEITURA
# ============================================================

def listar_contas():
    return _paginar('me/adaccounts', {'fields': 'name,account_id,currency,account_status', 'limit': 100})


def listar_campanhas(conta=None, ativas=False):
    conta = conta or conta_padrao()
    camps = _paginar(f'{conta}/campaigns', {
        'fields': 'name,status,effective_status,objective,daily_budget,lifetime_budget',
        'limit': 200,
    })
    if ativas:
        camps = [c for c in camps if c.get('effective_status') == 'ACTIVE']
    return camps


def insights(obj_id=None, level='ad', desde=None, ate=None, date_preset=None,
             breakdowns=None, campos=CAMPOS_PADRAO):
    """
    Insights da conta (ou de uma campanha) no nivel pedido.
    level: 'campaign' | 'adset' | 'ad'
    desde/ate: 'AAAA-MM-DD' (tem prioridade sobre date_preset)
    breakdowns: ex. 'region' (estado de quem viu o anuncio)
    """
    obj_id = obj_id or conta_padrao()
    params = {'level': level, 'fields': campos, 'limit': 500}
    if desde and ate:
        params['time_range'] = json.dumps({'since': desde, 'until': ate})
    else:
        params['date_preset'] = date_preset or 'last_7d'
    if breakdowns:
        params['breakdowns'] = breakdowns
    return _paginar(f'{obj_id}/insights', params)


def _soma_acoes(actions, tipos):
    total = 0.0
    for a in actions or []:
        if a.get('action_type') in tipos:
            total += float(a.get('value') or 0)
    return int(total)


def conversas(actions):
    return _soma_acoes(actions, (ACAO_CONVERSA,))


def formularios(actions):
    # 'lead' e 'onsite_conversion.lead_grouped' podem vir juntos para o mesmo lead: usa o maior
    return max(_soma_acoes(actions, ('lead',)), _soma_acoes(actions, ('onsite_conversion.lead_grouped',)),
               _soma_acoes(actions, ('offsite_conversion.fb_pixel_lead',)))


def leads(actions):
    """Lead do escritorio = conversa iniciada no WhatsApp + formulario de cadastro."""
    return conversas(actions) + formularios(actions)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
    import ambiente  # noqa: F401
    print('Configurado:', configurado())
    if configurado():
        for c in listar_contas():
            print(' Conta:', c.get('name'), c.get('id'))
