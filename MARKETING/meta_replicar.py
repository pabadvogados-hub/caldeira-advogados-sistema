"""
REPLICAR CAMPANHA DO META A PARTIR DO BACKUP (com revisao por IA opcional). Tudo nasce PAUSADO.

Fonte: o backup mais recente (MARKETING/main.py backup). A replica e montada a partir do que a campanha
original tinha de verdade: objetivo, conjuntos (publico, orcamento, otimizacao, destino), criativos
(texto, titulo, botao, video/imagem, formulario) e anuncios.

Uso:
    python MARKETING/main.py replicar --listar [--frente agro|prev]     ranking das campanhas para escolher
    python MARKETING/main.py replicar --campanha <id ou parte do nome>   PLANO (simulacao: nada enviado)
        --conta act_...            conta de destino (padrao: a da original). So contas do config/.env
        --orcamento-diario 50      reais por conjunto (padrao: o da original)
        --regiao "Rondonia,Acre"   troca a regiao de todos os conjuntos (estados do Brasil)
        --genero todos|homens|mulheres
        --todos                    leva tambem conjuntos/anuncios sem resultado (padrao: so os com lead ou ativos)
        --ia                       a IA revisa a estrutura (quais conjuntos/anuncios manter, regiao, genero, idade)
                                   e reescreve os textos dentro do Provimento 205/2021
        --aplicar                  cria de verdade (ver travas abaixo)

Travas do --aplicar (mesmas do MARKETING/meta_acoes.py):
  1. token de escrita META_ACCESS_TOKEN_ACOES (o token de leitura nao escreve);
  2. pessoa no terminal digitando SIM (nao roda pelo agendador);
  3. conta de destino tem de estar no config/.env (META_AD_ACCOUNT_ID ou META_AD_ACCOUNTS_RESERVA);
  4. campanha, conjuntos e anuncios nascem PAUSED e sao conferidos logo depois; nada e ativado por aqui;
  5. texto com alerta BLOQUEIA da conformidade (Provimento 205) nao vira anuncio;
  6. se der erro no meio, para e lista o que ja foi criado (tudo pausado). Nada e apagado.
Tudo vai para SAIDA/marketing/replicacoes_log.json.

Pegadinhas da API (v26.0):
  - campanha sem orcamento proprio (ABO) exige is_adset_budget_sharing_enabled;
  - publico personalizado e da conta: replicar em OUTRA conta exige compartilhar o publico antes (o plano avisa);
  - orcamento vai em centavos; objetos aninhados (targeting, object_story_spec...) vao como JSON.
"""
import argparse
import copy
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
import ambiente  # noqa: E402  (carrega .env e caminhos)

import meta_backup  # noqa: E402

PREFIXO = '[IA] '
MODELO_IA = os.getenv('MODELO_MARKETING') or os.getenv('MODELO_SDR') or 'claude-sonnet-5'

TEMAS = {   # palavras curtas com \b: "gado" esta dentro de "advogado", "terra" dentro de "enterra"
    'agro': r'produtor|\brural|\bsafra|fazenda|\bgado\b|pecuar|\bagro|credito rural|prorroga|leilao|\bbanco\b|\bdivida|cedula|\bterra\b',
    'maternidade': r'materni|gravid|gestante|mae\b|maes\b|filho de ate|bebe|nasceu',
    'acidente': r'acidente|sequela|pino|placa|caiu de moto|auxilio.acidente',
    'bpc_autismo': r'autis|tdah|tod\b|caps|deficien|medicac',
    'bpc_idoso': r'idoso|65 anos|sessenta e cinco',
    'incapacidade': r'incapacidade|pericia|indeferid|negou|negado',
}
UF_NOMES = {'RO': 'Rondônia', 'AC': 'Acre', 'AM': 'Amazonas', 'MT': 'Mato Grosso', 'MS': 'Mato Grosso do Sul',
            'PA': 'Pará', 'TO': 'Tocantins', 'GO': 'Goiás', 'RR': 'Roraima', 'AP': 'Amapá', 'MA': 'Maranhão',
            'PR': 'Paraná', 'SC': 'Santa Catarina', 'RS': 'Rio Grande do Sul', 'MG': 'Minas Gerais', 'SP': 'São Paulo',
            'BA': 'Bahia', 'DF': 'Distrito Federal'}


def sem_acento(t):
    return unicodedata.normalize('NFKD', t or '').encode('ascii', 'ignore').decode().lower()


def temas_do_texto(texto):
    t = sem_acento(texto)
    return {nome for nome, pad in TEMAS.items() if re.search(pad, t)}


def frente(nome):
    t = sem_acento(nome)
    if re.search(r'vaga', t):
        return 'recrutamento'
    if re.search(TEMAS['agro'] + r'|regulariza|dbtn\] form 3[01]03|crescimento de perfil', t):
        return 'agro'
    if re.search(r'bpc|materni|indeferid|prev|loas|inss|auxilio', t):
        return 'prev'
    return 'outros'


# ============================================================
# BACKUP
# ============================================================

def carregar_backup(caminho=None):
    caminho = caminho or meta_backup.ultimo_backup()
    if not caminho or not os.path.exists(caminho):
        raise SystemExit('Nenhum backup encontrado. Rode antes: python MARKETING/main.py backup')
    with open(caminho, encoding='utf-8') as f:
        dados = json.load(f)
    dados['_caminho'] = caminho
    return dados


def listar(dados, so_frente=None, minimo=100):
    res = dados['resultados']['campanha']
    linhas = []
    for c in dados['campanhas']:
        r = res.get(c['id']) or {}
        if (r.get('gasto') or 0) < minimo:
            continue
        fr = frente(c.get('name'))
        if so_frente and fr != so_frente:
            continue
        linhas.append((r.get('cpl') or 9e9, fr, c, r))
    linhas.sort(key=lambda x: x[0])
    print(f"\nCAMPANHAS DO BACKUP ({dados['gerado_em']}) com gasto acima de R$ {minimo}, da mais barata por lead para a mais cara:\n")
    for cpl, fr, c, r in linhas:
        print(f"  {c['id']} | {fr:6} | {c.get('effective_status', '')[:8]:8} | {meta_backup.reais(r.get('gasto'))} | "
              f"{r.get('leads', 0)} leads | CPL {meta_backup.reais(cpl) if cpl < 9e9 else 'sem lead'} | {c.get('name')}")
    print('\nPara montar o plano: replicar --campanha <id>')
    return linhas


def achar_campanha(dados, busca):
    b = sem_acento(busca)
    exatas = [c for c in dados['campanhas'] if c['id'] == busca]
    if exatas:
        return exatas[0]
    achadas = [c for c in dados['campanhas'] if b in sem_acento(c.get('name'))]
    if not achadas:
        raise SystemExit(f'Nenhuma campanha com "{busca}" no backup. Use --listar.')
    if len(achadas) > 1:
        print('Mais de uma campanha bate com a busca; use o id:')
        for c in achadas[:15]:
            print(f"  {c['id']} | {c.get('name')}")
        raise SystemExit(1)
    return achadas[0]


# ============================================================
# PLANO (pura montagem, sem rede)
# ============================================================

def _valor(v):
    """Orcamento da API vem como texto e '0' quando nao se aplica (ex.: lifetime_budget de conjunto diario)."""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _limpar_targeting(t):
    t = copy.deepcopy(t or {})
    for chave in ('targeting_optimization', 'targeting_relaxation_types', 'brand_safety_content_filter_levels'):
        t.pop(chave, None)
    auto = t.setdefault('targeting_automation', {})
    auto['advantage_audience'] = int(bool(auto.get('advantage_audience')))   # v26: tem de vir explicito
    return t


def avisos_conjunto(s):
    """Problemas que o mapa mostrou: nome x regiao, genero, publico de outra conta etc."""
    avisos = []
    t = s.get('targeting') or {}
    geo = t.get('geo_locations') or {}
    nome = s.get('name') or ''
    ufs_nome = [uf for uf in UF_NOMES if re.search(rf'(?<![A-Z]){uf}(?![A-Z])', nome)] + \
               [uf for uf, n in UF_NOMES.items() if sem_acento(n).replace(' ', '') in sem_acento(nome).replace(' ', '')]
    if ufs_nome and geo.get('countries') and not geo.get('regions') and not geo.get('cities'):
        avisos.append(f"o nome cita {', '.join(sorted(set(ufs_nome)))}, mas o público é o Brasil inteiro")
    generos = t.get('genders') or []
    if len(generos) == 1 and generos[0] == 2 and not re.search(r'materni|gravid|mae|sm\b|\[sm\]', sem_acento(nome)):
        avisos.append('só mulheres num conjunto que não é de salário-maternidade')
    if len(generos) == 1 and generos[0] == 1:
        avisos.append('só homens')
    if t.get('custom_audiences'):
        avisos.append(f"usa {len(t['custom_audiences'])} público(s) personalizado(s) da conta de origem")
    return avisos


def avisos_criativo(cc):
    avisos = []
    temas = [temas_do_texto(x) for x in cc['textos']]
    todos = set().union(*temas) if temas else set()
    todos.discard('incapacidade')
    if len(todos - {'agro'}) > 1 or (todos & {'agro'} and len(todos) > 1):
        avisos.append('textos de temas diferentes no mesmo anúncio: ' + ', '.join(sorted(todos)))
    if any('link na bio' in sem_acento(x) for x in cc['textos']) and (cc['cta'] or '').startswith('WHATSAPP'):
        avisos.append('texto fala em "link na bio" num anúncio de WhatsApp')
    return avisos


def conformidade_textos(textos):
    try:
        import conformidade
    except ImportError:
        return []
    alertas = []
    for i, t in enumerate(textos, 1):
        for a in conformidade.verificar(t, f'texto {i}'):
            alertas.append(a)
    return alertas


def montar_plano(dados, campanha, todos=False, conta=None, orcamento_diario=None, genero=None):
    conta = conta or dados['conta_id']
    res_s, res_a = dados['resultados']['conjunto'], dados['resultados']['anuncio']
    criativos = {c['id']: c for c in dados['criativos']}
    publicos = {p['id'] for p in dados.get('publicos', [])}
    conjuntos = [s for s in dados['conjuntos'] if s.get('campaign_id') == campanha['id']]
    anuncios = [a for a in dados['anuncios'] if a.get('campaign_id') == campanha['id']]

    def vale(obj, res):
        return todos or (res.get(obj['id']) or {}).get('leads') or obj.get('effective_status') == 'ACTIVE'

    plano = {'gerado_em': datetime.now().isoformat(timespec='seconds'), 'backup': dados['_caminho'],
             'origem': {'id': campanha['id'], 'nome': campanha.get('name'), 'conta': dados['conta_id'],
                        'resultado': dados['resultados']['campanha'].get(campanha['id'])},
             'conta_destino': conta, 'avisos': [], 'conjuntos': []}
    if conta != dados['conta_id']:
        plano['avisos'].append(f'destino ({conta}) é outra conta: públicos personalizados, pixel e formulários precisam '
                               'existir/estar compartilhados lá; conferir forma de pagamento da conta')
    camp = {'name': PREFIXO + (campanha.get('name') or ''), 'objective': campanha.get('objective'),
            'buying_type': campanha.get('buying_type') or 'AUCTION', 'status': 'PAUSED',
            'special_ad_categories': campanha.get('special_ad_categories') or []}
    c_dia, c_total = _valor(campanha.get('daily_budget')), _valor(campanha.get('lifetime_budget'))
    if c_dia or c_total:   # orcamento na campanha (CBO)
        if orcamento_diario:
            camp['daily_budget'] = int(orcamento_diario * 100)
        else:
            camp['daily_budget' if c_dia else 'lifetime_budget'] = c_dia or c_total
        if campanha.get('bid_strategy'):
            camp['bid_strategy'] = campanha['bid_strategy']
    else:
        camp['is_adset_budget_sharing_enabled'] = False
    plano['campanha'] = camp

    vistos_por_conjunto = defaultdict(set)
    for s in sorted(conjuntos, key=lambda s: -((res_s.get(s['id']) or {}).get('gasto') or 0)):
        if not vale(s, res_s):
            continue
        t = _limpar_targeting(s.get('targeting'))
        if genero:
            t.pop('genders', None) if genero == 'todos' else t.__setitem__('genders', [1] if genero == 'homens' else [2])
        if conta != dados['conta_id'] and t.get('custom_audiences'):
            t['custom_audiences'] = [a for a in t['custom_audiences'] if a.get('id') in publicos]
        s_dia, s_total = _valor(s.get('daily_budget')), _valor(s.get('lifetime_budget'))
        sem_orc_campanha = 'is_adset_budget_sharing_enabled' in camp
        cj = {'origem_id': s['id'], 'origem_nome': s.get('name'), 'resultado': res_s.get(s['id']),
              'avisos': avisos_conjunto(s),
              'payload': {k: v for k, v in {
                  'name': PREFIXO + (s.get('name') or ''), 'status': 'PAUSED',
                  'daily_budget': (int(orcamento_diario * 100) if orcamento_diario else s_dia) or None
                  if sem_orc_campanha and (s_dia or orcamento_diario or not s_total) else None,
                  'lifetime_budget': s_total or None if sem_orc_campanha and s_total and not orcamento_diario else None,
                  'billing_event': s.get('billing_event'), 'optimization_goal': s.get('optimization_goal'),
                  'bid_strategy': s.get('bid_strategy'), 'bid_amount': s.get('bid_amount'),
                  'destination_type': s.get('destination_type'), 'promoted_object': s.get('promoted_object'),
                  'attribution_spec': s.get('attribution_spec'), 'targeting': t,
                  'end_time': s.get('end_time') if s_total and not orcamento_diario else None,
              }.items() if v not in (None, '', [])},
              'anuncios': []}
        for a in sorted([a for a in anuncios if a.get('adset_id') == s['id']],
                        key=lambda a: -((res_a.get(a['id']) or {}).get('gasto') or 0)):
            if not vale(a, res_a):
                continue
            cr = criativos.get((a.get('creative') or {}).get('id')) or {}
            cc = meta_backup.conteudo_criativo(cr)
            chave = meta_backup.chave_criativo(cc)
            if chave in vistos_por_conjunto[s['id']]:
                continue   # mesmo criativo repetido no mesmo conjunto
            vistos_por_conjunto[s['id']].add(chave)
            spec = {k: copy.deepcopy(cr[k]) for k in ('object_story_spec', 'asset_feed_spec') if cr.get(k)}
            if not spec and cr.get('effective_object_story_id'):
                spec = {'object_story_id': cr['effective_object_story_id']}
            if not spec:
                cj['avisos'].append(f"anúncio {a.get('name')}: criativo sem especificação no backup; fica de fora")
                continue
            cj['anuncios'].append({
                'origem_id': a['id'], 'origem_nome': a.get('name'), 'resultado': res_a.get(a['id']), 'conteudo': cc,
                'avisos': avisos_criativo(cc), 'conformidade': conformidade_textos(cc['textos'] + cc['titulos']),
                'criativo': {'name': PREFIXO + (cr.get('name') or a.get('name') or ''), **spec},
                'anuncio': {'name': PREFIXO + (a.get('name') or ''), 'status': 'PAUSED'}})
        if cj['anuncios']:
            plano['conjuntos'].append(cj)
    return plano


def trocar_regiao(plano, nomes_estados):
    """Resolve nomes de estados na API de busca do Meta (leitura) e troca a regiao de todos os conjuntos."""
    import meta_ads_integration as meta
    regioes = []
    for nome in [n.strip() for n in nomes_estados if n.strip()]:
        nome = UF_NOMES.get(nome.upper(), nome)
        r = meta._get('search', {'type': 'adgeolocation', 'location_types': json.dumps(['region']), 'q': nome,
                                 'country_code': 'BR', 'limit': 5})
        achado = next((x for x in r.get('data', []) if sem_acento(x.get('name')) == sem_acento(nome)), None)
        if not achado:
            raise SystemExit(f'Estado não encontrado na busca do Meta: {nome}')
        regioes.append({'key': achado['key'], 'name': achado['name'], 'country': 'BR'})
    for cj in plano['conjuntos']:
        geo = cj['payload']['targeting'].setdefault('geo_locations', {})
        antes = meta_backup.resumo_publico(cj['payload']['targeting'])['local']
        for k in ('countries', 'cities', 'custom_locations', 'zips'):
            geo.pop(k, None)
        geo['regions'] = regioes
        cj.setdefault('mudancas', []).append(f"região: {antes} -> {', '.join(r['name'] for r in regioes)}")
    return regioes


# ============================================================
# IA: revisao da estrutura + textos novos
# ============================================================

SCHEMA_IA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['diagnostico', 'conjuntos', 'anuncios', 'ganchos_novos'],
    'properties': {
        'diagnostico': {'type': 'string'},
        'conjuntos': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['origem_id', 'manter', 'motivo', 'estados', 'genero', 'idade_min', 'idade_max'],
            'properties': {'origem_id': {'type': 'string'}, 'manter': {'type': 'boolean'}, 'motivo': {'type': 'string'},
                           'estados': {'type': 'array', 'items': {'type': 'string'}},
                           'genero': {'type': 'string', 'enum': ['manter', 'todos', 'homens', 'mulheres']},
                           'idade_min': {'type': 'integer'}, 'idade_max': {'type': 'integer'}}}},
        'anuncios': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['origem_id', 'manter', 'motivo', 'textos', 'titulo'],
            'properties': {'origem_id': {'type': 'string'}, 'manter': {'type': 'boolean'}, 'motivo': {'type': 'string'},
                           'textos': {'type': 'array', 'items': {'type': 'string'}}, 'titulo': {'type': 'string'}}}},
        'ganchos_novos': {'type': 'array', 'items': {'type': 'string'}},
    },
}

SISTEMA_IA = """Voce e o gestor de trafego do escritorio Caldeira Advogados Associados (Cacoal/RO), que defende produtor
rural contra bancos (prorrogacao de divida rural pelo Manual de Credito Rural, impenhorabilidade da pequena propriedade,
revisao de contratos) e atende previdenciario (BPC/LOAS, salario-maternidade, auxilio-acidente, beneficio negado).
Voce recebe uma campanha real do Meta Ads (estrutura, publico, textos e resultado de cada parte) e devolve a revisao
para a REPLICA dessa campanha.

Regras obrigatorias dos textos (Provimento 205/2021 da OAB e Codigo de Etica):
- nada de promessa ou garantia de resultado, prazo ou valor ("vai conseguir", "4 anos sem pagar", "6 mil no bolso");
- nada de caso concreto de cliente como prova ("derrubamos o leilao da cliente");
- nada de comparacao com outros advogados/escritorios, nem de preco, gratuidade ou desconto;
- nada de sensacionalismo ou urgencia de pressao; tom informativo, sobrio, linguagem simples de quem vive no campo;
- pode explicar o direito em tese ("a lei preve que...", "pode ser possivel... dependendo do caso") e convidar a
  conversar com a equipe;
- os primeiros 3 segundos/primeira linha decidem: comece pela dor do publico, na fala dele.
Estrutura: mantenha so o que trouxe lead a custo razoavel; aponte conjunto com regiao incoerente com o nome ou com o
escritorio (atende principalmente RO e vizinhos, mas previdenciario pode ser nacional), genero restrito sem motivo,
textos de temas misturados no mesmo anuncio. Use os nomes dos estados por extenso. genero='manter' se nao mudar;
idade_min/idade_max = os atuais se nao mudar. textos: 1 a 3 versoes, cada uma com no maximo 600 caracteres.
Responda so com o JSON pedido."""


def revisar_com_ia(plano, melhores):
    import ia
    if not ambiente.tem_credencial('ANTHROPIC_API_KEY'):
        raise SystemExit('--ia precisa de ANTHROPIC_API_KEY no config/.env (o resto do plano funciona sem IA).')
    resumo = {'campanha': plano['origem'], 'conjuntos': []}
    for cj in plano['conjuntos']:
        p = meta_backup.resumo_publico(cj['payload']['targeting'])
        resumo['conjuntos'].append({
            'origem_id': cj['origem_id'], 'nome': cj['origem_nome'], 'resultado': cj['resultado'], 'publico': p,
            'avisos': cj['avisos'], 'otimiza': cj['payload'].get('optimization_goal'),
            'destino': cj['payload'].get('destination_type'),
            'anuncios': [{'origem_id': a['origem_id'], 'nome': a['origem_nome'], 'resultado': a['resultado'],
                          'formato': a['conteudo']['formato'], 'textos': a['conteudo']['textos'][:5],
                          'titulos': a['conteudo']['titulos'][:3], 'avisos': a['avisos'],
                          'conformidade': [f"{x['gravidade']}: {x['trecho']} ({x['regra'][:60]})" for x in a['conformidade']]}
                         for a in cj['anuncios']]})
    conteudo = ('CAMPANHA A REPLICAR:\n' + json.dumps(resumo, ensure_ascii=False, default=str) +
                '\n\nMELHORES ANUNCIOS DA CONTA NA MESMA FRENTE (referencia de gancho, nao copiar promessas):\n' +
                json.dumps(melhores, ensure_ascii=False, default=str))
    print(f'   consultando a IA ({MODELO_IA})...')
    return ia.json_por_schema(MODELO_IA, SISTEMA_IA, conteudo, SCHEMA_IA, max_tokens=12000)


def melhores_da_frente(dados, fr, n=8):
    criativos = {c['id']: c for c in dados['criativos']}
    camp_nome = {c['id']: c.get('name') for c in dados['campanhas']}
    linhas = []
    for a in dados['anuncios']:
        r = dados['resultados']['anuncio'].get(a['id']) or {}
        if (r.get('leads') or 0) < 20 or frente(camp_nome.get(a.get('campaign_id'))) != fr:
            continue
        cc = meta_backup.conteudo_criativo(criativos.get((a.get('creative') or {}).get('id')))
        linhas.append({'anuncio': a.get('name'), 'cpl': r.get('cpl'), 'leads': r.get('leads'),
                       'texto': (cc['textos'] or [''])[0][:500]})
    vistos, saida = set(), []
    for x in sorted(linhas, key=lambda x: x['cpl'] or 9e9):
        if x['texto'][:80] in vistos:
            continue
        vistos.add(x['texto'][:80])
        saida.append(x)
    return saida[:n]


def aplicar_revisao(plano, rev):
    """Aplica a revisao da IA no plano (ainda sem rede), registrando cada mudanca."""
    plano['ia'] = {'modelo': MODELO_IA, 'diagnostico': rev['diagnostico'], 'ganchos_novos': rev['ganchos_novos']}
    por_cj = {c['origem_id']: c for c in rev['conjuntos']}
    por_ad = {a['origem_id']: a for a in rev['anuncios']}
    estados_pedidos = set()
    for cj in list(plano['conjuntos']):
        r = por_cj.get(cj['origem_id'])
        if r and not r['manter']:
            plano['conjuntos'].remove(cj)
            plano.setdefault('removidos_pela_ia', []).append(f"conjunto {cj['origem_nome']}: {r['motivo']}")
            continue
        if r:
            t = cj['payload']['targeting']
            mud = cj.setdefault('mudancas', [])
            if r['genero'] != 'manter':
                antes = t.get('genders')
                t.pop('genders', None) if r['genero'] == 'todos' else t.__setitem__('genders', [1] if r['genero'] == 'homens' else [2])
                mud.append(f"gênero: {antes or 'todos'} -> {r['genero']} ({r['motivo']})")
            if (r['idade_min'], r['idade_max']) != (t.get('age_min'), t.get('age_max')) and 13 <= r['idade_min'] <= r['idade_max'] <= 65:
                mud.append(f"idade: {t.get('age_min')}-{t.get('age_max')} -> {r['idade_min']}-{r['idade_max']}")
                t['age_min'], t['age_max'] = r['idade_min'], r['idade_max']
            if r['estados']:
                estados_pedidos.add(tuple(r['estados']))
                cj['estados_ia'] = r['estados']
        for ad in list(cj['anuncios']):
            ra = por_ad.get(ad['origem_id'])
            if not ra:
                continue
            if not ra['manter']:
                cj['anuncios'].remove(ad)
                plano.setdefault('removidos_pela_ia', []).append(f"anúncio {ad['origem_nome']}: {ra['motivo']}")
                continue
            if ra['textos']:
                ad['textos_ia'] = ra['textos']
                ad['titulo_ia'] = ra['titulo']
                ad['conformidade_ia'] = conformidade_textos(ra['textos'] + [ra['titulo']])
                trocar_textos(ad['criativo'], ra['textos'], ra['titulo'])
    return estados_pedidos


def trocar_textos(criativo, textos, titulo):
    """Troca texto e titulo no criativo (video_data/link_data ou variacoes do asset_feed_spec)."""
    oss = criativo.get('object_story_spec') or {}
    for parte in ('video_data', 'link_data'):
        if oss.get(parte):
            oss[parte]['message'] = textos[0]
            if titulo:
                oss[parte]['title' if parte == 'video_data' else 'name'] = titulo
    afs = criativo.get('asset_feed_spec')
    if afs:
        afs['bodies'] = [{'text': t} for t in textos]
        if titulo:
            afs['titles'] = [{'text': titulo}]
    if 'object_story_id' in criativo:
        criativo['_aviso'] = 'criativo é um post existente: o texto do post não muda (a IA só sugere)'


# ============================================================
# TELA / ARQUIVOS
# ============================================================

def texto_plano(plano):
    L = [f"REPLICA DE: {plano['origem']['nome']} ({plano['origem']['id']})",
         f"resultado da original: {meta_backup._linha_res(plano['origem']['resultado'])}",
         f"conta de destino: {plano['conta_destino']}", '',
         f"CAMPANHA: {plano['campanha']['name']} | {plano['campanha']['objective']} | PAUSADA | " +
         ('orçamento nos conjuntos' if plano['campanha'].get('is_adset_budget_sharing_enabled') is False
          else meta_backup._orcamento(plano['campanha']))]
    if plano.get('ia'):
        L += ['', 'DIAGNÓSTICO DA IA: ' + plano['ia']['diagnostico']]
        if plano['ia'].get('ganchos_novos'):
            L += ['GANCHOS NOVOS SUGERIDOS:'] + [f'  - {g}' for g in plano['ia']['ganchos_novos']]
    for a in plano['avisos']:
        L.append(f'AVISO: {a}')
    for cj in plano['conjuntos']:
        p = meta_backup.resumo_publico(cj['payload']['targeting'])
        L += ['', f"  CONJUNTO: {cj['payload']['name']} | {meta_backup._orcamento(cj['payload'])} | "
                  f"{cj['payload'].get('optimization_goal')} | destino {cj['payload'].get('destination_type', '-')}",
              f"     público: {p['local']} · {p['idade']} · {p['genero']} · Advantage+ {p['advantage_publico']}"
              + (f" · {len(p['publicos_incluidos'])} público(s)" if p['publicos_incluidos'] else '')
              + (f" · interesses: {', '.join(p['interesses'][:6])}" if p['interesses'] else ''),
              f"     original: {meta_backup._linha_res(cj['resultado'])}"]
        L += [f'     AVISO: {x}' for x in cj['avisos']]
        L += [f'     MUDANÇA: {x}' for x in cj.get('mudancas', [])]
        for ad in cj['anuncios']:
            L.append(f"     - ANÚNCIO {ad['anuncio']['name']} | {ad['conteudo']['formato']} | botão {ad['conteudo']['cta']} | "
                     f"original: {meta_backup._linha_res(ad['resultado'])}")
            L += [f'         AVISO: {x}' for x in ad['avisos']]
            graves = [x for x in (ad.get('conformidade_ia') if 'textos_ia' in ad else ad['conformidade']) if x['gravidade'] == 'BLOQUEIA']
            if graves:
                L.append('         BLOQUEIA (Provimento 205): ' + '; '.join(f"\"{x['trecho']}\"" for x in graves[:4]) +
                         ' -> esse anúncio NÃO é criado até o texto ser corrigido (use --ia)')
            if ad.get('textos_ia'):
                L.append('         TEXTO NOVO (IA): ' + ad['textos_ia'][0].replace('\n', ' ')[:300])
    for r in plano.get('removidos_pela_ia', []):
        L.append(f'  REMOVIDO PELA IA: {r}')
    return '\n'.join(L)


def salvar_plano(plano):
    pasta = ambiente.pasta_saida('marketing', 'replicacoes')
    base = os.path.join(pasta, f"{datetime.now():%Y-%m-%d_%H%M}_{meta_backup.slug(plano['origem']['nome'], 40)}")
    with open(base + '.json', 'w', encoding='utf-8') as f:
        json.dump(plano, f, ensure_ascii=False, indent=1, default=str)
    with open(base + '.txt', 'w', encoding='utf-8') as f:
        f.write(texto_plano(plano))
    return base


# ============================================================
# CRIACAO NA CONTA (so com --aplicar)
# ============================================================

def contas_permitidas():
    contas = {os.getenv('META_AD_ACCOUNT_ID', '')}
    contas |= set((os.getenv('META_AD_ACCOUNTS_RESERVA') or '').split(','))
    return {c.strip() if c.strip().startswith('act_') else f'act_{c.strip()}' for c in contas if c.strip()}


def _form(params):
    """Graph API recebe objetos aninhados como JSON."""
    return {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in params.items()}


def _registrar(evento):
    caminho = os.path.join(ambiente.pasta_saida('marketing'), 'replicacoes_log.json')
    log = []
    if os.path.exists(caminho):
        with open(caminho, encoding='utf-8') as f:
            log = json.load(f)
    log.append({'quando': datetime.now().isoformat(timespec='seconds'), **evento})
    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1, default=str)


def criar(plano, entrada=input):
    import meta_acoes as acoes
    conta = plano['conta_destino']
    if conta not in contas_permitidas():
        raise SystemExit(f'--aplicar recusado: {conta} não está no config/.env (META_AD_ACCOUNT_ID / META_AD_ACCOUNTS_RESERVA).')
    token = acoes.token_acoes()
    if not token:
        raise SystemExit('--aplicar recusado: META_ACCESS_TOKEN_ACOES não configurado. Nada foi criado.')
    if not acoes.terminal_interativo():
        raise SystemExit('--aplicar recusado: precisa de uma pessoa no terminal. Nada foi criado.')
    bloqueados = []
    for cj in plano['conjuntos']:
        for ad in list(cj['anuncios']):
            alertas = ad.get('conformidade_ia') if 'textos_ia' in ad else ad['conformidade']
            if any(x['gravidade'] == 'BLOQUEIA' for x in alertas or []):
                bloqueados.append(ad['origem_nome'])
                cj['anuncios'].remove(ad)
    plano['conjuntos'] = [cj for cj in plano['conjuntos'] if cj['anuncios']]
    if bloqueados:
        print(f"\n{len(bloqueados)} anúncio(s) ficam de fora por alerta BLOQUEIA do Provimento 205: {', '.join(bloqueados)}")
    if not plano['conjuntos']:
        raise SystemExit('Nada para criar (todos os anúncios bloqueados). Rode com --ia para reescrever os textos.')
    n_ad = sum(len(cj['anuncios']) for cj in plano['conjuntos'])
    print(f"\nVAI CRIAR em {conta}: 1 campanha, {len(plano['conjuntos'])} conjunto(s), {n_ad} criativo(s) e {n_ad} anúncio(s), "
          'TUDO PAUSADO. Nada é ativado por aqui.')
    try:
        resp = (entrada('Digite SIM para criar: ') or '').strip()
    except (EOFError, KeyboardInterrupt):
        resp = ''
    if resp != 'SIM':
        print('Cancelado. Nada foi criado.')
        return None
    criados = {'campanha': None, 'conjuntos': [], 'criativos': [], 'anuncios': []}
    try:
        assert plano['campanha']['status'] == 'PAUSED'
        c = acoes._post(f'{conta}/campaigns', _form(plano['campanha']), token)
        criados['campanha'] = c['id']
        print(f"   campanha {c['id']} criada")
        for cj in plano['conjuntos']:
            payload = {**cj['payload'], 'campaign_id': c['id'], 'status': 'PAUSED'}
            s = acoes._post(f'{conta}/adsets', _form(payload), token)
            criados['conjuntos'].append(s['id'])
            print(f"   conjunto {s['id']} criado ({cj['payload']['name']})")
            for ad in cj['anuncios']:
                cr_payload = {k: v for k, v in ad['criativo'].items() if not k.startswith('_')}
                cr = acoes._post(f'{conta}/adcreatives', _form(cr_payload), token)
                criados['criativos'].append(cr['id'])
                a = acoes._post(f'{conta}/ads', _form({**ad['anuncio'], 'adset_id': s['id'], 'status': 'PAUSED',
                                                      'creative': {'creative_id': cr['id']}}), token)
                criados['anuncios'].append(a['id'])
                print(f"      anúncio {a['id']} criado ({ad['anuncio']['name']})")
        for obj in [criados['campanha']] + criados['conjuntos'] + criados['anuncios']:
            print('   ' + acoes._garantir_pausado(obj, token))
    except (acoes.ErroAcao, KeyError, AssertionError) as e:
        print(f'\nERRO: {e}\nParei aqui. O que já foi criado está PAUSADO: {json.dumps(criados)}')
        _registrar({'tipo': 'replicacao', 'situacao': 'ERRO', 'erro': str(e), 'origem': plano['origem'], 'criados': criados})
        return criados
    _registrar({'tipo': 'replicacao', 'situacao': 'CRIADA PAUSADA', 'origem': plano['origem'], 'criados': criados})
    print(f"\nPRONTO: campanha {criados['campanha']} criada PAUSADA. Revise no Gerenciador e ative por lá.")
    return criados


# ============================================================
# COMANDO
# ============================================================

def main(argv=None):
    ap = argparse.ArgumentParser(prog='replicar', description='Replica campanha do Meta a partir do backup (nasce pausada)')
    ap.add_argument('--listar', action='store_true')
    ap.add_argument('--frente', choices=['agro', 'prev', 'outros'])
    ap.add_argument('--campanha')
    ap.add_argument('--backup', help='caminho de um bruto.json (padrão: o mais recente)')
    ap.add_argument('--conta')
    ap.add_argument('--orcamento-diario', type=float)
    ap.add_argument('--regiao', help='estados separados por vírgula (ex.: "Rondônia,Acre" ou "RO,AC")')
    ap.add_argument('--genero', choices=['todos', 'homens', 'mulheres'])
    ap.add_argument('--todos', action='store_true')
    ap.add_argument('--ia', action='store_true')
    ap.add_argument('--aplicar', action='store_true')
    a = ap.parse_args(argv)

    dados = carregar_backup(a.backup)
    if a.listar or not a.campanha:
        listar(dados, a.frente)
        return 0
    camp = achar_campanha(dados, a.campanha)
    conta = a.conta if not a.conta or a.conta.startswith('act_') else f'act_{a.conta}'
    plano = montar_plano(dados, camp, todos=a.todos, conta=conta, orcamento_diario=a.orcamento_diario, genero=a.genero)
    if not plano['conjuntos']:
        raise SystemExit('A campanha não tem conjunto/anúncio com resultado ou ativo para replicar (use --todos).')
    if a.ia:
        rev = revisar_com_ia(plano, melhores_da_frente(dados, frente(camp.get('name'))))
        pedidos = aplicar_revisao(plano, rev)
        if len(pedidos) == 1 and not a.regiao:
            trocar_regiao(plano, list(next(iter(pedidos))))
        elif len(pedidos) > 1:
            plano['avisos'].append('a IA sugeriu regiões diferentes por conjunto: ' +
                                   '; '.join(f"{c['origem_nome']}: {', '.join(c.get('estados_ia', []))}" for c in plano['conjuntos']) +
                                   ' (aplique com --regiao, um conjunto por vez, se concordar)')
    if a.regiao:
        trocar_regiao(plano, a.regiao.split(','))
    print('\n' + texto_plano(plano))
    base = salvar_plano(plano)
    print(f'\nPlano salvo: {base}.txt / .json')
    if not a.aplicar:
        print('SIMULAÇÃO: nada foi enviado ao Meta. Para criar (tudo pausado): mesmo comando com --aplicar.')
        return 0
    criar(plano)
    return 0


if __name__ == '__main__':
    sys.exit(main())
