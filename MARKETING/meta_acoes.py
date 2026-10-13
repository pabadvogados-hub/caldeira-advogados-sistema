"""
ACOES NA CONTA DE ANUNCIOS DO META (escrita) - com travas de seguranca.

A integracao INTEGRACOES/meta_ads_integration.py continua SO LEITURA. Tudo que altera a conta
mora aqui, isolado, e so roda quando TODAS as travas passam:

  1. o comando foi chamado com --aplicar (sem isso: so a lista do que seria feito);
  2. existe a credencial propria de escrita META_ACCESS_TOKEN_ACOES no config/.env
     (token de Usuario do Sistema com ads_management). O token de leitura (META_ACCESS_TOKEN,
     ads_read) NAO serve aqui de proposito: a rotina diaria nunca consegue escrever;
  3. a pessoa esta no terminal (nao roda pelo agendador) e DIGITA "SIM" para cada item,
     um por um. Qualquer outra resposta pula o item;
  4. limites fixos no codigo (validar_requisicao):
     - status so pode ir para PAUSED. Nada e ativado por aqui, nunca;
     - orcamento diario de conjunto muda no maximo LIMITE_ORCAMENTO_PCT (20%) por vez, calculado
       sobre o valor lido da API NA HORA (nao sobre o relatorio) e no maximo 1 vez a cada
       INTERVALO_ORCAMENTO_HORAS (72h) no mesmo conjunto;
     - copia (duplicar conjunto/anuncio) nasce PAUSADA (status_option=PAUSED) e e conferida
       logo depois; se por algum motivo vier ativa, e pausada na mesma hora;
     - no maximo MAX_ACOES_POR_RODADA acoes executaveis por rodada.
  5. tudo (simulado, pulado, aplicado, erro) vai para SAIDA/marketing/acoes_log.json.

Chamadas de escrita da Graph API usadas (documentacao: developers.facebook.com/docs/marketing-api):
  POST /{ad_id}                 status=PAUSED                         pausa o anuncio
  POST /{adset_id}              daily_budget=<centavos>               orcamento diario do conjunto
  POST /{adset_id}/copies       deep_copy=true, status_option=PAUSED  copia o conjunto com os anuncios
  POST /{ad_id}/copies          status_option=PAUSED                  copia um anuncio
Pegadinhas:
  - daily_budget vai em CENTAVOS da moeda da conta (R$ 50,00 = 5000).
  - conjunto de campanha com orcamento na CAMPANHA (CBO/Advantage) ou orcamento vitalicio nao tem
    daily_budget: a acao fica bloqueada e o ajuste e feito a mao no Gerenciador.
  - copia profunda de conjunto com muitos anuncios pode exigir copia assincrona na API [CONFERIR no 1o uso].
"""
import getpass
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
import ambiente  # noqa: E402  (carrega .env e caminhos)

import requests  # noqa: E402

LIMITE_ORCAMENTO_PCT = 20          # nunca mexer no orcamento mais que isso por vez
INTERVALO_ORCAMENTO_HORAS = 72     # e no maximo 1 vez a cada 3 dias no mesmo conjunto
INTERVALO_COPIA_DIAS = 7           # nao duplicar o mesmo conjunto mais de 1 vez por semana
MAX_ACOES_POR_RODADA = 10
SUFIXO_COPIA = ' - COPIA TESTE'
VAR_TOKEN = 'META_ACCESS_TOKEN_ACOES'

TIPOS = {
    'pausar_anuncio': 'Pausar anúncio',
    'ajustar_orcamento': 'Ajustar orçamento diário do conjunto',
    'duplicar_conjunto': 'Duplicar conjunto (cópia PAUSADA)',
    'duplicar_anuncio': 'Duplicar anúncio (cópia PAUSADA)',
    'pedir_criativo': 'Pedir novo criativo (tarefa da equipe, não mexe na conta)',
}


class ErroAcao(RuntimeError):
    pass


def reais(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return '-'
    return 'R$ ' + f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


# ============================================================
# LOG
# ============================================================

PASTA_LOG = None   # None = SAIDA/marketing (testes podem apontar para outra pasta)


def caminho_log():
    return os.path.join(PASTA_LOG or ambiente.pasta_saida('marketing'), 'acoes_log.json')


def ler_log():
    try:
        with open(caminho_log(), encoding='utf-8') as f:
            dados = json.load(f)
        return dados if isinstance(dados, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def registrar(acao, modo, resultado, detalhe=None):
    log = ler_log()
    log.append({
        'quando': datetime.now().isoformat(timespec='seconds'),
        'quem': _usuario(),
        'modo': modo,                       # SIMULADO | APLICADO | PULADO | BLOQUEADO | ERRO
        'tipo': acao.get('tipo'),
        'alvo_id': acao.get('alvo_id'),
        'alvo_nome': acao.get('alvo_nome'),
        'de': acao.get('de'),
        'para': acao.get('para'),
        'motivo': acao.get('motivo'),
        'resultado': resultado,
        'detalhe': detalhe,
    })
    with open(caminho_log(), 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)


def _usuario():
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return '?'


def _ultima(tipo, alvo_id, log=None):
    """Data da ultima acao APLICADA desse tipo nesse alvo (ou None)."""
    datas = []
    for e in log if log is not None else ler_log():
        if e.get('modo') == 'APLICADO' and e.get('tipo') == tipo and str(e.get('alvo_id')) == str(alvo_id):
            try:
                datas.append(datetime.fromisoformat(e['quando']))
            except (KeyError, ValueError):
                pass
    return max(datas) if datas else None


# ============================================================
# PROPOSTA (a partir da analise de criativos do trafego.py)
# ============================================================

def _centavos(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def novo_orcamento(atual_centavos, pct):
    """Aplica pct (limitado a +-LIMITE_ORCAMENTO_PCT) sobre o orcamento atual, em centavos."""
    pct = max(-LIMITE_ORCAMENTO_PCT, min(LIMITE_ORCAMENTO_PCT, pct))
    delta = int(atual_centavos * abs(pct) / 100)   # arredonda para baixo: nunca passa do limite
    return atual_centavos + delta if pct > 0 else atual_centavos - delta


def propor(analise, conjuntos, agora=None):
    """
    analise: saida de trafego.analisar_criativos (anuncios com 'recomendacao').
    conjuntos: {adset_id: {'name', 'daily_budget' (centavos), 'effective_status'}}
    Devolve a lista de acoes (dicts), numeradas, com 'executavel' e 'bloqueio'.
    """
    agora = agora or datetime.now()
    log = ler_log()
    acoes, tarefas = [], []

    def add(**a):
        a.setdefault('executavel', True)
        a.setdefault('bloqueio', None)
        (tarefas if a['tipo'] == 'pedir_criativo' else acoes).append(a)

    anuncios = analise.get('anuncios') or []
    for a in anuncios:
        if a['recomendacao'] == 'PAUSAR':
            if (a.get('status') or 'ACTIVE') != 'ACTIVE':
                continue
            add(tipo='pausar_anuncio', alvo_id=a['id'], alvo_nome=a['nome'], conjunto=a.get('conjunto'),
                de='ATIVO', para='PAUSADO', motivo=a['motivo'])
        elif a['recomendacao'] == 'TROCAR CRIATIVO':
            add(tipo='pedir_criativo', alvo_id=a['id'], alvo_nome=a['nome'], conjunto=a.get('conjunto'),
                de='-', para='-', motivo=a['motivo'], executavel=False,
                bloqueio='tarefa humana: produzir novo vídeo/imagem (não há ação automática)')

    # escalar: +20% no conjunto do anuncio vencedor (1 vez por conjunto)
    vistos = set()
    vencedores = sorted([a for a in anuncios if a['recomendacao'] == 'ESCALAR'], key=lambda x: x['cpl'] or 1e9)
    for a in vencedores:
        cid = a.get('conjunto_id')
        if not cid or cid in vistos:
            continue
        vistos.add(cid)
        cj = conjuntos.get(cid) or {}
        atual = _centavos(cj.get('daily_budget'))
        base = dict(tipo='ajustar_orcamento', alvo_id=cid, alvo_nome=cj.get('name') or a.get('conjunto'),
                    motivo=f"anúncio vencedor \"{a['nome']}\": {a['motivo']}")
        if not atual:
            add(**base, de='-', para='-', executavel=False,
                bloqueio='conjunto sem orçamento diário próprio (orçamento na campanha ou vitalício): ajustar à mão')
            continue
        ult = _ultima('ajustar_orcamento', cid, log)
        novo = novo_orcamento(atual, LIMITE_ORCAMENTO_PCT)
        bloq = None
        if ult and agora - ult < timedelta(hours=INTERVALO_ORCAMENTO_HORAS):
            bloq = (f'orçamento deste conjunto já foi mudado em {ult.strftime("%d/%m %H:%M")}; '
                    f'esperar {INTERVALO_ORCAMENTO_HORAS}h entre mudanças')
        add(**base, de=atual, para=novo, pct=LIMITE_ORCAMENTO_PCT, executavel=not bloq, bloqueio=bloq)

    # reduzir: conjunto caro sem nenhum anuncio vencedor
    ref = analise.get('cpl_ref')
    for c in analise.get('conjuntos') or []:
        cid = c.get('id')
        if not ref or cid in vistos or not c.get('gasto'):
            continue
        caro = (c['leads'] == 0 and c['gasto'] >= 3 * ref) or (c['leads'] and c['cpl'] > 1.5 * ref and c['gasto'] >= 3 * ref)
        if not caro:
            continue
        cj = conjuntos.get(cid) or {}
        atual = _centavos(cj.get('daily_budget'))
        if not atual:
            continue
        ult = _ultima('ajustar_orcamento', cid, log)
        bloq = None
        if ult and agora - ult < timedelta(hours=INTERVALO_ORCAMENTO_HORAS):
            bloq = f'orçamento já mudado em {ult.strftime("%d/%m %H:%M")}; esperar {INTERVALO_ORCAMENTO_HORAS}h'
        cpl_txt = reais(c['cpl']) if c['leads'] else 'sem lead'
        add(tipo='ajustar_orcamento', alvo_id=cid, alvo_nome=cj.get('name') or c.get('nome'),
            de=atual, para=novo_orcamento(atual, -LIMITE_ORCAMENTO_PCT), pct=-LIMITE_ORCAMENTO_PCT,
            motivo=f"conjunto caro: gastou {reais(c['gasto'])}, CPL {cpl_txt} (referência {reais(ref)})",
            executavel=not bloq, bloqueio=bloq)

    # copiar a estrutura que funciona: 1 copia PAUSADA do conjunto do melhor anuncio
    if vencedores:
        a = vencedores[0]
        cid = a.get('conjunto_id')
        if cid:
            ult = _ultima('duplicar_conjunto', cid, log)
            bloq = None
            if ult and agora - ult < timedelta(days=INTERVALO_COPIA_DIAS):
                bloq = f'este conjunto já foi duplicado em {ult.strftime("%d/%m")}; esperar {INTERVALO_COPIA_DIAS} dias'
            add(tipo='duplicar_conjunto', alvo_id=cid,
                alvo_nome=(conjuntos.get(cid) or {}).get('name') or a.get('conjunto'),
                de='-', para='cópia PAUSADA', executavel=not bloq, bloqueio=bloq,
                motivo=(f"copiar a estrutura do conjunto do melhor anúncio (\"{a['nome']}\") para testar outra "
                        'região ou público. A cópia nasce PAUSADA: a equipe troca a região/público no Gerenciador '
                        'e só então ativa.'))

    acoes += tarefas   # tarefas da equipe (sem acao na conta) vao por ultimo
    executaveis = 0
    for i, a in enumerate(acoes, 1):
        a['n'] = i
        if a['executavel']:
            executaveis += 1
            if executaveis > MAX_ACOES_POR_RODADA:
                a['executavel'] = False
                a['bloqueio'] = f'limite de {MAX_ACOES_POR_RODADA} ações por rodada'
        a['requisicao'] = requisicao(a) if a['tipo'] in ('pausar_anuncio', 'ajustar_orcamento',
                                                          'duplicar_conjunto', 'duplicar_anuncio') else None
    return acoes


# ============================================================
# REQUISICOES (montagem + validacao das travas)
# ============================================================

def requisicao(acao):
    t, alvo = acao['tipo'], str(acao['alvo_id'])
    if t == 'pausar_anuncio':
        return {'metodo': 'POST', 'caminho': alvo, 'params': {'status': 'PAUSED'}}
    if t == 'ajustar_orcamento':
        return {'metodo': 'POST', 'caminho': alvo, 'params': {'daily_budget': int(acao['para'])}}
    if t == 'duplicar_conjunto':
        return {'metodo': 'POST', 'caminho': f'{alvo}/copies', 'params': {
            'deep_copy': 'true', 'status_option': 'PAUSED',
            'rename_options': json.dumps({'rename_strategy': 'ONLY_TOP_LEVEL_RENAME', 'rename_suffix': SUFIXO_COPIA})}}
    if t == 'duplicar_anuncio':
        return {'metodo': 'POST', 'caminho': f'{alvo}/copies', 'params': {
            'status_option': 'PAUSED', 'rename_options': json.dumps({'rename_suffix': SUFIXO_COPIA})}}
    raise ErroAcao(f'tipo de ação desconhecido: {t}')


PARAMS_PERMITIDOS = {
    'pausar_anuncio': {'status'},
    'ajustar_orcamento': {'daily_budget'},
    'duplicar_conjunto': {'deep_copy', 'status_option', 'rename_options'},
    'duplicar_anuncio': {'status_option', 'rename_options'},
}


def validar_requisicao(acao, req, orcamento_atual=None):
    """Ultima barreira antes do POST. Levanta ErroAcao se qualquer trava for violada."""
    t = acao['tipo']
    if t not in PARAMS_PERMITIDOS:
        raise ErroAcao(f'tipo {t} não pode ser executado')
    if req.get('metodo') != 'POST':
        raise ErroAcao('só POST é permitido')
    params = req.get('params') or {}
    extras = set(params) - PARAMS_PERMITIDOS[t]
    if extras:
        raise ErroAcao(f'parâmetros não permitidos: {sorted(extras)}')
    if 'status' in params and params['status'] != 'PAUSED':
        raise ErroAcao('status diferente de PAUSED é proibido (nada é ativado por aqui)')
    if 'status_option' in params and params['status_option'] != 'PAUSED':
        raise ErroAcao('cópia tem que nascer PAUSADA (status_option=PAUSED)')
    if t == 'ajustar_orcamento':
        novo = int(params['daily_budget'])
        if not orcamento_atual or orcamento_atual <= 0:
            raise ErroAcao('orçamento atual desconhecido: não dá para conferir o limite de 20%')
        variacao = abs(novo - orcamento_atual) * 100.0 / orcamento_atual
        if variacao > LIMITE_ORCAMENTO_PCT + 1e-9:
            raise ErroAcao(f'mudança de {variacao:.1f}% passa do limite de {LIMITE_ORCAMENTO_PCT}%')
    alvo = str(req.get('caminho', '')).split('/')[0]
    if not alvo.isdigit():
        raise ErroAcao(f'id de destino inválido: {alvo!r}')
    return True


# ============================================================
# HTTP (so com o token de escrita)
# ============================================================

def token_acoes():
    return os.getenv(VAR_TOKEN) if ambiente.tem_credencial(VAR_TOKEN) else None


def _base():
    return f"https://graph.facebook.com/{os.getenv('META_API_VERSION') or 'v26.0'}"


def _resposta(r):
    try:
        dados = r.json()
    except ValueError:
        dados = {'texto': r.text[:300]}
    if r.status_code != 200:
        msg = (dados.get('error') or {}).get('message') if isinstance(dados, dict) else None
        raise ErroAcao(f'Meta API {r.status_code}: {msg or str(dados)[:300]}')
    return dados


def _get(caminho, campos, token):
    try:
        r = requests.get(f'{_base()}/{caminho}', params={'fields': campos, 'access_token': token}, timeout=60)
    except requests.RequestException as e:
        raise ErroAcao(f'falha de rede: {e}') from e
    return _resposta(r)


def _post(caminho, params, token):
    try:
        r = requests.post(f'{_base()}/{caminho}', data={**params, 'access_token': token}, timeout=90)
    except requests.RequestException as e:
        raise ErroAcao(f'falha de rede: {e}') from e
    return _resposta(r)


def _garantir_pausado(novo_id, token):
    """Confere a copia recem-criada; se nao estiver PAUSED, pausa na hora."""
    info = _get(novo_id, 'status,effective_status,name', token)
    if info.get('status') != 'PAUSED':
        _post(novo_id, {'status': 'PAUSED'}, token)
        return f"cópia {novo_id} veio {info.get('status')} e foi PAUSADA na hora"
    return f"cópia {novo_id} criada PAUSADA ({info.get('name', '')})"


def executar_uma(acao, token):
    """Executa 1 acao ja confirmada. Devolve texto do resultado."""
    req = requisicao(acao)
    atual = None
    if acao['tipo'] == 'ajustar_orcamento':
        atual = _centavos(_get(acao['alvo_id'], 'daily_budget', token).get('daily_budget'))
        if atual != acao['de']:
            raise ErroAcao(f"orçamento mudou desde a leitura ({reais((acao['de'] or 0) / 100)} -> "
                           f"{reais((atual or 0) / 100)}); rode o comando de novo")
    validar_requisicao(acao, req, atual)
    resp = _post(req['caminho'], req['params'], token)
    if acao['tipo'] == 'duplicar_conjunto':
        novo = resp.get('copied_adset_id')
        return _garantir_pausado(novo, token) if novo else f'resposta sem id da cópia: {resp}'
    if acao['tipo'] == 'duplicar_anuncio':
        novo = resp.get('copied_ad_id')
        return _garantir_pausado(novo, token) if novo else f'resposta sem id da cópia: {resp}'
    return 'ok' if resp.get('success', True) else f'resposta: {resp}'


# ============================================================
# TELA + CONFIRMACAO ITEM A ITEM
# ============================================================

def descrever(a):
    if a['tipo'] == 'ajustar_orcamento' and isinstance(a.get('de'), int):
        de, para = reais(a['de'] / 100), reais(a['para'] / 100)
        sinal = '+' if a['para'] > a['de'] else ''
        mudanca = f"{de}/dia -> {para}/dia ({sinal}{a.get('pct', 0)}%)"
    else:
        mudanca = f"{a.get('de')} -> {a.get('para')}"
    linhas = [f"[{a['n']}] {TIPOS[a['tipo']].upper()}: {a['alvo_nome']} (id {a['alvo_id']})",
              f"     mudança: {mudanca}", f"     motivo: {a['motivo']}"]
    if a.get('bloqueio'):
        linhas.append(f"     NÃO EXECUTÁVEL: {a['bloqueio']}")
    elif a.get('requisicao'):
        r = a['requisicao']
        linhas.append(f"     requisição: {r['metodo']} /{r['caminho']} {json.dumps(r['params'], ensure_ascii=False)}")
    return '\n'.join(linhas)


def terminal_interativo():
    """True so com uma pessoa num console de verdade. No Windows, isatty() da True para o dispositivo NUL
    (agendador, '< nul'), por isso confere tambem o GetConsoleMode. No Mac e no Linux o isatty() basta:
    launchd e cron entregam /dev/null, que nao e terminal (ctypes.windll/msvcrt so existem no Windows)."""
    try:
        if not (sys.stdin and sys.stdin.isatty()):
            return False
        if sys.platform == 'win32':
            import ctypes
            import msvcrt
            modo = ctypes.c_uint32()
            return bool(ctypes.windll.kernel32.GetConsoleMode(msvcrt.get_osfhandle(sys.stdin.fileno()),
                                                              ctypes.byref(modo)))
        return True
    except Exception:  # noqa: BLE001 - na duvida, nao e terminal
        return False


def executar(acoes, aplicar=False, entrada=input, exigir_terminal=True, registrar_log=True):
    """
    Mostra a lista; sem aplicar, so registra como SIMULADO. Com aplicar: exige token de escrita,
    terminal interativo e "SIM" digitado em cada item. Devolve resumo {modo: quantidade}.
    registrar_log=False (dados de exemplo): nao grava no log de verdade.
    """
    reg = registrar if registrar_log else (lambda *a, **k: None)
    print('\nAÇÕES PROPOSTAS' + ('' if aplicar else ' (SIMULAÇÃO: nada será enviado ao Meta)'))
    if not acoes:
        print('  nenhuma ação proposta.')
        return {}
    for a in acoes:
        print(descrever(a))
    resumo = {}

    def conta(modo):
        resumo[modo] = resumo.get(modo, 0) + 1

    if not aplicar:
        for a in acoes:
            reg(a, 'SIMULADO', 'nada enviado (sem --aplicar)')
            conta('SIMULADO')
        print('\nPara executar: rode de novo com --aplicar (precisa de META_ACCESS_TOKEN_ACOES e confirmação item a item).')
        return resumo

    token = token_acoes()
    if not token:
        raise SystemExit(f'\n--aplicar recusado: {VAR_TOKEN} não configurado em config/.env '
                         '(token de Usuário do Sistema com ads_management). Nada foi alterado.')
    if exigir_terminal and not terminal_interativo():
        raise SystemExit('\n--aplicar recusado: precisa de uma pessoa no terminal para confirmar item a item '
                         '(não roda pelo agendador). Nada foi alterado.')

    print('\nCONFIRMAÇÃO ITEM A ITEM. Digite SIM (maiúsculo) para executar; qualquer outra coisa pula.')
    for a in acoes:
        if not a['executavel']:
            reg(a, 'BLOQUEADO', a.get('bloqueio'))
            conta('BLOQUEADO')
            continue
        if a['tipo'] == 'ajustar_orcamento':
            # le o valor de agora e recalcula o limite de 20% sobre ele
            try:
                atual = _centavos(_get(a['alvo_id'], 'daily_budget', token).get('daily_budget'))
            except ErroAcao as e:
                reg(a, 'ERRO', f'não consegui ler o orçamento atual: {e}')
                conta('ERRO')
                continue
            if not atual:
                reg(a, 'BLOQUEADO', 'conjunto sem orçamento diário próprio')
                conta('BLOQUEADO')
                continue
            a['de'], a['para'] = atual, novo_orcamento(atual, a.get('pct', LIMITE_ORCAMENTO_PCT))
            a['requisicao'] = requisicao(a)
        print('\n' + descrever(a))
        try:
            resposta = (entrada(f"   Executar a ação {a['n']}? Digite SIM para confirmar: ") or '').strip()
        except (EOFError, KeyboardInterrupt):
            resposta = ''   # sem ninguem digitando: pula
        if resposta != 'SIM':
            print('   pulada.')
            reg(a, 'PULADO', f'resposta digitada: {resposta!r}')
            conta('PULADO')
            continue
        try:
            resultado = executar_uma(a, token)
        except ErroAcao as e:
            print(f'   ERRO: {e}')
            reg(a, 'ERRO', str(e))
            conta('ERRO')
            continue
        print(f'   FEITO: {resultado}')
        reg(a, 'APLICADO', resultado)
        conta('APLICADO')
    print(f'\nLog: {caminho_log()}')
    return resumo
