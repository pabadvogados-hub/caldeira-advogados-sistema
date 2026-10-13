"""
TRAFEGO PAGO (Meta Ads) + FUNIL - Caldeira Advogados Associados

  Plano de campanha (conversas no WhatsApp), com publicos por regiao a partir do radar de credito rural:
    python MARKETING/trafego.py plano --orcamento-mensal 3000 [--uf RO,MT] [--radar ARQ.json] [--ia] [--exemplo]

  Analise por anuncio/criativo (so leitura): ESCALAR / MANTER / PAUSAR / TROCAR CRIATIVO, com motivo:
    python MARKETING/trafego.py criativos --dias 7|14|30 [--exemplo] [--sem-ia]

  Acoes na conta (pausar, orcamento +-20%, duplicar PAUSADO). Sem --aplicar = so simulacao:
    python MARKETING/trafego.py acoes --dias 7 [--aplicar] [--exemplo]

  Funil do mes (gasto -> conversas -> qualificados -> reunioes -> contratos -> CAC e ROI):
    python MARKETING/trafego.py funil [--mes MM/AAAA] [--csv ATENDIMENTO.csv] [--gasto VALOR] [--exemplo]

  Pagina para o produtor rural (landing) e links com UTM:
    python MARKETING/trafego.py landing [--whatsapp 5569...] [--pixel ID] [--calculadora-url URL]
    python MARKETING/trafego.py utm --campanha X --conjunto Y --anuncio Z [--landing-url URL]

Regras (Provimento 205/2021 da OAB): anuncio informativo, sem promessa de resultado, sem preco,
sem "gratis" como chamariz, sem sensacionalismo. A conta de anuncios so e alterada pelo comando
`acoes --aplicar`, com credencial propria e confirmacao digitada item a item (ver meta_acoes.py).
POP: docs/POP_MARKETING_TRAFEGO.md | Guia de quem monitora: docs/GUIA_MONITOR_CAMPANHAS.md
"""
import argparse
import base64
import csv
import glob
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
import ambiente  # noqa: E402  (carrega .env e caminhos)

AQUI = os.path.dirname(os.path.abspath(__file__))
COMERCIAL = os.path.join(ambiente.RAIZ, 'COMERCIAL')
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)
if COMERCIAL not in sys.path:
    sys.path.append(COMERCIAL)

from config.escritorio import ESCRITORIO, TITULAR  # noqa: E402
from config_comercial import META, RADAR, UFS_ATENDIMENTO, WHATSAPP_CALCULADORA  # noqa: E402
from html_util import cartoes, esc, lista, numero, pagina, reais, tabela  # noqa: E402

EXEMPLOS = os.path.join(AQUI, 'exemplos')
EXEMPLO_RADAR = os.path.join(EXEMPLOS, 'TRAFEGO_RADAR_EXEMPLO.json')
EXEMPLO_CRIATIVOS = os.path.join(EXEMPLOS, 'TRAFEGO_CRIATIVOS_EXEMPLO.json')

# ============================================================
# REGRAS DO TRAFEGO (o escritorio ajusta aqui)
# ============================================================
REGRAS = {
    'piso_diario_conjunto': 20.0,   # R$/dia minimo por conjunto (menos que isso o Meta mal sai do aprendizado)
    'teto_pct_conjunto': 50,        # no teste, nenhum conjunto leva mais que isso do orcamento
    'max_conjuntos': 4,
    'cidades_por_conjunto': 6,
    'top_municipios': RADAR.get('top_sugestao', 15),
    'raio_km': 40,                  # raio em volta de cada cidade (zona rural extensa)
    'idade_min': 28,
    'idade_max': 65,                # 65 = "65+" no Gerenciador
    # analise de criativos
    'min_impressoes_julgar': 1000,  # antes disso: poucos dados, MANTER
    'min_leads_escalar': 5,
    'escalar_cpl_fator': 0.8,       # ESCALAR se CPL <= 80% da referencia
    'pausar_cpl_fator': 2.0,        # PAUSAR se CPL >= 2x a referencia com gasto >= 3x a referencia
    'queda_ctr_fadiga_pct': 20,     # CTR caiu 20%+ contra o periodo anterior + frequencia alta = fadiga
    'frequencia_maxima': 4.5,       # acima disso troca o criativo mesmo sem queda de CTR
    'gancho_video_min_pct': 15,     # visualizacoes de 3s / impressoes abaixo disso = inicio do video fraco
}

MENSAGEM_WHATSAPP = 'Olá! Vi a informação sobre crédito rural e gostaria de falar com a equipe do escritório.'
MODELO_IA = os.getenv('MODELO_MARKETING') or os.getenv('MODELO_SDR') or 'claude-sonnet-5'


# ============================================================
# UTILITARIOS
# ============================================================

def sem_acento(txt):
    return ''.join(c for c in unicodedata.normalize('NFD', str(txt or '')) if unicodedata.category(c) != 'Mn')


def slug(txt, maximo=40):
    s = re.sub(r'[^a-z0-9]+', '-', sem_acento(txt).lower()).strip('-')
    return s[:maximo].strip('-') or 'sem-nome'


def pct(v, casas=1):
    return '-' if v is None else f'{numero(v, casas)}%'


def numero_whatsapp(numero_=None):
    d = re.sub(r'\D', '', numero_ or WHATSAPP_CALCULADORA or ESCRITORIO.get('central') or ESCRITORIO['telefone'])
    if len(d) in (10, 11):
        d = '55' + d
    if len(d) not in (12, 13):
        raise SystemExit(f'Número de WhatsApp inválido: {numero_!r} (use DDI+DDD+número, ex.: 5569999999999)')
    return d


def pasta(saida, *partes):
    if saida:
        caminho = os.path.join(saida, *partes)
        os.makedirs(caminho, exist_ok=True)
        return caminho
    return ambiente.pasta_saida('marketing', *partes)


def _ler_json(caminho):
    with open(caminho, encoding='utf-8') as f:
        return json.load(f)


# ------------------------------------------------------------
# Conformidade (Provimento 205/2021). Usa MARKETING/conformidade.py quando existir.
# ------------------------------------------------------------
_PROIBIDOS = [
    (r'\bgaranti', 'promessa ou garantia de resultado'),
    (r'\bgr[aá]tis\b|\bgratuit', '"grátis"/gratuidade como chamariz'),
    (r'R\$\s*\d', 'menção a valor ou preço'),
    (r'\b100\s*%|\bcerteza\b|\bsem risco\b|\bresolvemos\b|\bganhe\b|\bcausa ganha\b|\bvit[oó]ria garantida',
     'promessa de resultado'),
    (r'\bmelhor(es)? advogad|\bn[ºo°]\s*1\b|\bl[ií]der(es)? (em|no|na)\b', 'autopromoção ou comparação'),
    (r'!!|\burgente\b|[uú]ltima chance|n[aã]o perca', 'sensacionalismo ou urgência artificial'),
    (r'\bsuspens[aã]o (garantid|imediat)|\blimpa(r)? (o )?nome\b', 'promessa de resultado'),
]


def _checagem_minima(texto):
    t = sem_acento(texto or '').lower()
    achados = []
    for padrao, motivo in _PROIBIDOS:
        m = re.search(sem_acento(padrao).lower(), t, re.I)
        if m and motivo not in achados:
            achados.append(f'{motivo} ("{m.group(0).strip()}")')
    return achados


def _normalizar_conformidade(r):
    """Resultado do conformidade.verificar -> [(descricao, grave)]. None se o formato for desconhecido."""
    if r is None:
        return None
    if isinstance(r, bool):
        return [] if r else [('reprovado na checagem de conformidade', True)]
    if isinstance(r, str):
        return [(r, True)] if r.strip() else []
    if isinstance(r, dict):
        for chave in ('alertas', 'problemas', 'violacoes', 'itens', 'achados', 'avisos'):
            if isinstance(r.get(chave), list):
                return _normalizar_conformidade(r[chave])
        return [] if r.get('ok', r.get('aprovado', True)) else [('reprovado na checagem de conformidade', True)]
    if isinstance(r, (list, tuple)):
        # a mesma regra pode aparecer varias vezes: junta os trechos numa linha so
        grupos = {}
        for x in r:
            regra, trecho, grave = _item(x)
            g = grupos.setdefault(regra, [[], False])
            if trecho and trecho not in g[0]:
                g[0].append(trecho)
            g[1] = g[1] or grave
        return [(regra + (' (' + ', '.join(f'"{t}"' for t in trechos) + ')' if trechos else ''), grave)
                for regra, (trechos, grave) in grupos.items()]
    return None


def _item(x):
    """(regra, trecho, grave) de um alerta."""
    if isinstance(x, dict):
        regra = str(x.get('regra') or x.get('motivo') or x.get('descricao') or x.get('problema') or '')
        grave = str(x.get('gravidade', 'BLOQUEIA')).upper() == 'BLOQUEIA'
        return (regra or json.dumps(x, ensure_ascii=False), str(x.get('trecho') or ''), grave)
    return (str(x), '', True)


def conformidade_itens(texto):
    """[(descricao, grave)] do texto. Usa MARKETING/conformidade.py; sem ele, a checagem minima. Nunca levanta erro."""
    try:
        import conformidade  # modulo do MARKETING (outro componente); pode ainda nao existir
        r = _normalizar_conformidade(conformidade.verificar(texto))
        if r is not None:
            return r
    except Exception:  # noqa: BLE001 - modulo ausente ou em construcao: usa a checagem minima
        pass
    return [(p, True) for p in _checagem_minima(texto)]


def verificar_conformidade(texto):
    """Lista de problemas (texto), graves marcados com [BLOQUEIA]. Vazia = nada encontrado."""
    return [('[BLOQUEIA] ' if grave else '[ATENÇÃO] ') + d for d, grave in conformidade_itens(texto)]


# ============================================================
# UTM + codigo de referencia (para o funil saber de onde veio o lead)
# ============================================================

def codigo_ref(campanha, conjunto, anuncio):
    chave = f'{slug(campanha)}|{slug(conjunto)}|{slug(anuncio)}'
    return 'MKT-' + base64.b32encode(hashlib.sha1(chave.encode()).digest()).decode()[:5]


PASTA_CODIGOS = None   # None = SAIDA/marketing (testes podem apontar para outra pasta)


def caminho_codigos():
    return os.path.join(PASTA_CODIGOS or ambiente.pasta_saida('marketing'), 'utm_codigos.csv')


def registrar_codigo(cod, campanha, conjunto, anuncio):
    arq = caminho_codigos()
    existentes = set()
    if os.path.exists(arq):
        with open(arq, encoding='utf-8-sig') as f:
            existentes = {linha.split(';')[0] for linha in f}
    if cod in existentes:
        return
    novo = not os.path.exists(arq)
    with open(arq, 'a', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        if novo:
            w.writerow(['codigo', 'campanha', 'conjunto', 'anuncio', 'criado_em'])
        w.writerow([cod, campanha, conjunto, anuncio, date.today().isoformat()])


def ler_codigos():
    """{codigo: {'campanha', 'conjunto', 'anuncio'}} dos links gerados."""
    arq = caminho_codigos()
    if not os.path.exists(arq):
        return {}
    with open(arq, encoding='utf-8-sig') as f:
        return {r['codigo']: r for r in csv.DictReader(f, delimiter=';')}


def links_utm(campanha, conjunto, anuncio, landing_url=None, whatsapp=None, registrar=True):
    cod = codigo_ref(campanha, conjunto, anuncio)
    params = {'utm_source': 'meta', 'utm_medium': 'trafego_pago', 'utm_campaign': slug(campanha),
              'utm_term': slug(conjunto), 'utm_content': slug(anuncio)}
    landing_url = landing_url or os.getenv('MARKETING_LANDING_URL') or ''
    mensagem = f'{MENSAGEM_WHATSAPP} (ref. {cod})'
    saida = {
        'codigo': cod, 'utm': params, 'mensagem': mensagem,
        'whatsapp': f'https://wa.me/{numero_whatsapp(whatsapp)}?text={quote(mensagem)}',
        'landing': (landing_url + ('&' if '?' in landing_url else '?') + urlencode({**params, 'ref': cod}))
                   if landing_url else
                   '[PREENCHER: endereço onde a landing foi publicada]?' + urlencode({**params, 'ref': cod}),
    }
    if registrar:
        registrar_codigo(cod, campanha, conjunto, anuncio)
    return saida


def cmd_utm(args):
    global PASTA_CODIGOS
    if args.saida:
        PASTA_CODIGOS = pasta(args.saida)
    r = links_utm(args.campanha, args.conjunto, args.anuncio, args.landing_url, args.whatsapp)
    print('\n=== LINKS COM UTM ===')
    print(f"Código de referência: {r['codigo']}  (vai no fim da mensagem; o SDR registra como ORIGEM do lead)")
    print(f"UTM: {urlencode(r['utm'])}")
    print(f"\nWhatsApp (mensagem pré-preenchida):\n  {r['whatsapp']}")
    print(f"\nLanding:\n  {r['landing']}")
    print(f"\nMensagem para colar no anúncio de WhatsApp (campo 'mensagem pré-preenchida'):\n  {r['mensagem']}")
    print(f'\nCódigos gerados ficam em: {caminho_codigos()}')
    return r


# ============================================================
# LANDING (pagina unica para o produtor rural)
# ============================================================
PASTA_LANDING = os.path.join(AQUI, 'landing')
MODELO_LANDING = os.path.join(PASTA_LANDING, 'modelo.html')
MENSAGEM_LANDING = 'Olá! Vi a página sobre dívida rural e gostaria de falar com a equipe do escritório.'
CALCULADORA_LOCAL = '../../COMERCIAL/calculadora/index.html'   # funciona abrindo do computador


def cmd_landing(args):
    import html as _html
    with open(MODELO_LANDING, encoding='utf-8') as f:
        modelo = f.read()
    numero_ = numero_whatsapp(args.whatsapp)
    pixel = re.sub(r'\D', '', args.pixel or '')
    calc = args.calculadora_url or os.getenv('MARKETING_CALCULADORA_URL') or CALCULADORA_LOCAL
    with open(os.path.join(ambiente.RAIZ, 'config', 'logo_caldeira.png'), 'rb') as f:
        logo = 'data:image/png;base64,' + base64.b64encode(f.read()).decode()
    e = ESCRITORIO
    campos = {
        'ESCRITORIO': e['nome'], 'CNPJ': e['cnpj'], 'ENDERECO': e['endereco'],
        'CIDADE_UF': f"{e['cidade']}/{e['uf']}", 'TELEFONE': e.get('central') or e['telefone'],
        'EMAIL': e['email'], 'INSTAGRAM': e['instagram'],
        'RESPONSAVEL': f"Dr. {TITULAR['nome']} - {TITULAR['oab']}",
        'WHATSAPP_LINK': f'https://wa.me/{numero_}?text={quote(MENSAGEM_LANDING)}',
        'CALCULADORA_URL': calc, 'ANO': str(date.today().year),
    }
    pagina_ = modelo.replace('{{LOGO}}', logo)
    for chave, valor in campos.items():
        pagina_ = pagina_.replace('{{' + chave + '}}', _html.escape(valor, quote=True))
    faltou = re.findall(r'\{\{[A-Z_]+\}\}', pagina_)
    if faltou:
        raise SystemExit(f'Modelo com campo sem valor: {sorted(set(faltou))}')
    config = json.dumps({'whatsapp': numero_, 'mensagem': MENSAGEM_LANDING, 'pixelId': pixel}, ensure_ascii=False)
    bloco = f'<!-- CONFIG-INICIO -->\n<script>\nwindow.CONFIG_LANDING = {config};\n</script>\n<!-- CONFIG-FIM -->'
    pagina_ = re.sub(r'<!-- CONFIG-INICIO -->.*?<!-- CONFIG-FIM -->', lambda _: bloco, pagina_, count=1, flags=re.S)
    pagina_ = re.sub(r'<!-- =+\s*MODELO da pagina.*?=+ -->\n', '', pagina_, count=1, flags=re.S)
    destino_dir = args.saida or PASTA_LANDING
    os.makedirs(destino_dir, exist_ok=True)
    destino = os.path.join(destino_dir, 'index.html')
    with open(destino, 'w', encoding='utf-8') as f:
        f.write(pagina_)
    problemas = verificar_conformidade(re.sub(r'<[^>]+>', ' ', pagina_.split('<main', 1)[-1].split('</main>')[0]))
    print('\n=== LANDING DO PRODUTOR RURAL ===')
    print(f'  {destino}  ({len(pagina_) // 1024} KB, um arquivo só)')
    print(f'  WhatsApp do botão: +{numero_}')
    print(f"  Pixel do Meta: {'LIGADO (' + pixel + ') - com aviso de cookies' if pixel else 'desligado (use --pixel ID para ligar)'}")
    print(f'  Calculadora: {calc}')
    if calc == CALCULADORA_LOCAL:
        print('  ATENÇÃO: o link da calculadora é o do computador. Ao publicar, rode de novo com '
              '--calculadora-url https://... (endereço onde a calculadora foi publicada).')
    print('  Conformidade do texto: ' + ('sem alerta automático (a revisão do advogado continua obrigatória)'
                                         if not problemas else '; '.join(problemas)))
    print('  Links dos anúncios para esta página: python MARKETING/trafego.py utm --campanha ... --landing-url https://...')
    return destino


# ============================================================
# PLANO DE CAMPANHA
# ============================================================

# Interesses do agro para o publico detalhado. confirmado=True so para o que e categoria padrao do Meta;
# o resto sai [CONFERIR] ate a busca de interesses (com token) ou a equipe achar o nome na tela.
INTERESSES = [
    ('Agricultura', True), ('Agronegócio', False), ('Soja', False), ('Pecuária', False), ('Gado de corte', False),
    ('Máquinas agrícolas', False), ('Trator', False), ('Fazenda', False), ('Cooperativa agrícola', False),
    ('Crédito rural', False), ('Canal Rural', False), ('Globo Rural', False),
]


def conferir_interesses(termos):
    """Com META_ACCESS_TOKEN: busca cada interesse na API de segmentacao do Meta (so leitura)."""
    saida = {}
    try:
        import meta_ads_integration as meta
        if not meta.get_token():
            return saida
        for termo in termos:
            try:
                r = meta._get('search', {'type': 'adinterest', 'q': termo, 'limit': 5, 'locale': 'pt_BR'})
            except meta.ErroMeta:
                continue
            for item in r.get('data', []):
                if sem_acento(item.get('name', '')).lower() == sem_acento(termo).lower():
                    lo, hi = item.get('audience_size_lower_bound'), item.get('audience_size_upper_bound')
                    saida[termo] = f"confirmado no Meta (id {item.get('id')}" + (
                        f", público {numero(lo)} a {numero(hi)})" if lo and hi else ')')
                    break
    except Exception:  # noqa: BLE001 - conferencia e opcional
        pass
    return saida


ANGULOS = [
    {
        'id': 'A1', 'nome': 'O que diz a regra (prorrogação)',
        'titulo': 'Dívida rural e prorrogação: entenda a regra',
        'texto': ('Produtor rural: quando a safra frustra ou a comercialização fica difícil, o Manual de Crédito '
                  'Rural prevê a prorrogação da dívida, com os mesmos encargos, desde que a incapacidade de '
                  'pagamento seja comprovada. Cada caso depende de análise. Entenda como funciona e quais '
                  'documentos ajudam.'),
        'mensagem': 'Olá! Quero entender como funciona a prorrogação de dívida rural.',
        'roteiro': [
            ('0-3s', 'Advogado em frente a uma lavoura ou no escritório, olhando para a câmera',
             'Safra frustrada e a parcela do banco vencendo?', 'SAFRA FRUSTRADA + PARCELA VENCENDO?'),
            ('3-12s', 'Corte para o texto do Manual de Crédito Rural na tela (item 2-6-4)',
             'O Manual de Crédito Rural prevê a prorrogação da dívida quando há frustração de safra ou '
             'dificuldade de comercialização, com comprovação.', 'MCR 2-6-4: prorrogação com comprovação'),
            ('12-22s', 'Mãos organizando cédulas, extratos e laudo sobre a mesa',
             'Cada caso precisa de análise. Cédulas, extratos e o registro da perda ajudam.',
             'Cédulas + extratos + registro da perda'),
            ('22-30s', 'Advogado de volta, logo do escritório no canto',
             'Informação do escritório Caldeira Advogados. Para entender o seu caso, chame no WhatsApp.',
             'Caldeira Advogados Associados - OAB/RO'),
        ],
    },
    {
        'id': 'A2', 'nome': 'Documentos que ajudam',
        'titulo': 'Frustração de safra: quais documentos guardar',
        'texto': ('Teve perda de safra e a parcela do crédito rural está chegando? Guarde as cédulas e aditivos, '
                  'os extratos, as notas fiscais e o registro da perda (laudo, decreto de emergência, comunicação '
                  'ao seguro). Esses documentos ajudam na análise de qualquer pedido ao banco.'),
        'mensagem': 'Olá! Tive perda de safra e quero saber quais documentos separar.',
        'roteiro': [
            ('0-3s', 'Close em uma pasta de documentos sendo aberta sobre a mesa da fazenda',
             'Perdeu a safra? Não jogue fora esses papéis.', 'GUARDE ESTES DOCUMENTOS'),
            ('3-15s', 'Cada documento aparece na tela, um por vez',
             'Cédula e aditivos, extratos, notas fiscais e o registro da perda: laudo, decreto de emergência '
             'ou comunicação ao seguro.', 'Cédula - Extratos - Notas - Laudo'),
            ('15-25s', 'Advogado explicando, com a pasta na mão',
             'São eles que mostram ao banco o que aconteceu com a produção.', 'Documento comprova a perda'),
            ('25-30s', 'Logo e contato', 'Dúvidas sobre o seu caso? Fale com a equipe pelo WhatsApp.',
             'Caldeira Advogados Associados'),
        ],
    },
    {
        'id': 'A3', 'nome': 'Produtor de soja',
        'titulo': 'Produtor de soja: quebra de safra e a parcela do custeio',
        'texto': ('Informação para o produtor de soja de Rondônia e do norte do Mato Grosso: a quebra de safra '
                  'por clima ou praga pode ser motivo de pedido de prorrogação do custeio, conforme as regras do '
                  'crédito rural. Entenda o que o banco costuma pedir e como o pedido é feito.'),
        'mensagem': 'Olá! Sou produtor de soja e quero entender a prorrogação do custeio.',
        'roteiro': [
            ('0-3s', 'Imagem de lavoura de soja com falhas (estiagem) ou vagens chochas',
             'A soja quebrou e o custeio vence agora?', 'QUEBRA DE SAFRA NA SOJA?'),
            ('3-15s', 'Advogado na lavoura ou em frente a um armazém',
             'As regras do crédito rural tratam da prorrogação quando a perda é comprovada.',
             'Prorrogação: regra do crédito rural'),
            ('15-25s', 'Tela com três itens: laudo, produtividade, notas',
             'Laudo agronômico, produtividade colhida e notas fiscais costumam ser pedidos.',
             'Laudo - Produtividade - Notas'),
            ('25-30s', 'Logo e contato', 'Informação do escritório Caldeira Advogados. Fale com a equipe.',
             'Caldeira Advogados Associados'),
        ],
    },
    {
        'id': 'A4', 'nome': 'Calculadora de juros (conteúdo útil)',
        'titulo': 'Quanto de juros tem o seu financiamento rural?',
        'texto': ('Use a calculadora informativa do escritório e veja a parcela, o total de juros e o custo efetivo '
                  'do seu financiamento rural. É uma simulação para entender o contrato; não substitui a análise '
                  'dos documentos.'),
        'mensagem': 'Olá! Quero usar a calculadora de juros do crédito rural.',
        'roteiro': [
            ('0-3s', 'Celular na mão, calculadora aberta na tela', 'Você sabe quanto paga de juros no custeio?',
             'QUANTO VOCÊ PAGA DE JUROS?'),
            ('3-18s', 'Gravação da tela da calculadora sendo preenchida (valores ilustrativos na tela)',
             'Coloque o valor, a taxa e o prazo e veja parcela, juros totais e custo efetivo.',
             'Valor + taxa + prazo = parcela e juros'),
            ('18-30s', 'Advogado', 'É uma simulação informativa. Para entender o seu contrato, fale com a equipe.',
             'Simulação informativa - Caldeira Advogados'),
        ],
    },
]


def carregar_radar(ufs, arquivo=None, exemplo=False):
    """Registros do radar (COMERCIAL/radar.py). Ordem: --radar, --exemplo, ultimo radar em SAIDA/radar/."""
    import radar
    if exemplo:
        dados = _ler_json(EXEMPLO_RADAR)
        fonte = 'DADOS DE EXEMPLO (números fictícios)'
    elif arquivo:
        dados = _ler_json(arquivo)
        fonte = os.path.basename(arquivo)
    else:
        candidatos = sorted(glob.glob(os.path.join(ambiente.SAIDA, 'radar', 'radar_*.json')), key=os.path.getmtime,
                            reverse=True)
        bons = [c for c in candidatos if all(u in os.path.basename(c) for u in ufs)]
        completos = [c for c in bons if 'INCOMPLETO' not in c]
        escolhido = (completos or bons or [None])[0]
        if not escolhido:
            raise SystemExit('Radar ainda não gerado para ' + ','.join(ufs) + '. Rode antes:\n'
                             '   python COMERCIAL/main.py radar --uf ' + ','.join(ufs) +
                             '\n(ou use --radar ARQUIVO.json, ou --exemplo para ver um plano com números fictícios)')
        dados = _ler_json(escolhido)
        fonte = os.path.basename(escolhido)
    regs = []
    for r in dados.get('municipios') or []:
        if r.get('uf', '').upper() not in ufs:
            continue
        r = dict(r)
        for campo in ('qtd_total', 'vl_total', 'vl_soja', 'vl_bovinos', 'area_soja_ha'):
            r[campo] = r.get(campo) or 0
        r['vl_foco'] = r.get('vl_foco') or (r['vl_soja'] + r['vl_bovinos'])
        r['vl_medio_contrato'] = r.get('vl_medio_contrato') or (r['vl_total'] / r['qtd_total'] if r['qtd_total'] else 0)
        regs.append(r)
    if not regs:
        raise SystemExit(f'O radar ({fonte}) não tem municípios de {", ".join(ufs)}.')
    if exemplo or 'indice' not in regs[0]:
        regs = radar.pontuar(regs)
    else:
        regs.sort(key=lambda r: (r.get('indice', 0), r['vl_total']), reverse=True)
    return {'municipios': regs, 'ano': dados.get('ano'), 'fonte': fonte, 'exemplo': exemplo,
            'incompleto': bool(dados.get('incompleto'))}


def _perfil(cidades):
    soja = sum(c['vl_soja'] for c in cidades)
    bov = sum(c['vl_bovinos'] for c in cidades)
    if soja > 1.5 * bov:
        return 'soja'
    if bov > 1.5 * soja:
        return 'pecuária'
    return 'soja e pecuária'


def _nome_meso(meso):
    return {'Norte Mato-grossense': 'Norte', 'Sinop': 'Norte', 'Leste Rondoniense': 'Leste',
            'Madeira-Guaporé': 'Madeira-Guaporé'}.get(meso, meso or 'demais')


def montar_conjuntos(regs, orcamento_mensal):
    """Agrupa os municipios prioritarios em conjuntos por regiao e divide o orcamento."""
    import radar
    elegiveis = [r for r in regs if r['qtd_total'] > 0 and (r['uf'] != 'MT' or r.get('mesorregiao') in radar.NORTE_MT)]
    top = elegiveis[:REGRAS['top_municipios']]
    grupos = {}
    for r in top:
        chave = (r['uf'], _nome_meso(r.get('mesorregiao')))
        grupos.setdefault(chave, []).append(r)
    conjuntos = []
    for (uf, meso), cidades in grupos.items():
        # partes equilibradas (8 cidades -> 4 + 4, e nao 6 + 2), mantendo a ordem do indice
        qtd = -(-len(cidades) // REGRAS['cidades_por_conjunto'])
        n = -(-len(cidades) // qtd)
        partes = [cidades[i:i + n] for i in range(0, len(cidades), n)]
        for i, parte in enumerate(partes):
            sufixo = '' if len(partes) == 1 else (' - núcleo' if i == 0 else f' - ampliação {i}')
            conjuntos.append({'nome': f'{uf} {meso}{sufixo} ({_perfil(parte)})', 'uf': uf, 'cidades': parte,
                              'peso': sum(c['vl_total'] for c in parte),
                              'contratos': sum(c['qtd_total'] for c in parte)})
    conjuntos.sort(key=lambda c: c['peso'], reverse=True)

    diario = orcamento_mensal / 30.4
    piso = REGRAS['piso_diario_conjunto']
    cabe = max(1, min(REGRAS['max_conjuntos'], int(diario // piso)))
    usados, fase2 = conjuntos[:cabe], conjuntos[cabe:]

    # divisao: piso para todos + o restante proporcional ao volume de credito, com teto por conjunto
    # teto so com 3+ conjuntos (com 2, um teto de 50% viraria divisao meio a meio)
    teto = diario * REGRAS['teto_pct_conjunto'] / 100 if len(usados) >= 3 else diario
    valores = {id(c): min(piso, diario / len(usados)) for c in usados}
    restante = diario - sum(valores.values())
    livres = list(usados)
    while restante > 0.01 and livres:
        soma = sum(c['peso'] for c in livres) or 1
        excesso, prox = 0.0, []
        for c in livres:
            v = valores[id(c)] + restante * c['peso'] / soma
            if v > teto:
                excesso += v - teto
                v = teto
            else:
                prox.append(c)
            valores[id(c)] = v
        restante, livres = excesso, prox
    for c in usados:
        c['diario'] = round(valores[id(c)], 2)
        c['mensal'] = round(c['diario'] * 30.4, 2)
        c['pct'] = 100.0 * c['diario'] / diario if diario else 0
    return usados, fase2, diario


def _ia_variacoes(conjuntos):
    """1 chamada: 2 variacoes de titulo/texto por angulo, dentro do Provimento 205. Opcional (--ia)."""
    import ia
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['angulos'], 'properties': {
        'angulos': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                               'required': ['id', 'variacoes'], 'properties': {
            'id': {'type': 'string'},
            'variacoes': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                                     'required': ['titulo', 'texto'], 'properties': {
                'titulo': {'type': 'string'}, 'texto': {'type': 'string'}}}}}}}}}
    sistema = ('Você escreve anúncios para um escritório de advocacia que defende produtores rurais em dívidas com '
               'bancos (Rondônia e norte do Mato Grosso). Regras obrigatórias do Provimento 205/2021 da OAB: '
               'conteúdo informativo, sem promessa ou garantia de resultado, sem preço ou gratuidade, sem '
               'sensacionalismo, sem autopromoção comparativa, sem pressão de urgência. Linguagem simples de quem '
               'vive no campo. Não invente números, leis ou prazos além dos que já estão no texto base.')
    base = [{'id': a['id'], 'titulo': a['titulo'], 'texto': a['texto']} for a in ANGULOS]
    regioes = [c['nome'] for c in conjuntos]
    conteudo = ('Crie 2 variações (título até 40 caracteres, texto até 350 caracteres) para cada ângulo abaixo, '
                f'mantendo o sentido. Regiões dos anúncios: {regioes}.\n\n'
                + json.dumps(base, ensure_ascii=False, indent=1))
    r = ia.json_por_schema(MODELO_IA, sistema, conteudo, schema, max_tokens=6000)
    return {a['id']: a['variacoes'] for a in r.get('angulos', [])}


def cmd_plano(args):
    ufs = [u.strip().upper() for u in (args.uf or ','.join(UFS_ATENDIMENTO)).replace(' ', ',').split(',') if u.strip()]
    if args.orcamento_mensal <= 0:
        raise SystemExit('Informe --orcamento-mensal maior que zero (em reais).')
    global PASTA_CODIGOS
    if args.saida:
        PASTA_CODIGOS = pasta(args.saida)
    print(f'\n=== PLANO DE CAMPANHA META ADS ({", ".join(ufs)}) ===')
    rad = carregar_radar(ufs, args.radar, args.exemplo)
    print(f"   radar: {rad['fonte']}" + (' (INCOMPLETO)' if rad['incompleto'] else ''))
    conjuntos, fase2, diario = montar_conjuntos(rad['municipios'], args.orcamento_mensal)
    confirmados = conferir_interesses([n for n, ok in INTERESSES if not ok]) if not args.exemplo else {}
    interesses = [(n, 'categoria padrão do Meta' if ok else confirmados.get(n, '[CONFERIR] no Gerenciador'))
                  for n, ok in INTERESSES]

    variacoes = {}
    if args.ia:
        print(f'   IA: variações dos anúncios ({MODELO_IA})...')
        try:
            variacoes = _ia_variacoes(conjuntos)
        except Exception as e:  # noqa: BLE001
            print(f'   aviso: IA indisponível ({e}); seguindo com os textos base')
    angulos = []
    for a in ANGULOS:
        a = dict(a)
        a['variacoes'] = [v for v in variacoes.get(a['id'], []) if v.get('titulo')]
        textos = [a['titulo'], a['texto'], a['mensagem']] + [x for v in a['variacoes'] for x in (v['titulo'], v['texto'])]
        textos += [linha[2] + ' ' + linha[3] for linha in a['roteiro']]
        a['conformidade'] = verificar_conformidade('\n'.join(textos))
        angulos.append(a)

    campanha = f"[{'+'.join(ufs)}] Conversas WhatsApp - Dívida rural"
    linhas_csv = []
    for c in conjuntos:
        for a in angulos:
            nome_ad = f"{a['id']} - {a['nome']}"
            ref = links_utm(campanha, c['nome'], nome_ad, registrar=not args.exemplo)
            linhas_csv.append({
                'Campanha': campanha, 'Objetivo': 'Engajamento > Apps de mensagens (WhatsApp) [CONFERIR nome na tela]',
                'Status inicial': 'PAUSADO (ativar só depois da revisão)',
                'Conjunto': c['nome'], 'Orçamento diário (R$)': f"{c['diario']:.2f}".replace('.', ','),
                'Locais (cidade + raio)': '; '.join(f"{x['municipio']}/{x['uf']} +{REGRAS['raio_km']} km"
                                                    for x in c['cidades']),
                'Idade': f"{REGRAS['idade_min']}-{REGRAS['idade_max']}+", 'Gênero': 'todos',
                'Interesses': ', '.join(n for n, _ in interesses),
                'Posicionamentos': 'Advantage+ (automático)',
                'Anúncio': nome_ad, 'Título': a['titulo'], 'Texto principal': a['texto'],
                'Chamada (botão)': 'Enviar mensagem (WhatsApp)',
                'Mensagem pré-preenchida': f"{a['mensagem']} (ref. {ref['codigo']})",
                'Código de referência': ref['codigo'], 'UTM': urlencode(ref['utm']),
                'Formato': 'vídeo 9:16 de 15-30s (roteiro no DOCX) ou imagem 1:1',
            })

    saida = pasta(args.saida, 'plano')
    base = os.path.join(saida, f"{date.today().isoformat()}_plano_trafego_{'-'.join(ufs)}"
                        + ('_EXEMPLO' if args.exemplo else ''))
    with open(base + '.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(linhas_csv[0].keys()), delimiter=';')
        w.writeheader()
        w.writerows(linhas_csv)
    plano = {'ufs': ufs, 'orcamento_mensal': args.orcamento_mensal, 'diario': diario, 'radar': rad['fonte'],
             'ano_radar': rad['ano'], 'exemplo': args.exemplo, 'campanha': campanha, 'interesses': interesses,
             'conjuntos': [{k: v for k, v in c.items() if k != 'cidades'} |
                           {'cidades': [f"{x['municipio']}/{x['uf']}" for x in c['cidades']]} for c in conjuntos],
             'fase2': [c['nome'] for c in fase2], 'angulos': angulos}
    with open(base + '.json', 'w', encoding='utf-8') as f:
        json.dump(plano, f, ensure_ascii=False, indent=1, default=str)
    docx_plano(base + '.docx', rad, conjuntos, fase2, diario, args.orcamento_mensal, angulos, interesses, campanha, ufs)

    print(f"\nOrçamento: {reais(args.orcamento_mensal)}/mês = {reais(diario)}/dia em {len(conjuntos)} conjunto(s)")
    for c in conjuntos:
        print(f"  - {c['nome']}: {reais(c['diario'])}/dia ({numero(c['pct'])}%) - "
              + ', '.join(x['municipio'] for x in c['cidades']))
    if fase2:
        print('  Fora por falta de verba (fase 2): ' + '; '.join(c['nome'] for c in fase2))
    if diario < REGRAS['piso_diario_conjunto']:
        print(f"  ATENÇÃO: {reais(diario)}/dia está abaixo do piso de {reais(REGRAS['piso_diario_conjunto'])}/dia: "
              'o teste vai demorar para ter dado confiável.')
    problemas = [(a['id'], p) for a in angulos for p in a['conformidade']]
    print('Conformidade dos textos: ' + ('OK' if not problemas else '; '.join(f'{i}: {p}' for i, p in problemas)))
    print(f'\nArquivos:\n  {base}.docx\n  {base}.csv\n  {base}.json')
    return base


def docx_plano(caminho, rad, conjuntos, fase2, diario, mensal, angulos, interesses, campanha, ufs):
    from docx_caldeira import lista as dlista
    from docx_caldeira import novo_documento, paragrafo, secao, tabela as dtabela, titulo
    doc = novo_documento()
    titulo(doc, 'Plano de campanha - Meta Ads (conversas no WhatsApp)')
    if rad['exemplo']:
        paragrafo(doc, 'DADOS DE EXEMPLO: os números do radar abaixo são fictícios. Rodar o radar real antes de usar.',
                  negrito=True)
    paragrafo(doc, f"{ESCRITORIO['nome']} - {date.today().strftime('%d/%m/%Y')}. Público: produtor rural "
                   f"({', '.join(ufs)}; no Mato Grosso, só o norte do estado).")

    secao(doc, '1. Resumo')
    dlista(doc, [
        f'Orçamento: {reais(mensal)} por mês = {reais(diario)} por dia.',
        'Objetivo da campanha: conversas no WhatsApp (o SDR atende e qualifica). [CONFERIR na tela: '
        'objetivo "Engajamento" ou "Leads" com local da conversão "Apps de mensagens - WhatsApp".]',
        f"Estrutura: 1 campanha -> {len(conjuntos)} conjunto(s) por região -> {len(angulos)} anúncios por conjunto "
        '(um por ângulo).',
        f"Regiões escolhidas pelo radar de crédito rural (Banco Central/SICOR, {rad['fonte']}"
        + (f", contratos de {rad['ano']}" if rad.get('ano') else '') + '). O radar mostra onde há mais crédito '
        'rural tomado; não traz nome de ninguém: serve para anúncio institucional por região.',
        'Divisão do orçamento: piso de ' + reais(REGRAS['piso_diario_conjunto']) + '/dia por conjunto e o restante '
        f"proporcional ao volume de crédito rural das cidades do conjunto (com 3 ou mais conjuntos, teto de "
        f"{REGRAS['teto_pct_conjunto']}% por conjunto durante o teste).",
        'Tudo é criado PAUSADO e só é ativado depois da revisão do texto (Provimento 205/2021).',
    ] + ([f"[CONFERIR] A verba diária ({reais(diario)}) está abaixo do piso de "
          f"{reais(REGRAS['piso_diario_conjunto'])} por conjunto: o teste vai demorar para ter dado confiável."]
         if diario < REGRAS['piso_diario_conjunto'] else []))

    secao(doc, '2. Conjuntos por região')
    dtabela(doc, ['Conjunto', 'Cidades (+raio)', 'R$/dia', 'R$/mês', '%', 'Contratos no radar'], [
        [c['nome'], ', '.join(f"{x['municipio']}/{x['uf']}" for x in c['cidades']) + f" (+{REGRAS['raio_km']} km)",
         reais(c['diario']), reais(c['mensal']), f"{numero(c['pct'])}%", numero(c['contratos'])] for c in conjuntos],
        larguras_cm=[4.2, 6.3, 1.9, 2.1, 1.2, 2.0])
    if fase2:
        paragrafo(doc, 'Ficaram de fora por falta de verba (entram quando o orçamento subir ou no lugar de um '
                       'conjunto que não performar): ' + '; '.join(c['nome'] for c in fase2) + '.')
    dlista(doc, [
        f"Idade: {REGRAS['idade_min']} a {REGRAS['idade_max']}+ anos; todos os gêneros; idioma português.",
        f"Local: cada cidade com raio de {REGRAS['raio_km']} km (zona rural extensa). Cidades vizinhas que se "
        'sobrepõem não são problema. Marcar "pessoas que moram neste local".',
        'Posicionamentos: Advantage+ (automático). Formato preferido: vídeo vertical 9:16 de 15 a 30 segundos.',
        'Se o Meta pedir "categoria especial de anúncio" (serviços financeiros/crédito), a segmentação por idade e '
        'raio fica limitada: aceitar e manter as cidades, sem idade. [CONFERIR na criação]',
    ])

    secao(doc, '3. Interesses do agro (público detalhado)')
    paragrafo(doc, 'Usar como sugestão para o Meta (deixar o "público detalhado Advantage+" ligado). Interesse '
                   'marcado [CONFERIR] precisa ser procurado pelo nome no Gerenciador: se não existir, pular.')
    dtabela(doc, ['Interesse', 'Situação'], [[n, s] for n, s in interesses], larguras_cm=[6, 11])

    secao(doc, '4. Ângulos dos anúncios')
    for a in angulos:
        paragrafo(doc, a['nome'], rotulo=a['id'], negrito=True)
        paragrafo(doc, a['titulo'], rotulo='Título')
        paragrafo(doc, a['texto'], rotulo='Texto principal')
        paragrafo(doc, a['mensagem'] + ' (ref. código do anúncio)', rotulo='Mensagem pré-preenchida')
        for i, v in enumerate(a['variacoes'], 1):
            paragrafo(doc, f"{v['titulo']} | {v['texto']}", rotulo=f'Variação IA {i} [CONFERIR]')
        dtabela(doc, ['Tempo', 'Cena', 'Fala', 'Texto na tela'], [list(x) for x in a['roteiro']],
                larguras_cm=[1.5, 5.0, 6.5, 4.0])
        paragrafo(doc, 'Conformidade: ' + ('nenhum problema encontrado na checagem automática (revisão humana '
                                           'continua obrigatória).' if not a['conformidade'] else
                                           '[CONFERIR] ' + '; '.join(a['conformidade'])))

    secao(doc, '5. Teste A/B de 14 dias')
    dtabela(doc, ['Dias', 'O que fazer'], [
        ['1 a 3', 'Aprendizado do Meta: não mexer (só pausar anúncio reprovado ou com problema de texto).'],
        ['4 a 7', 'Primeiro corte pelos critérios abaixo (relatório diário "criativos"). Anotar a qualidade das '
                  'conversas com o SDR (quantas viram reunião).'],
        ['7', 'Comparar ângulos (qual traz conversa mais barata E mais qualificada) e regiões. Definir o CPL alvo '
              '(média dos 7 dias) em COMERCIAL/config_comercial.py, META["cpl_alvo"].'],
        ['8 a 14', 'Mover verba aos poucos: no máximo 20% a cada 3 dias para o conjunto com menor custo por conversa '
                   'qualificada. Duplicar (PAUSADO) o conjunto vencedor para testar outra região.'],
        ['14', 'Decisão: ficar com os 2 melhores ângulos nas melhores regiões; pedir 2 criativos novos no ângulo '
               'vencedor. Relatório "funil" do mês mostra o custo por contrato.'],
    ], larguras_cm=[2.0, 15.0])

    secao(doc, '6. Critérios de corte')
    ref = reais(META['cpl_alvo']) if META.get('cpl_alvo') else 'a média da conta (até o CPL alvo ser definido)'
    dtabela(doc, ['Sinal', 'Regra', 'Ação'], [
        ['Custo por conversa (CPL)', f"CPL >= {REGRAS['pausar_cpl_fator']:g}x a referência ({ref}) com gasto >= 3x",
         'PAUSAR'],
        ['Gasto sem conversa', f"gastou >= {reais(META['gasto_minimo_sem_lead'])} (ou 2x o CPL) sem nenhuma conversa",
         'PAUSAR'],
        ['Taxa de clique (CTR)', f"abaixo de {numero(META['ctr_baixo_pct'], 1)}% depois de "
                                 f"{numero(REGRAS['min_impressoes_julgar'])} impressões", 'TROCAR CRIATIVO'],
        ['Frequência', f"acima de {numero(META['frequencia_alta'], 1)} com CTR caindo "
                       f"{REGRAS['queda_ctr_fadiga_pct']}%+, ou acima de {numero(REGRAS['frequencia_maxima'], 1)}",
         'TROCAR CRIATIVO / ampliar público'],
        ['Início do vídeo', f"menos de {REGRAS['gancho_video_min_pct']}% das impressões assistem 3 segundos",
         'refazer os 3 primeiros segundos'],
        ['Vencedor', f"{REGRAS['min_leads_escalar']}+ conversas e CPL <= {int(REGRAS['escalar_cpl_fator'] * 100)}% "
                     'da referência, sem cansaço', 'ESCALAR (+20% no conjunto, no máximo a cada 3 dias)'],
    ], larguras_cm=[3.8, 8.7, 4.5])

    secao(doc, '7. Cuidados obrigatórios')
    dlista(doc, [
        'Provimento 205/2021 da OAB: anúncio informativo; sem promessa ou garantia de resultado, sem preço, sem '
        '"grátis" como chamariz, sem sensacionalismo, sem "melhor escritório". O texto e o vídeo passam por '
        'revisão de um advogado antes de ativar.',
        'Nada de mensagem para lista comprada ou para pessoa identificada pelo radar: o radar é dado agregado.',
        'Pixel do Meta na landing só com aviso de cookies (LGPD) e decisão do escritório.',
        'Mudanças na conta pelo sistema só com "trafego.py acoes --aplicar" e confirmação item a item; '
        'nunca ativa nada sozinho.',
    ])

    secao(doc, '8. Como montar no Gerenciador de Anúncios')
    dlista(doc, [
        'Abrir o CSV que acompanha este plano (uma linha por anúncio): ele é o roteiro de montagem, não o arquivo '
        'de importação em massa do Meta.',
        f'Criar a campanha "{campanha}" com o objetivo de conversas no WhatsApp e orçamento no CONJUNTO '
        '(não na campanha), para dar para comparar as regiões.',
        'Criar um conjunto por linha da tabela 2 (cidades + raio, idade, interesses, orçamento diário).',
        'Em cada conjunto, um anúncio por ângulo, com a mensagem pré-preenchida da coluna do CSV (o código "ref." '
        'diz ao SDR de qual anúncio o lead veio).',
        'Deixar tudo pausado, pedir a revisão do texto, e só então ativar.',
    ])
    doc.save(caminho)
    return caminho


# ============================================================
# ANALISE DE CRIATIVOS (so leitura)
# ============================================================
CAMPOS_VIDEO = ',video_p50_watched_actions,video_p100_watched_actions,video_thruplay_watched_actions'
STATUS_LISTADOS = ['ACTIVE', 'PAUSED', 'ADSET_PAUSED', 'CAMPAIGN_PAUSED', 'WITH_ISSUES', 'IN_PROCESS',
                   'PENDING_REVIEW', 'DISAPPROVED']


def _por_ids(meta, ids, campos):
    """Le varios objetos, um GET por id. So leitura.
    (O atalho ?ids=... foi desligado pelo Meta na v26.0: responde 500 'ids query parameter is deprecated'.)"""
    saida = []
    for obj_id in [i for i in dict.fromkeys(ids) if i]:
        obj = meta._get(obj_id, {'fields': campos}) or {}
        obj.setdefault('id', obj_id)
        saida.append(obj)
    return saida


def coletar_criativos(dias):
    """Dados reais da conta (so leitura). None se o Meta nao estiver configurado."""
    import meta_ads_integration as meta
    from meta_ads import periodos
    if not meta.configurado():
        return None
    (d1, a1), (d0, a0) = periodos(dias)
    print(f'   período {d1} a {a1} (comparando com {d0} a {a0})')
    try:
        dados = {
            'periodo': [d1, a1], 'periodo_anterior': [d0, a0],
            'anuncios': meta.insights(level='ad', desde=d1, ate=a1, campos=meta.CAMPOS_PADRAO + CAMPOS_VIDEO),
            'anuncios_anterior': meta.insights(level='ad', desde=d0, ate=a0,
                                               campos='ad_id,spend,impressions,inline_link_clicks,clicks,frequency,actions'),
        }
    except meta.ErroMeta as e:
        raise SystemExit(f'ERRO na Meta API: {e}')
    dados['avisos'] = []
    ids_ad = [str(a.get('ad_id')) for a in dados['anuncios']]
    ids_cj = [str(a.get('adset_id')) for a in dados['anuncios']]
    for chave, ids, campos in (
            ('criativos', ids_ad, 'name,effective_status,adset_id,creative{title,body,video_id,object_type}'),
            ('conjuntos', ids_cj, 'name,campaign_id,effective_status,daily_budget,lifetime_budget')):
        try:
            dados[chave] = _por_ids(meta, ids, campos)
        except meta.ErroMeta as e:
            dados[chave] = []
            dados['avisos'].append(f'não consegui ler {chave} ({e}); a análise segue sem eles')
    return dados


def carregar_dados_criativos(dias, exemplo=False):
    if exemplo:
        from meta_ads import periodos
        dados = _ler_json(EXEMPLO_CRIATIVOS)
        (d1, a1), (d0, a0) = periodos(dias)
        dados.update({'_exemplo': True, 'periodo': [d1, a1], 'periodo_anterior': [d0, a0]})
        dados.setdefault('avisos', [])
        print('   usando dados FICTICIOS (MARKETING/exemplos/TRAFEGO_CRIATIVOS_EXEMPLO.json)')
        return dados
    return coletar_criativos(dias)


def _soma(acoes, tipo='video_view'):
    return sum(float(a.get('value') or 0) for a in (acoes or []) if a.get('action_type') == tipo)


def _video(linha, impressoes):
    v3 = _soma(linha.get('actions'))
    if not v3:
        return None
    p50, p100 = _soma(linha.get('video_p50_watched_actions')), _soma(linha.get('video_p100_watched_actions'))
    return {'views_3s': int(v3), 'gancho': 100.0 * v3 / impressoes if impressoes else None,
            'ret50': 100.0 * p50 / v3 if p50 else None, 'ret100': 100.0 * p100 / v3 if p100 else None}


def _var(atual, anterior):
    if atual is None or not anterior:
        return None
    return 100.0 * (atual - anterior) / anterior


def classificar(a, ref):
    """(recomendacao, motivo) de um anuncio. ref = CPL de referencia (meta do escritorio ou media da conta)."""
    R = REGRAS
    gasto, leads, cpl = a['gasto'], a['leads'], a['cpl']
    lim = max(META['gasto_minimo_sem_lead'], 2 * ref) if ref else META['gasto_minimo_sem_lead']
    rec, motivo = None, None
    if not leads and gasto >= lim:
        rec, motivo = 'PAUSAR', f'gastou {reais(gasto)} sem nenhuma conversa (limite {reais(lim)})'
    elif ref and leads and cpl >= R['pausar_cpl_fator'] * ref and gasto >= 3 * ref:
        rec, motivo = 'PAUSAR', f'custo por conversa {reais(cpl)} = {numero(cpl / ref, 1)}x a referência ({reais(ref)})'
    elif a['impressoes'] < R['min_impressoes_julgar']:
        rec, motivo = 'MANTER', f"poucos dados ainda ({numero(a['impressoes'])} impressões): esperar"
    elif (a['frequencia'] > META['frequencia_alta'] and a['var_ctr'] is not None
          and a['var_ctr'] <= -R['queda_ctr_fadiga_pct']):
        rec, motivo = 'TROCAR CRIATIVO', (f"público cansado: frequência {numero(a['frequencia'], 1)} e taxa de clique "
                                          f"caiu {numero(-a['var_ctr'])}% ({pct(a['ctr_anterior'], 2)} -> {pct(a['ctr'], 2)})")
    elif a['frequencia'] > R['frequencia_maxima']:
        rec, motivo = 'TROCAR CRIATIVO', (f"frequência {numero(a['frequencia'], 1)}: as mesmas pessoas já viram o "
                                          'anúncio muitas vezes')
    elif a['ctr'] < META['ctr_baixo_pct']:
        rec, motivo = 'TROCAR CRIATIVO', (f"poucos cliques: taxa de clique {pct(a['ctr'], 2)} (mínimo "
                                          f"{pct(META['ctr_baixo_pct'])}); testar outro começo, título ou imagem")
    elif a.get('video') and a['video']['gancho'] is not None and a['video']['gancho'] < R['gancho_video_min_pct']:
        rec, motivo = 'TROCAR CRIATIVO', (f"só {pct(a['video']['gancho'], 0)} de quem viu assistiu 3 segundos: "
                                          'refazer o começo do vídeo')
    elif ref and leads >= R['min_leads_escalar'] and cpl <= R['escalar_cpl_fator'] * ref:
        rec, motivo = 'ESCALAR', (f"{leads} conversas a {reais(cpl)} cada ({numero(100 * (1 - cpl / ref))}% abaixo "
                                  f"da referência {reais(ref)}), sem sinal de cansaço")
    elif leads:
        rec, motivo = 'MANTER', f'{leads} conversa(s) a {reais(cpl)} cada, dentro do esperado (referência {reais(ref)})'
    else:
        rec, motivo = 'MANTER', f'ainda sem conversa; gasto {reais(gasto)} abaixo do limite de corte ({reais(lim)})'
    graves = [p for p in a.get('conformidade') or [] if p.startswith('[BLOQUEIA]')]
    if graves:
        extra = f'; além disso: {motivo}' if rec == 'PAUSAR' else ''
        rec, motivo = 'PAUSAR', ('texto com risco no Provimento 205/2021: '
                                 + '; '.join(p.replace('[BLOQUEIA] ', '') for p in graves[:2])
                                 + ' - corrigir com um advogado antes de voltar' + extra)
    elif a.get('conformidade'):
        motivo += ' | atenção no texto: ' + '; '.join(p.replace('[ATENÇÃO] ', '') for p in a['conformidade'][:2])
    return rec, motivo


ORDEM_REC = {'PAUSAR': 0, 'TROCAR CRIATIVO': 1, 'ESCALAR': 2, 'MANTER': 3}


def analisar_criativos(dados):
    from meta_ads import metricas
    ant = {str(x.get('ad_id')): metricas(x) for x in dados.get('anuncios_anterior') or []}
    cria = {str(c.get('id')): c for c in dados.get('criativos') or []}
    cjs = {str(c.get('id')): c for c in dados.get('conjuntos') or []}

    anuncios = []
    for linha in dados.get('anuncios') or []:
        m = metricas(linha)
        ad_id = str(linha.get('ad_id'))
        c = cria.get(ad_id) or {}
        criativo = c.get('creative') or {}
        texto = ' '.join(x for x in (criativo.get('title'), criativo.get('body')) if x)
        a0 = ant.get(ad_id) or {}
        m.update({
            'id': ad_id, 'nome': linha.get('ad_name') or c.get('name') or ad_id,
            'campanha': linha.get('campaign_name', ''), 'conjunto': linha.get('adset_name', ''),
            'conjunto_id': str(linha.get('adset_id') or c.get('adset_id') or ''),
            'status': c.get('effective_status'), 'titulo': criativo.get('title', ''), 'texto': criativo.get('body', ''),
            'video': _video(linha, m['impressoes']),
            'ctr_anterior': a0.get('ctr') if a0.get('impressoes') else None,
            'cpl_anterior': a0.get('cpl'), 'conformidade': verificar_conformidade(texto) if texto else [],
        })
        m['var_ctr'] = _var(m['ctr'], m['ctr_anterior'])
        m['var_cpl'] = _var(m['cpl'], m['cpl_anterior'])
        anuncios.append(m)

    gasto = sum(a['gasto'] for a in anuncios)
    leads = sum(a['leads'] for a in anuncios)
    gasto0 = sum(a['gasto'] for a in ant.values())
    leads0 = sum(a['leads'] for a in ant.values())
    cpl_conta = gasto / leads if leads else None
    cpl_ant = gasto0 / leads0 if leads0 else None
    ref = META.get('cpl_alvo') or cpl_conta
    for a in anuncios:
        a['recomendacao'], a['motivo'] = classificar(a, ref)
    com = sorted([a for a in anuncios if a['leads']], key=lambda x: x['cpl'])
    sem = sorted([a for a in anuncios if not a['leads']], key=lambda x: x['gasto'], reverse=True)
    ranking = com + sem
    for i, a in enumerate(ranking, 1):
        a['posicao'] = i

    conjuntos = {}
    for a in anuncios:
        cj = conjuntos.setdefault(a['conjunto_id'], {'id': a['conjunto_id'], 'nome': a['conjunto'], 'gasto': 0.0,
                                                     'leads': 0, 'anuncios': 0})
        cj['gasto'] += a['gasto']
        cj['leads'] += a['leads']
        cj['anuncios'] += 1
    for cj in conjuntos.values():
        cj['cpl'] = cj['gasto'] / cj['leads'] if cj['leads'] else None
        orc = (cjs.get(cj['id']) or {}).get('daily_budget')
        cj['orcamento_diario'] = float(orc) / 100 if orc else None

    alertas = list(dados.get('avisos') or [])
    v = _var(cpl_conta, cpl_ant)
    if v is not None and v > META['alerta_cpl_subiu_pct']:
        alertas.append(f'Custo por conversa da conta subiu {numero(v)}%: {reais(cpl_ant)} -> {reais(cpl_conta)}.')
    if gasto and not leads:
        alertas.append(f'A conta gastou {reais(gasto)} sem nenhuma conversa no período.')
    for a in anuncios:
        if a['conformidade']:
            alertas.append(f"Anúncio \"{a['nome']}\" - conformidade (Provimento 205): {'; '.join(a['conformidade'])}.")
    resumo = {r: sum(1 for a in anuncios if a['recomendacao'] == r) for r in ORDEM_REC}
    return {'periodo': dados.get('periodo'), 'exemplo': bool(dados.get('_exemplo')),
            'conta': {'gasto': gasto, 'leads': leads, 'cpl': cpl_conta, 'cpl_anterior': cpl_ant, 'var_cpl': v,
                      'impressoes': sum(a['impressoes'] for a in anuncios)},
            'cpl_ref': ref, 'cpl_ref_origem': 'meta do escritório' if META.get('cpl_alvo') else 'média da conta no período',
            'anuncios': ranking, 'conjuntos': sorted(conjuntos.values(), key=lambda c: c['gasto'], reverse=True),
            'resumo': resumo, 'alertas': alertas}


def parecer_ia(analise):
    """Leitura em linguagem simples, feita pela IA SO com os numeros calculados (1 chamada)."""
    import ia
    schema = {'type': 'object', 'additionalProperties': False,
              'required': ['resumo', 'pontos', 'proximo_teste', 'cuidados'], 'properties': {
                  'resumo': {'type': 'string'}, 'pontos': {'type': 'array', 'items': {'type': 'string'}},
                  'proximo_teste': {'type': 'string'}, 'cuidados': {'type': 'array', 'items': {'type': 'string'}}}}
    sistema = ('Você é analista de tráfego pago de um escritório de advocacia que atende produtores rurais '
               '(Rondônia e norte do Mato Grosso). Escreva para a pessoa que monitora as campanhas, sem jargão. '
               'Use SOMENTE os números do JSON recebido: nunca invente métrica, porcentagem ou tendência que não '
               'esteja nele. As recomendações ESCALAR/MANTER/PAUSAR/TROCAR CRIATIVO já foram calculadas por regra: '
               'explique-as, não as troque. NADA foi alterado na conta: escreva "recomendado pausar", '
               '"sugerido trocar o criativo", nunca "foi pausado" ou "foi trocado". Formato do anúncio: só diga '
               '"vídeo" quando tem_video for true; nos demais, diga "anúncio" (pode ser imagem ou carrossel). '
               'Anúncios seguem o Provimento 205/2021 da OAB (sem promessa de '
               'resultado, sem preço, sem sensacionalismo): sugestões de criativo novo têm de respeitar isso. '
               'resumo: 3 a 5 frases. pontos: até 6 itens curtos. proximo_teste: 1 sugestão de teste. '
               'cuidados: até 3 itens.')
    campos = ('nome', 'conjunto', 'gasto', 'leads', 'cpl', 'ctr', 'ctr_anterior', 'frequencia', 'video',
              'recomendacao', 'motivo')
    conteudo = json.dumps({
        'periodo': analise['periodo'], 'conta': analise['conta'], 'cpl_referencia': analise['cpl_ref'],
        'anuncios': [{k: a.get(k) for k in campos} | {'tem_video': bool(a.get('video'))} for a in analise['anuncios']],
        'conjuntos': analise['conjuntos'],
    }, ensure_ascii=False, default=str)
    return ia.json_por_schema(MODELO_IA, sistema, conteudo, schema, max_tokens=4000)


def texto_whatsapp(analise, dias):
    c = analise['conta']
    d1, a1 = analise['periodo']
    L = [f"*Anúncios - últimos {dias} dias* ({datetime.fromisoformat(d1):%d/%m} a {datetime.fromisoformat(a1):%d/%m})"
         + (' [EXEMPLO]' if analise['exemplo'] else ''),
         f"Gasto {reais(c['gasto'])} | {c['leads']} conversas | "
         f"{reais(c['cpl']) + ' por conversa' if c['cpl'] else 'sem conversa'}"]
    if c['var_cpl'] is not None:
        L.append(f"Custo por conversa {'subiu' if c['var_cpl'] > 0 else 'caiu'} {numero(abs(c['var_cpl']))}% "
                 'contra o período anterior')
    for rec in ('PAUSAR', 'TROCAR CRIATIVO', 'ESCALAR'):
        for a in [x for x in analise['anuncios'] if x['recomendacao'] == rec][:3]:
            curto = a['motivo'] if len(a['motivo']) <= 110 else a['motivo'][:107] + '...'
            L.append(f"{rec}: {a['nome']} - {curto}")
    n = analise['resumo'].get('MANTER', 0)
    if n:
        L.append(f'MANTER: {n} anúncio(s)')
    L.append('Nada foi mudado na conta. Detalhes no relatório HTML.')
    return '\n'.join(L) + '\n'


def html_criativos(analise, dias):
    c, r = analise['conta'], analise['resumo']
    d1, a1 = analise['periodo']
    decisoes = [a for a in sorted(analise['anuncios'], key=lambda x: (ORDEM_REC[x['recomendacao']], x['posicao']))]
    blocos = [
        (None, cartoes([
            (reais(c['gasto']), 'gasto no período'), (str(c['leads']), 'conversas (leads)'),
            (reais(c['cpl']) if c['cpl'] else '-', 'custo por conversa'
             + (f" ({'+' if c['var_cpl'] > 0 else ''}{numero(c['var_cpl'])}% vs. anterior)" if c['var_cpl'] is not None else '')),
            (f"{r['ESCALAR']} / {r['MANTER']}", 'escalar / manter'),
            (f"{r['PAUSAR']} / {r['TROCAR CRIATIVO']}", 'pausar / trocar criativo')])),
        ('Alertas', lista(analise['alertas'] or ['Nenhum alerta no período.'], 'alerta' if analise['alertas'] else 'ok')),
        ('Decisão sugerida por anúncio (nada foi alterado na conta)', tabela(
            ['Recomendação', 'Anúncio', 'Conjunto', 'Motivo'],
            [[a['recomendacao'], a['nome'], a['conjunto'], a['motivo']] for a in decisoes],
            {i for i, a in enumerate(decisoes) if a['recomendacao'] in ('PAUSAR', 'TROCAR CRIATIVO')})),
    ]
    p = analise.get('parecer_ia')
    if p:
        blocos.append(('Leitura da IA (feita só com os números acima)', f"<p>{esc(p.get('resumo'))}</p>"
                       + lista(p.get('pontos') or []) + f"<p><b>Próximo teste:</b> {esc(p.get('proximo_teste'))}</p>"
                       + lista(p.get('cuidados') or [], 'nota')))

    def v(a, k):
        return a['video'][k] if a.get('video') and a['video'].get(k) is not None else None
    blocos += [
        ('Ranking (menor custo por conversa primeiro)', tabela(
            ['#', 'Anúncio', 'Gasto', 'Conversas', 'CPL', 'CTR', 'Var. CTR', 'Frequência', '3s / impressões',
             'Assistiu 50%', 'Assistiu 100%'],
            [[(str(a['posicao']), a['posicao']), a['nome'], (reais(a['gasto']), a['gasto']), (str(a['leads']), a['leads']),
              (reais(a['cpl']) if a['cpl'] else 'sem conversa', a['cpl'] or 999999),
              (pct(a['ctr'], 2), round(a['ctr'], 2)), (pct(a['var_ctr'], 0), a['var_ctr'] if a['var_ctr'] is not None else 0),
              (numero(a['frequencia'], 2), a['frequencia']),
              (pct(v(a, 'gancho'), 0), v(a, 'gancho') or 0), (pct(v(a, 'ret50'), 0), v(a, 'ret50') or 0),
              (pct(v(a, 'ret100'), 0), v(a, 'ret100') or 0)] for a in analise['anuncios']])),
        ('Conjuntos', tabela(['Conjunto', 'Anúncios', 'Gasto', 'Conversas', 'CPL', 'Orçamento/dia'], [
            [cj['nome'], (str(cj['anuncios']), cj['anuncios']), (reais(cj['gasto']), cj['gasto']),
             (str(cj['leads']), cj['leads']), (reais(cj['cpl']) if cj['cpl'] else '-', cj['cpl'] or 999999),
             (reais(cj['orcamento_diario']) if cj['orcamento_diario'] else 'na campanha', cj['orcamento_diario'] or 0)]
            for cj in analise['conjuntos']])),
        ('Como ler', lista([
            f"Referência de custo por conversa: {reais(analise['cpl_ref']) if analise['cpl_ref'] else '-'} "
            f"({analise['cpl_ref_origem']}).",
            'CPL = gasto ÷ conversas. CTR = cliques ÷ impressões. Frequência = quantas vezes, em média, a mesma pessoa viu.',
            '3s / impressões = de cada 100 pessoas que viram o vídeo, quantas assistiram 3 segundos (o "gancho"). '
            'Assistiu 50%/100% = das que passaram dos 3 segundos, quantas foram até a metade/o fim.',
            'ESCALAR = subir o orçamento do conjunto aos poucos (máx. 20% a cada 3 dias). TROCAR CRIATIVO = pedir '
            'vídeo/imagem nova, sem apagar o anúncio antigo antes do novo rodar.',
            'Para executar as sugestões com trava: python MARKETING/trafego.py acoes --dias ' + str(dias),
        ], 'nota')),
    ]
    sub = f'Últimos {dias} dias ({d1} a {a1})' + (' - DADOS DE EXEMPLO' if analise['exemplo'] else '')
    return pagina('Análise de criativos - Meta Ads', sub, blocos, 'Somente leitura: nenhuma campanha foi alterada.')


def cmd_criativos(args):
    print(f'\n=== CRIATIVOS META ADS ({args.dias} dias) ===')
    dados = carregar_dados_criativos(args.dias, args.exemplo)
    if dados is None:
        print('Meta Ads não configurado (META_ACCESS_TOKEN e META_AD_ACCOUNT_ID em config/.env): nada feito.\n'
              'Para ver o relatório com dados fictícios: python MARKETING/trafego.py criativos --exemplo')
        return None
    analise = analisar_criativos(dados)
    usar_ia = args.ia or (not args.exemplo and not args.sem_ia and ambiente.tem_credencial('ANTHROPIC_API_KEY'))
    if usar_ia and analise['anuncios']:
        print(f'   IA: leitura do relatório ({MODELO_IA})...')
        try:
            analise['parecer_ia'] = parecer_ia(analise)
        except Exception as e:  # noqa: BLE001 - a IA e complemento; o relatorio sai sem ela
            analise['alertas'].append(f'Leitura da IA indisponível ({e}).')
    saida = pasta(args.saida, 'criativos')
    base = os.path.join(saida, f"{date.today().isoformat()}_criativos_{args.dias}d" + ('_EXEMPLO' if args.exemplo else ''))
    txt = texto_whatsapp(analise, args.dias)
    with open(base + '.txt', 'w', encoding='utf-8') as f:
        f.write(txt)
    with open(base + '.html', 'w', encoding='utf-8') as f:
        f.write(html_criativos(analise, args.dias))
    with open(base + '.json', 'w', encoding='utf-8') as f:
        json.dump(analise, f, ensure_ascii=False, indent=1, default=str)
    print(txt)
    print(f'Arquivos: {base}.txt | .html | .json')
    return base


# ============================================================
# ACOES (com trava) - ver meta_acoes.py
# ============================================================

def cmd_acoes(args):
    import meta_acoes
    if args.exemplo and args.aplicar:
        raise SystemExit('--aplicar não funciona com --exemplo (os IDs do exemplo são fictícios). Nada foi alterado.')
    if args.saida:
        meta_acoes.PASTA_LOG = pasta(args.saida)
    print(f'\n=== AÇÕES NA CONTA DO META ({args.dias} dias) ===')
    dados = carregar_dados_criativos(args.dias, args.exemplo)
    if dados is None:
        raise SystemExit('Meta Ads não configurado (META_ACCESS_TOKEN e META_AD_ACCOUNT_ID em config/.env). '
                         'Para ver a simulação: --exemplo')
    analise = analisar_criativos(dados)
    conjuntos = {str(c.get('id')): c for c in dados.get('conjuntos') or []}
    acoes = meta_acoes.propor(analise, conjuntos)
    arq = os.path.join(pasta(args.saida, 'acoes'), f"{datetime.now():%Y-%m-%d_%H%M}_acoes"
                       + ('_EXEMPLO' if args.exemplo else '') + '.json')
    with open(arq, 'w', encoding='utf-8') as f:
        json.dump({'periodo': analise['periodo'], 'exemplo': args.exemplo, 'aplicar': args.aplicar, 'acoes': acoes},
                  f, ensure_ascii=False, indent=1, default=str)
    resumo = meta_acoes.executar(acoes, aplicar=args.aplicar, registrar_log=(not args.exemplo) or bool(args.saida))
    print(f'\nResumo: {resumo or "nada"} | propostas salvas em {arq}')
    return acoes


# ============================================================
# CLI
# ============================================================

def main(argv=None):
    ap = argparse.ArgumentParser(prog='trafego.py', description='Tráfego pago (Meta Ads) e funil - Caldeira Advogados')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('plano', help='plano de campanha a partir do radar de crédito rural')
    p.add_argument('--orcamento-mensal', type=float, required=True, help='verba de mídia por mês, em reais')
    p.add_argument('--uf', default='', help='ex.: RO,MT (padrão: UFs de atendimento)')
    p.add_argument('--radar', help='JSON do radar (padrão: o mais recente em SAIDA/radar/)')
    p.add_argument('--ia', action='store_true', help='pedir à IA 2 variações de texto por ângulo (1 chamada)')
    p.add_argument('--exemplo', action='store_true')
    p.add_argument('--saida')

    c = sub.add_parser('criativos', help='análise por anúncio: escalar, manter, pausar, trocar criativo')
    c.add_argument('--dias', type=int, default=7, choices=[7, 14, 30])
    c.add_argument('--exemplo', action='store_true')
    c.add_argument('--ia', action='store_true', help='forçar a leitura da IA (inclusive no exemplo)')
    c.add_argument('--sem-ia', action='store_true', help='não chamar a IA')
    c.add_argument('--saida')

    a = sub.add_parser('acoes', help='ações propostas; só executa com --aplicar + confirmação item a item')
    a.add_argument('--dias', type=int, default=7, choices=[7, 14, 30])
    a.add_argument('--aplicar', action='store_true')
    a.add_argument('--exemplo', action='store_true')
    a.add_argument('--saida')

    f = sub.add_parser('funil', help='funil do mês: gasto -> conversas -> reuniões -> contratos (CAC, ROI)')
    f.add_argument('--mes', help='MM/AAAA (padrão: mês anterior)')
    f.add_argument('--csv', help='export do atendimento (mesmas colunas da auditoria do comercial)')
    f.add_argument('--gasto', type=float, help='gasto do mês informado à mão (quando o Meta não está conectado)')
    f.add_argument('--exemplo', action='store_true')
    f.add_argument('--saida')

    lg = sub.add_parser('landing', help='gera MARKETING/landing/index.html')
    lg.add_argument('--whatsapp', help='número do botão, só dígitos com DDI (ex.: 5569999999999)')
    lg.add_argument('--pixel', default='', help='ID do Pixel do Meta (vazio = desligado)')
    lg.add_argument('--calculadora-url', help='endereço publicado da calculadora de juros')
    lg.add_argument('--saida', help='pasta de saída (padrão: MARKETING/landing)')

    u = sub.add_parser('utm', help='links de WhatsApp/landing com UTM padronizada')
    u.add_argument('--campanha', required=True)
    u.add_argument('--conjunto', required=True)
    u.add_argument('--anuncio', required=True)
    u.add_argument('--landing-url', help='endereço da landing publicada (ou MARKETING_LANDING_URL no .env)')
    u.add_argument('--whatsapp')
    u.add_argument('--saida', help='pasta do cadastro de códigos (padrão: SAIDA/marketing)')

    args = ap.parse_args(argv)
    if args.cmd == 'plano':
        return cmd_plano(args)
    if args.cmd == 'criativos':
        return cmd_criativos(args)
    if args.cmd == 'acoes':
        return cmd_acoes(args)
    if args.cmd == 'funil':
        import funil
        return funil.gerar(args.mes, exemplo=args.exemplo, csv_path=args.csv, gasto_manual=args.gasto, saida=args.saida)
    if args.cmd == 'landing':
        return cmd_landing(args)
    if args.cmd == 'utm':
        return cmd_utm(args)
    return None


if __name__ == '__main__':
    main()
