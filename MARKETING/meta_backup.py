"""
BACKUP E MAPA COMPLETO DA CONTA DE ANUNCIOS DO META (somente leitura).

Copia TUDO o que existe na conta para uma pasta local, para:
  - ter o historico mesmo que alguem apague campanhas na conta;
  - saber exatamente como cada campanha foi montada (publico, orcamento, texto, formulario);
  - servir de base para o MARKETING/meta_replicar.py recriar campanhas.

Uso:
    python MARKETING/main.py backup                  dados + mapa + criativos + imagens
    python MARKETING/main.py backup --videos         tambem baixa os videos originais da biblioteca
    python MARKETING/main.py backup --sem-midia      so os dados (sem baixar imagem nem video)

Sai em SAIDA/meta_ads/backup/AAAA-MM-DD/:
    bruto.json          tudo o que a API devolveu (base da replicacao)
    MAPA_COMPLETO.md    campanha > conjunto > anuncio, com publico, orcamento e resultado
    CRIATIVOS.md        cada criativo unico, com os textos inteiros e o resultado somado
    campanhas.csv / conjuntos.csv / anuncios.csv
    midia/imagens, midia/videos

Limites do Meta que o backup respeita:
  - resultados so existem para os ultimos 37 meses (a API recusa datas mais antigas);
  - videos que pertencem a Pagina (e nao a biblioteca da conta) e perguntas dos formularios de lead
    so abrem com acesso de conteudo/leads na Pagina; sem isso ficam listados como pendencia.
Nao usa nenhum POST: so le.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
import ambiente  # noqa: E402  (carrega .env e caminhos)

import requests  # noqa: E402

import meta_ads_integration as meta  # noqa: E402

CAMPOS_CAMPANHA = ('id,name,objective,status,effective_status,buying_type,bid_strategy,daily_budget,lifetime_budget,'
                   'special_ad_categories,special_ad_category_country,created_time,start_time,stop_time,'
                   'is_adset_budget_sharing_enabled,smart_promotion_type')
CAMPOS_CAMPANHA_MIN = 'id,name,objective,status,effective_status,daily_budget,lifetime_budget,created_time'
CAMPOS_CONJUNTO = ('id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,optimization_goal,'
                   'billing_event,bid_strategy,bid_amount,destination_type,promoted_object,targeting,attribution_spec,'
                   'start_time,end_time,created_time,pacing_type,frequency_control_specs,is_dynamic_creative')
CAMPOS_CONJUNTO_MIN = ('id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,optimization_goal,'
                       'billing_event,bid_strategy,destination_type,promoted_object,targeting,created_time')
CAMPOS_ANUNCIO = 'id,name,campaign_id,adset_id,status,effective_status,created_time,creative{id},tracking_specs'
CAMPOS_ANUNCIO_MIN = 'id,name,campaign_id,adset_id,status,effective_status,created_time,creative{id}'
CAMPOS_CRIATIVO = ('id,name,title,body,object_type,call_to_action_type,object_story_spec,asset_feed_spec,'
                   'effective_object_story_id,effective_instagram_media_id,instagram_permalink_url,image_hash,'
                   'image_url,thumbnail_url,video_id,url_tags,link_url,status')
CAMPOS_CRIATIVO_MIN = 'id,name,title,body,object_type,call_to_action_type,object_story_spec,asset_feed_spec,video_id,image_hash'
STATUS_TODOS = ['ACTIVE', 'PAUSED', 'ARCHIVED', 'IN_PROCESS', 'WITH_ISSUES', 'CAMPAIGN_PAUSED', 'ADSET_PAUSED',
                'PENDING_REVIEW', 'DISAPPROVED', 'PREAPPROVED', 'PENDING_BILLING_INFO', 'DELETED']
CAMPOS_RESULTADO = 'spend,impressions,clicks,inline_link_clicks,actions'
CAMPOS_VIDEO = (',video_play_actions,video_thruplay_watched_actions,video_p25_watched_actions,'
                'video_p50_watched_actions,video_p75_watched_actions,video_p100_watched_actions')
MESES_HISTORICO = 37


# ============================================================
# LEITURA (com tentativa de novo e campos de reserva)
# ============================================================

def _tentar(funcao, *args, tentativas=3, espera=6, **kw):
    for n in range(tentativas):
        try:
            return funcao(*args, **kw)
        except meta.ErroMeta as e:
            if n == tentativas - 1:
                raise
            print(f'   (Meta respondeu "{str(e)[:90]}"; tentando de novo em {espera}s)')
            time.sleep(espera)


def _lista(caminho, campos, campos_min=None, limite=100, extras=None):
    """Pagina uma aresta da conta. Se o Meta recusar algum campo, tenta com os campos minimos."""
    params = {'fields': campos, 'limit': limite, **(extras or {})}
    try:
        return _tentar(meta._paginar, caminho, params)
    except meta.ErroMeta as e:
        if not campos_min:
            raise
        print(f'   {caminho}: campos completos recusados ({str(e)[:80]}); usando os campos minimos')
        params['fields'] = campos_min
        params['limit'] = max(25, limite // 2)
        return _tentar(meta._paginar, caminho, params)


def _status(extras_status):
    return {'effective_status': json.dumps(extras_status)}


def ler_estrutura(conta):
    """Campanhas, conjuntos, anuncios e criativos de TODOS os status (inclusive arquivados)."""
    out = {}
    for nome, aresta, campos, minimos, limite in (
            ('campanhas', 'campaigns', CAMPOS_CAMPANHA, CAMPOS_CAMPANHA_MIN, 100),
            ('conjuntos', 'adsets', CAMPOS_CONJUNTO, CAMPOS_CONJUNTO_MIN, 100),
            ('anuncios', 'ads', CAMPOS_ANUNCIO, CAMPOS_ANUNCIO_MIN, 100)):
        print(f'   lendo {nome}...')
        try:
            out[nome] = _lista(f'{conta}/{aresta}', campos, minimos, limite, _status(STATUS_TODOS))
        except meta.ErroMeta:
            # algumas versoes nao aceitam DELETED no filtro: tenta sem ele
            out[nome] = _lista(f'{conta}/{aresta}', campos, minimos, limite, _status(STATUS_TODOS[:-1]))
        print(f'   {len(out[nome])} {nome}')
    print('   lendo criativos...')
    out['criativos'] = _lista(f'{conta}/adcreatives', CAMPOS_CRIATIVO, CAMPOS_CRIATIVO_MIN, 50)
    print(f"   {len(out['criativos'])} criativos")
    return out


def janelas_trimestrais(hoje=None):
    """Trimestres dos ultimos 37 meses (limite do Meta), do mais antigo ao atual."""
    hoje = hoje or date.today()
    meses = hoje.year * 12 + hoje.month - 1 - MESES_HISTORICO
    inicio = date(meses // 12, meses % 12 + 1, min(hoje.day, 28)) + timedelta(days=2)   # folga para nao bater no limite
    janelas, d = [], inicio
    while d <= hoje:
        ultimo_mes_tri = ((d.month - 1) // 3 + 1) * 3
        prox = date(d.year + 1, 1, 1) if ultimo_mes_tri == 12 else date(d.year, ultimo_mes_tri + 1, 1)
        fim = min(prox - timedelta(days=1), hoje)
        janelas.append((d.isoformat(), fim.isoformat()))
        d = fim + timedelta(days=1)
    return janelas


def _soma_acao(lista, tipo=None):
    return sum(float(a.get('value') or 0) for a in lista or [] if tipo is None or a.get('action_type') == tipo)


def ler_resultados(conta, nivel, chave):
    """Resultado somado por objeto (campanha/conjunto/anuncio) em janelas trimestrais."""
    campos = f'{chave},{CAMPOS_RESULTADO}' + (CAMPOS_VIDEO if nivel == 'ad' else '')
    acc = defaultdict(lambda: defaultdict(float))
    falhas = []
    for d, a in janelas_trimestrais():
        try:
            linhas = _tentar(meta.insights, conta, level=nivel, desde=d, ate=a, campos=campos)
        except meta.ErroMeta as e:
            falhas.append(f'{nivel} {d}..{a}: {e}')
            continue
        for r in linhas:
            x = acc[r[chave]]
            x['gasto'] += float(r.get('spend') or 0)
            x['impressoes'] += float(r.get('impressions') or 0)
            x['cliques'] += float(r.get('inline_link_clicks') or r.get('clicks') or 0)
            x['conversas'] += meta.conversas(r.get('actions'))
            x['formularios'] += meta.formularios(r.get('actions'))
            if nivel == 'ad':
                x['video_3s'] += _soma_acao(r.get('actions'), 'video_view')
                x['thruplay'] += _soma_acao(r.get('video_thruplay_watched_actions'))
                for p in ('25', '50', '75', '100'):
                    x[f'video_p{p}'] += _soma_acao(r.get(f'video_p{p}_watched_actions'))
    res = {}
    for k, x in acc.items():
        x = {kk: round(v, 2) for kk, v in x.items()}
        x['leads'] = int(x.get('conversas', 0) + x.get('formularios', 0))
        x['cpl'] = round(x['gasto'] / x['leads'], 2) if x['leads'] else None
        res[k] = x
    return res, falhas


def ler_publicos(conta):
    avisos = []
    try:
        custom = _lista(f'{conta}/customaudiences',
                        'id,name,subtype,description,approximate_count_lower_bound,approximate_count_upper_bound,'
                        'time_created,lookalike_spec,rule,delivery_status,data_source',
                        'id,name,subtype,approximate_count_lower_bound,approximate_count_upper_bound,time_created', 100)
    except meta.ErroMeta as e:
        custom, _ = [], avisos.append(f'públicos personalizados: {e}')
    try:
        salvos = _lista(f'{conta}/saved_audiences', 'id,name,targeting,time_created', 'id,name', 100)
    except meta.ErroMeta as e:
        salvos, _ = [], avisos.append(f'públicos salvos: {e}')
    return custom, salvos, avisos


def ler_midia(conta):
    avisos = []
    try:
        imagens = _lista(f'{conta}/adimages', 'hash,name,url,width,height,created_time,status', 'hash,name,url', 100)
    except meta.ErroMeta as e:
        imagens, _ = [], avisos.append(f'imagens: {e}')
    try:
        videos = _lista(f'{conta}/advideos', 'id,title,length,created_time,source,picture', 'id,title,length', 100)
    except meta.ErroMeta as e:
        videos, _ = [], avisos.append(f'vídeos: {e}')
    return imagens, videos, avisos


# ============================================================
# CRIATIVOS: o que tem dentro de cada um
# ============================================================

def _sem_acento(t):
    return unicodedata.normalize('NFKD', t or '').encode('ascii', 'ignore').decode().lower()


def slug(t, maximo=50):
    return re.sub(r'[^a-z0-9]+', '_', _sem_acento(t)).strip('_')[:maximo] or 'sem_nome'


def conteudo_criativo(c):
    """Resumo legivel de um criativo: formato, textos, titulos, botao, destino, formulario, midia."""
    c = c or {}
    oss = c.get('object_story_spec') or {}
    afs = c.get('asset_feed_spec') or {}
    ld, vd = oss.get('link_data') or {}, oss.get('video_data') or {}
    textos, titulos, cta, destino, form, videos, imagens = [], [], None, None, None, [], []
    formato = None
    if ld:
        formato = 'carrossel' if ld.get('child_attachments') else 'imagem'
        textos.append(ld.get('message'))
        titulos.append(ld.get('name'))
        cta_ = ld.get('call_to_action') or {}
        cta, destino = cta_.get('type'), ld.get('link')
        form = (cta_.get('value') or {}).get('lead_gen_form_id')
        if ld.get('image_hash'):
            imagens.append(ld['image_hash'])
        for ch in ld.get('child_attachments') or []:
            if ch.get('image_hash'):
                imagens.append(ch['image_hash'])
            if ch.get('video_id'):
                videos.append(ch['video_id'])
    if vd:
        formato = 'vídeo'
        textos.append(vd.get('message'))
        titulos.append(vd.get('title'))
        cta_ = vd.get('call_to_action') or {}
        v = cta_.get('value') or {}
        cta, destino, form = cta_.get('type'), v.get('link') or v.get('app_destination'), v.get('lead_gen_form_id')
        if vd.get('video_id'):
            videos.append(vd['video_id'])
    if afs:
        textos += [b.get('text') for b in afs.get('bodies', [])]
        titulos += [t.get('text') for t in afs.get('titles', [])]
        cta = cta or ', '.join(afs.get('call_to_action_types', []))
        videos += [v.get('video_id') for v in afs.get('videos', []) if v.get('video_id')]
        imagens += [i.get('hash') for i in afs.get('images', []) if i.get('hash')]
        destino = destino or ', '.join(u.get('website_url', '') for u in afs.get('link_urls', []) if u.get('website_url'))
        formato = ('vídeo' if afs.get('videos') else 'imagem') + ' com variações (dinâmico)'
    if c.get('video_id'):
        videos.append(c['video_id'])
    if c.get('image_hash'):
        imagens.append(c['image_hash'])
    if not textos and c.get('body'):
        textos.append(c['body'])
    if not titulos and c.get('title'):
        titulos.append(c['title'])
    if not formato:
        formato = 'post existente da Página/Instagram' if c.get('effective_object_story_id') else (c.get('object_type') or '?')
    uniq = lambda xs: [x for x in dict.fromkeys(x for x in xs if x)]  # noqa: E731
    return {'formato': formato, 'textos': uniq(textos), 'titulos': uniq(titulos), 'cta': cta or c.get('call_to_action_type'),
            'destino': destino, 'formulario': form, 'videos': uniq(videos), 'imagens': uniq(imagens),
            'post': c.get('effective_object_story_id'), 'instagram': c.get('instagram_permalink_url')}


def chave_criativo(cc):
    """Mesmo midia + mesmo texto = mesmo criativo (a agencia duplica o mesmo anuncio em varios conjuntos)."""
    base = '|'.join(cc['videos'] + cc['imagens']) or (cc['post'] or '')
    texto = _sem_acento((cc['textos'] or [''])[0])[:120]
    return f'{base}#{texto}'


# ============================================================
# PUBLICO: resumo legivel do targeting
# ============================================================

def resumo_publico(t, nomes_publicos=None):
    t = t or {}
    nomes_publicos = nomes_publicos or {}
    geo = t.get('geo_locations') or {}
    partes = []
    if geo.get('countries'):
        partes.append('país ' + ','.join(geo['countries']))
    if geo.get('regions'):
        partes.append('estados ' + ', '.join(r.get('name', r.get('key', '')) for r in geo['regions']))
    if geo.get('cities'):
        partes.append(f"{len(geo['cities'])} cidade(s): " + ', '.join(
            f"{c.get('name')}{' +' + str(c.get('radius')) + 'km' if c.get('radius') else ''}" for c in geo['cities'][:8])
            + (' …' if len(geo['cities']) > 8 else ''))
    if geo.get('custom_locations'):
        partes.append(f"{len(geo['custom_locations'])} ponto(s) no mapa")
    gen = {1: 'homens', 2: 'mulheres'}
    generos = ', '.join(gen.get(g, str(g)) for g in t.get('genders', [])) or 'todos'
    interesses = []
    for bloco in t.get('flexible_spec') or []:
        for tipo, lst in bloco.items():
            interesses += [x.get('name', '') for x in lst]
    incl = [nomes_publicos.get(a.get('id'), a.get('name', a.get('id'))) for a in t.get('custom_audiences') or []]
    excl = [nomes_publicos.get(a.get('id'), a.get('name', a.get('id'))) for a in t.get('excluded_custom_audiences') or []]
    adv = (t.get('targeting_automation') or {}).get('advantage_audience')
    posic = ', '.join(t.get('publisher_platforms') or []) or 'automático'
    return {'local': ' | '.join(partes) or '-', 'idade': f"{t.get('age_min', '-')}-{t.get('age_max', '-')}",
            'genero': generos, 'interesses': interesses, 'publicos_incluidos': incl, 'publicos_excluidos': excl,
            'advantage_publico': {1: 'ligado', 0: 'desligado'}.get(adv, '-'), 'posicionamentos': posic}


# ============================================================
# SAIDAS
# ============================================================

def reais(v):
    return 'R$ ' + f'{float(v or 0):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _linha_res(r):
    if not r or not r.get('gasto'):
        return 'sem entrega'
    cpl = reais(r['cpl']) if r.get('cpl') else 'sem lead'
    return (f"{reais(r['gasto'])} | {r['leads']} leads ({int(r.get('conversas', 0))} conversas, "
            f"{int(r.get('formularios', 0))} formulários) | CPL {cpl}")


def _orcamento(o):
    # a API devolve '0' no campo que nao se aplica (ex.: lifetime_budget de conjunto diario)
    dia, total = int(o.get('daily_budget') or 0), int(o.get('lifetime_budget') or 0)
    if dia:
        return reais(dia / 100) + '/dia'
    if total:
        return 'total ' + reais(total / 100)
    return '-'


def montar_saidas(pasta, dados):
    camps, cjs, ads = dados['campanhas'], dados['conjuntos'], dados['anuncios']
    res_c, res_s, res_a = dados['resultados']['campanha'], dados['resultados']['conjunto'], dados['resultados']['anuncio']
    criativos = {c['id']: c for c in dados['criativos']}
    nomes_publicos = {a['id']: a.get('name') for a in dados['publicos']}
    cjs_por_camp, ads_por_cj = defaultdict(list), defaultdict(list)
    for s in cjs:
        cjs_por_camp[s.get('campaign_id')].append(s)
    for a in ads:
        ads_por_cj[a.get('adset_id')].append(a)

    # --- criativos unicos (soma o resultado de todos os anuncios que usam o mesmo criativo)
    unicos = {}
    for a in ads:
        cid = (a.get('creative') or {}).get('id')
        cc = conteudo_criativo(criativos.get(cid))
        k = chave_criativo(cc)
        u = unicos.setdefault(k, {'chave': k, 'conteudo': cc, 'criativo_ids': set(), 'anuncios': [], 'campanhas': set(),
                                  'res': defaultdict(float)})
        u['criativo_ids'].add(cid)
        u['anuncios'].append(a.get('name'))
        camp = next((c for c in camps if c['id'] == a.get('campaign_id')), {})
        u['campanhas'].add(camp.get('name', a.get('campaign_id')))
        for kk, v in (res_a.get(a['id']) or {}).items():
            if isinstance(v, (int, float)) and kk != 'cpl':
                u['res'][kk] += v
        a['_criativo_chave'] = k
    lista_unicos = []
    for u in unicos.values():
        r = dict(u['res'])
        r['leads'] = int(r.get('leads', 0))
        r['cpl'] = round(r['gasto'] / r['leads'], 2) if r.get('leads') else None
        imp = r.get('impressoes') or 0
        r['gancho_3s_pct'] = round(r.get('video_3s', 0) / imp * 100, 1) if imp and r.get('video_3s') else None
        r['assistem_ate_fim_pct'] = round(r.get('video_p100', 0) / imp * 100, 1) if imp and r.get('video_3s') else None
        lista_unicos.append({**u, 'res': r, 'criativo_ids': sorted(i for i in u['criativo_ids'] if i),
                             'campanhas': sorted(u['campanhas'])})
    lista_unicos.sort(key=lambda u: -(u['res'].get('gasto') or 0))
    for i, u in enumerate(lista_unicos, 1):
        u['codigo'] = f'CR{i:03d}'
    codigo_de = {u['chave']: u['codigo'] for u in lista_unicos}

    # --- MAPA_COMPLETO.md
    total = {'gasto': sum((r.get('gasto') or 0) for r in res_c.values()), 'leads': sum(r.get('leads', 0) for r in res_c.values())}
    md = [f"# Mapa completo da conta {dados['conta'].get('name')} ({dados['conta_id']})", '',
          f"Backup de {dados['gerado_em']}. Somente leitura. Resultados dos últimos {MESES_HISTORICO} meses "
          f"(limite do Meta): {reais(total['gasto'])}, {total['leads']} leads.", '',
          f"{len(camps)} campanhas · {len(cjs)} conjuntos · {len(ads)} anúncios · {len(lista_unicos)} criativos únicos "
          f"(textos inteiros em CRIATIVOS.md) · {len(dados['publicos'])} públicos personalizados", '']
    if dados['avisos']:
        md += ['## Avisos do backup', ''] + [f'- {a}' for a in dados['avisos']] + ['']
    for c in sorted(camps, key=lambda c: c.get('created_time', ''), reverse=True):
        cats = ', '.join(c.get('special_ad_categories') or []) or 'nenhuma'
        md += [f"## {c.get('name')}", '',
               f"- **id** {c['id']} · **status** {c.get('effective_status')} · **criada** {(c.get('created_time') or '')[:10]} · "
               f"**objetivo** {c.get('objective')} · **orçamento** {_orcamento(c) if _orcamento(c) != '-' else 'nos conjuntos (ABO)'} · "
               f"**lance** {c.get('bid_strategy') or 'no conjunto'} · **categoria especial** {cats}",
               f"- **Resultado:** {_linha_res(res_c.get(c['id']))}", '']
        for s in sorted(cjs_por_camp.get(c['id'], []), key=lambda s: -((res_s.get(s['id']) or {}).get('gasto') or 0)):
            p = resumo_publico(s.get('targeting'), nomes_publicos)
            md += [f"### {s.get('name')} · {s.get('effective_status')}",
                   f"- {_orcamento(s)} · otimiza {s.get('optimization_goal')} · destino {s.get('destination_type') or '-'} · "
                   f"lance {s.get('bid_strategy') or '-'} · atribuição " +
                   (', '.join(f"{x.get('event_type')} {x.get('window_days')}d" for x in s.get('attribution_spec') or []) or '-'),
                   f"- **Público:** {p['local']} · {p['idade']} anos · {p['genero']} · Advantage+ {p['advantage_publico']} · "
                   f"posicionamentos {p['posicionamentos']}"]
            if p['interesses']:
                md.append('- **Interesses:** ' + ', '.join(p['interesses'][:25]) + (' …' if len(p['interesses']) > 25 else ''))
            if p['publicos_incluidos']:
                md.append('- **Públicos incluídos:** ' + ', '.join(map(str, p['publicos_incluidos'])))
            if p['publicos_excluidos']:
                md.append('- **Públicos excluídos:** ' + ', '.join(map(str, p['publicos_excluidos'])))
            md.append(f"- **Resultado:** {_linha_res(res_s.get(s['id']))}")
            for a in sorted(ads_por_cj.get(s['id'], []), key=lambda a: -((res_a.get(a['id']) or {}).get('gasto') or 0)):
                md.append(f"  - {a.get('name')} · {a.get('effective_status')} · criativo {codigo_de.get(a.get('_criativo_chave'), '?')} · "
                          f"{_linha_res(res_a.get(a['id']))}")
            md.append('')
    with open(os.path.join(pasta, 'MAPA_COMPLETO.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    # --- CRIATIVOS.md
    md = [f"# Criativos únicos da conta ({len(lista_unicos)})", '',
          'Ordenados por gasto. "Gancho 3s" = % das impressões que assistiram 3 segundos; "até o fim" = % que assistiu 100%.', '']
    for u in lista_unicos:
        cc, r = u['conteudo'], u['res']
        md += [f"## {u['codigo']} · {cc['formato']} · {_linha_res(r)}", '',
               f"- **Usado em:** {len(u['anuncios'])} anúncio(s), campanhas: " + '; '.join(u['campanhas'][:6]),
               f"- **Botão:** {cc['cta'] or '-'} · **destino:** {cc['destino'] or '-'} · **formulário:** {cc['formulario'] or '-'}",
               f"- **Mídia:** vídeos {', '.join(cc['videos']) or '-'} · imagens {', '.join(cc['imagens']) or '-'} · "
               f"post {cc['post'] or '-'} {cc['instagram'] or ''}"]
        if r.get('gancho_3s_pct') is not None:
            md.append(f"- **Vídeo:** gancho 3s {r['gancho_3s_pct']}% · até o fim {r['assistem_ate_fim_pct']}%")
        for t in cc['titulos'][:5]:
            md.append(f'- **Título:** {t}')
        for i, t in enumerate(cc['textos'][:5], 1):
            md += [f'- **Texto {i}:**', '', '> ' + t.replace('\n', '\n> '), '']
        md.append('')
    with open(os.path.join(pasta, 'CRIATIVOS.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    # --- CSVs (abre no Excel com ; e acentos)
    def gravar_csv(nome, linhas, colunas):
        with open(os.path.join(pasta, nome), 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=colunas, delimiter=';', extrasaction='ignore')
            w.writeheader()
            w.writerows(linhas)

    num = lambda v: '' if v is None else str(v).replace('.', ',')  # noqa: E731
    gravar_csv('campanhas.csv', [{
        'id': c['id'], 'nome': c.get('name'), 'status': c.get('effective_status'), 'criada': (c.get('created_time') or '')[:10],
        'objetivo': c.get('objective'), 'orcamento': _orcamento(c), 'gasto': num((res_c.get(c['id']) or {}).get('gasto')),
        'leads': (res_c.get(c['id']) or {}).get('leads', 0), 'cpl': num((res_c.get(c['id']) or {}).get('cpl'))} for c in camps],
        ['id', 'nome', 'status', 'criada', 'objetivo', 'orcamento', 'gasto', 'leads', 'cpl'])
    gravar_csv('conjuntos.csv', [dict(id=s['id'], campanha_id=s.get('campaign_id'), nome=s.get('name'),
                                      status=s.get('effective_status'), orcamento=_orcamento(s),
                                      otimiza=s.get('optimization_goal'), destino=s.get('destination_type'),
                                      **{k: (', '.join(map(str, v)) if isinstance(v, list) else v)
                                         for k, v in resumo_publico(s.get('targeting'), nomes_publicos).items()},
                                      gasto=num((res_s.get(s['id']) or {}).get('gasto')),
                                      leads=(res_s.get(s['id']) or {}).get('leads', 0),
                                      cpl=num((res_s.get(s['id']) or {}).get('cpl'))) for s in cjs],
               ['id', 'campanha_id', 'nome', 'status', 'orcamento', 'otimiza', 'destino', 'local', 'idade', 'genero',
                'interesses', 'publicos_incluidos', 'publicos_excluidos', 'advantage_publico', 'posicionamentos',
                'gasto', 'leads', 'cpl'])
    gravar_csv('anuncios.csv', [{
        'id': a['id'], 'campanha_id': a.get('campaign_id'), 'conjunto_id': a.get('adset_id'), 'nome': a.get('name'),
        'status': a.get('effective_status'), 'criativo': codigo_de.get(a.get('_criativo_chave')),
        'gasto': num((res_a.get(a['id']) or {}).get('gasto')), 'leads': (res_a.get(a['id']) or {}).get('leads', 0),
        'cpl': num((res_a.get(a['id']) or {}).get('cpl'))} for a in ads],
        ['id', 'campanha_id', 'conjunto_id', 'nome', 'status', 'criativo', 'gasto', 'leads', 'cpl'])
    return lista_unicos


def baixar_midia(pasta, imagens, videos, com_videos):
    feitos = {'imagens': 0, 'videos': 0, 'erros': []}
    p_img = os.path.join(pasta, 'midia', 'imagens')
    os.makedirs(p_img, exist_ok=True)
    for im in imagens:
        if not im.get('url'):
            continue
        ext = os.path.splitext(im.get('name') or '')[1].lower() or '.jpg'
        destino = os.path.join(p_img, f"{im['hash']}{ext if len(ext) <= 5 else '.jpg'}")
        if os.path.exists(destino):
            feitos['imagens'] += 1
            continue
        try:
            r = requests.get(im['url'], timeout=60)
            r.raise_for_status()
            with open(destino, 'wb') as f:
                f.write(r.content)
            feitos['imagens'] += 1
        except requests.RequestException as e:
            feitos['erros'].append(f"imagem {im.get('hash')}: {e}")
    if not com_videos:
        return feitos
    p_vid = os.path.join(pasta, 'midia', 'videos')
    os.makedirs(p_vid, exist_ok=True)
    for v in videos:
        titulo = _sem_acento(v.get('title'))
        if not v.get('source') or titulo.startswith('auto_cropped') or titulo.startswith('cropped_'):
            continue   # os recortes automaticos o proprio Meta refaz a partir do original
        destino = os.path.join(p_vid, f"{v['id']}_{slug(v.get('title'))}.mp4")
        if os.path.exists(destino):
            feitos['videos'] += 1
            continue
        try:
            with requests.get(v['source'], stream=True, timeout=180) as r:
                r.raise_for_status()
                with open(destino, 'wb') as f:
                    for bloco in r.iter_content(1 << 16):
                        f.write(bloco)
            feitos['videos'] += 1
        except requests.RequestException as e:
            feitos['erros'].append(f"vídeo {v.get('id')}: {e}")
    return feitos


def ultimo_backup():
    """Caminho do bruto.json mais recente (usado pelo meta_replicar.py)."""
    base = os.path.join(ambiente.SAIDA, 'meta_ads', 'backup')
    if not os.path.isdir(base):
        return None
    datas = sorted(d for d in os.listdir(base) if os.path.exists(os.path.join(base, d, 'bruto.json')))
    return os.path.join(base, datas[-1], 'bruto.json') if datas else None


# ============================================================
# COMANDO
# ============================================================

def executar(com_midia=True, com_videos=False, conta=None):
    if not meta.configurado():
        raise SystemExit('Meta Ads não configurado (META_ACCESS_TOKEN e META_AD_ACCOUNT_ID em config/.env): nada feito.')
    conta = conta or meta.conta_padrao()
    hoje = date.today().isoformat()
    pasta = ambiente.pasta_saida('meta_ads', 'backup', hoje)
    print(f'BACKUP DA CONTA {conta} -> {pasta}')
    dados = {'conta_id': conta, 'gerado_em': hoje, 'avisos': []}
    dados['conta'] = _tentar(meta._get, conta, {'fields': 'name,account_status,currency,timezone_name,created_time,amount_spent'})
    dados.update(ler_estrutura(conta))

    print('   lendo resultados (trimestre a trimestre, últimos 37 meses)...')
    dados['resultados'] = {}
    for rotulo, nivel, chave in (('campanha', 'campaign', 'campaign_id'), ('conjunto', 'adset', 'adset_id'), ('anuncio', 'ad', 'ad_id')):
        dados['resultados'][rotulo], falhas = ler_resultados(conta, nivel, chave)
        dados['avisos'] += [f'resultado não lido: {f}' for f in falhas]

    print('   lendo públicos e mídia...')
    dados['publicos'], dados['publicos_salvos'], av = ler_publicos(conta)
    dados['avisos'] += av
    imagens, videos, av = ler_midia(conta)
    dados['avisos'] += av
    dados['imagens'] = [{k: v for k, v in i.items() if k != 'url'} for i in imagens]          # url expira; o arquivo fica na pasta
    dados['videos'] = [{k: v for k, v in x.items() if k not in ('source', 'picture')} for x in videos]

    forms = sorted({conteudo_criativo(c)['formulario'] for c in dados['criativos']} - {None})
    dados['formularios_usados'] = forms
    if forms:
        dados['avisos'].append(f'{len(forms)} formulário(s) de lead usados ({", ".join(forms)}): as perguntas só abrem '
                               'com a tarefa "Leads" do usuário do sistema nas Páginas.')

    unicos = montar_saidas(pasta, dados)
    with open(os.path.join(pasta, 'bruto.json'), 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=1, default=str)

    if com_midia:
        print('   baixando mídia...')
        feitos = baixar_midia(pasta, imagens, videos, com_videos)
        print(f"   {feitos['imagens']} imagens" + (f", {feitos['videos']} vídeos" if com_videos else ' (vídeos: use --videos)'))
        for e in feitos['erros'][:10]:
            print('   erro:', e)

    print(f"\nPRONTO: {len(dados['campanhas'])} campanhas, {len(dados['conjuntos'])} conjuntos, {len(dados['anuncios'])} anúncios, "
          f"{len(unicos)} criativos únicos, {len(dados['publicos'])} públicos.")
    for a in dados['avisos']:
        print('   aviso:', a)
    print(f'   {os.path.join(pasta, "MAPA_COMPLETO.md")}\n   {os.path.join(pasta, "CRIATIVOS.md")}')
    return pasta


def main(argv=None):
    ap = argparse.ArgumentParser(prog='backup', description='Backup e mapa completo da conta de anúncios (só leitura)')
    ap.add_argument('comando', nargs='?', default='backup')
    ap.add_argument('--videos', action='store_true', help='baixa também os vídeos originais da biblioteca')
    ap.add_argument('--sem-midia', action='store_true', help='não baixa imagens nem vídeos')
    ap.add_argument('--conta', help='act_... (padrão: META_AD_ACCOUNT_ID)')
    a = ap.parse_args(argv)
    executar(com_midia=not a.sem_midia, com_videos=a.videos, conta=a.conta)
    return 0


if __name__ == '__main__':
    sys.exit(main())
