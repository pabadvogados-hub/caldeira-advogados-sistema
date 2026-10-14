"""
Regras da cobranca de documentos (pecas puras: sem rede, sem arquivo; testaveis).

Cada regra veio de um erro real de uma automacao de cobranca em producao. Antes de mexer,
leia o motivo que esta ao lado de cada uma:

  1. FASE DO CASO MANDA. Caso que ja andou (notificacao enviada, fase judicial, encerrado) nao
     recebe mais cobranca: com a peca pronta o documento nao faz falta e cobrar irrita o cliente
     e mostra desorganizacao do escritorio.
  2. SEM LISTA DO CASO, NAO COBRA. Lista generica mandada as cegas ja pediu documento de outro
     tipo de caso a quem nunca teria aquilo. Sem a analise da reuniao, segura e avisa a equipe.
  3. O QUE O CLIENTE DISSE QUE NAO TEM SAI DA LISTA (na reuniao ou depois, pelo WhatsApp). Pedir
     cinco vezes um documento que nunca existiu e o erro mais caro: o cliente para de responder.
  4. ITEM CONDICIONAL SO ENTRA COM SINAL. Documento que "so existe se aconteceu X" (laudo de
     frustracao de safra, GTA de pecuarista) so e cobrado quando o cliente disse que tem.
     Na duvida, nao cobra: melhor deixar de pedir algo que existe do que cobrar o que nao existe.
  5. NADA SENSIVEL POR MENSAGEM. Senha (gov.br) nunca se pede por WhatsApp: a equipe pega por
     ligacao. Para extrato, a mensagem avisa que o escritorio nunca pede senha, codigo ou PIX
     (cliente tem medo de golpe quando pedem extrato por mensagem).
  6. "JA ENTREGUEI" NAO SE COBRA. Se o cliente disse que entregou e o arquivo nao esta na pasta,
     o problema e interno: a equipe acha e guarda.
  7. CADENCIA GENTIL E COM FIM. No maximo 1 mensagem por dia por telefone, a cada INTERVALO_DIAS,
     ate MAX_TOQUES. Depois disso para e passa para uma pessoa da equipe.
  8. UMA PESSOA, UMA COBRANCA. O mesmo telefone pode aparecer em dois casos (cadastro duplicado
     com o nome escrito diferente): a trava diaria e pelo telefone, nunca pelo nome.
  9. HORARIO DE GENTE. So envia de segunda a sabado, das 8h as 19h.
 10. SIMULACAO E O PADRAO. Sem --enviar, nada sai.
"""
import re
import unicodedata
from datetime import date, datetime

INTERVALO_DIAS = 2
MAX_TOQUES = 5
HORA_INICIO, HORA_FIM = 8, 19          # janela de envio (hora local)
ALERTA_EQUIPE_A_CADA_DIAS = 3          # mesma pendencia nao e avisada todo dia

# fases em que o documento nao faz mais falta (prefixos de caso['etapa'])
FASES_QUE_ENCERRAM = ('ENCERRADO', 'JUDICIAL', 'DOCUMENTOS COMPLETOS')

# status que a analise da reuniao (triagem) da a cada item do checklist
JA_ENTREGOU, VAI_ENVIAR, NAO_TEM, NAO_FALADO = 'JA ENTREGOU', 'VAI ENVIAR', 'NAO TEM', 'NAO FALADO'
NA_PASTA = 'NA PASTA'

# ordem de prioridade (o toque 2 pede o primeiro que faltar)
PRIORIDADE = ['contratos', 'extratos', 'pagamentos', 'matricula', 'fiscal', 'pessoais', 'endereco',
              'frustracao', 'pecuaria', 'ir']

# como o cliente se refere a cada item quando diz que nao tem (regra 3)
PALAVRAS_ITEM = {
    'contratos': r'contrato|cedula|c[eé]dula|cpr|aditivo',
    'extratos': r'extrato',
    'pagamentos': r'comprovante|recibo|boleto',
    'matricula': r'matr[ií]cula|escritura|\bcar\b|ccir',
    'fiscal': r'nota fiscal|notas fiscais|\bnf\b|tal[aã]o',
    'pessoais': r'\brg\b|\bcnh\b|identidade|documento pessoal',
    'endereco': r'comprovante de (endere[cç]o|resid[eê]ncia)|conta de luz|conta de [aá]gua',
    'frustracao': r'laudo|frustra[cç][aã]o|proagro|decreto',
    'pecuaria': r'\bgta\b|idaron',
    'ir': r'imposto de renda|\birpf\b|declara[cç][aã]o',
}
NEGACAO = (r"n[aã]o\s+(tenho|tinha|tem|tive|recebi|guardei|guardo|acho|achei|consigo|existe|existia|fiz|fizeram)"
           r"|nunca\s+(tive|recebi|me\s+deram|fiz)|perdi|j[aá]\s+joguei\s+fora|o\s+banco\s+n[aã]o\s+(me\s+)?deu")


def sem_acento(t):
    return unicodedata.normalize('NFKD', t or '').encode('ascii', 'ignore').decode().lower()


def digitos(tel):
    return ''.join(c for c in str(tel or '') if c.isdigit())


def chave_telefone(tel):
    """Ultimos 8 digitos: casa o mesmo celular escrito com ou sem 55, DDD e o nono digito."""
    d = digitos(tel)
    return d[-8:] if len(d) >= 8 else ''


# ------------------------------------------------------------ regra 1: fase
def caso_encerrado(caso):
    """Motivo (texto) se a cobranca nao cabe mais pela fase do caso; None se ainda cabe."""
    etapa = (caso.get('etapa') or '').upper()
    for prefixo in FASES_QUE_ENCERRAM:
        if etapa.startswith(prefixo):
            return f'caso em "{caso.get("etapa")}"'
    for n in (caso.get('extrajudicial') or {}).get('notificacoes') or []:
        if n.get('enviada_em'):
            return f"notificação ao {n.get('banco') or 'banco'} já enviada em {n['enviada_em']}"
    return None


# ------------------------------------------------------------ regras 2 a 6: lista do caso
def lista_do_caso(status_documentos, tem_zapsign=False):
    """
    status_documentos: [{'id','nome','situacao','obrigatorio','sensivel'}] (pasta + o que foi dito na reuniao).
    Devolve (cobrar, avisos_equipe, fora): o que pedir ao cliente, o que a equipe resolve, o que ficou de fora e por que.
    """
    cobrar, equipe, fora = [], [], []
    for s in status_documentos or []:
        sit, ident = s.get('situacao'), s.get('id')
        if sit == NA_PASTA:
            continue
        if s.get('sensivel'):
            equipe.append(f"{s['nome']}: pegar por ligação (nunca por mensagem)")
            continue
        if ident == 'procuracao' and tem_zapsign:
            continue                                    # segue pela assinatura digital
        if sit == JA_ENTREGOU:
            equipe.append(f"{s['nome']}: cliente diz que já entregou, mas não está na pasta (achar e guardar)")
            continue
        if sit == NAO_TEM:
            fora.append((s, 'cliente disse na reunião que não tem'))
            continue
        if not s.get('obrigatorio') and sit != VAI_ENVIAR:
            fora.append((s, 'só existe em alguns casos e o cliente não disse que tem'))
            continue
        cobrar.append(s)
    cobrar.sort(key=lambda s: PRIORIDADE.index(s['id']) if s['id'] in PRIORIDADE else 99)
    return cobrar, equipe, fora


def podar_pelo_que_disse(cobrar, textos_do_cliente):
    """Tira da lista o que o cliente escreveu que nao tem. Devolve (lista, [(item, frase)])."""
    tirados = []
    restantes = []
    for s in cobrar:
        padrao = PALAVRAS_ITEM.get(s.get('id'))
        prova = None
        if padrao:
            for t in textos_do_cliente or []:
                tn = sem_acento(t)
                if re.search(sem_acento(padrao), tn) and re.search(sem_acento(NEGACAO), tn):
                    prova = t
                    break
        if prova:
            tirados.append((s, prova))
        else:
            restantes.append(s)
    return restantes, tirados


# ------------------------------------------------------------ regras 7 a 9: quando mandar
def dentro_do_horario(agora=None):
    agora = agora or datetime.now()
    return agora.weekday() < 6 and HORA_INICIO <= agora.hour < HORA_FIM


def proximo_toque(controle, hoje=None):
    """
    controle: bloco caso['cobranca_documentos'] ({'toques': [{'data','toque','enviado'}...]}).
    Devolve (numero_do_toque, None) se cabe mandar hoje, ou (None, motivo).
    """
    hoje = hoje or date.today()
    enviados = [t for t in controle.get('toques') or [] if t.get('enviado', True)]
    if len(enviados) >= MAX_TOQUES:
        return None, f'já foram {MAX_TOQUES} mensagens: passa para a equipe'
    if enviados:
        ultimo = date.fromisoformat(enviados[-1]['data'])
        if (hoje - ultimo).days < INTERVALO_DIAS:
            return None, f'última mensagem em {ultimo.isoformat()} (intervalo de {INTERVALO_DIAS} dias)'
    return len(enviados) + 1, None


def pode_avisar_equipe(controle, chave, hoje=None):
    hoje = hoje or date.today()
    ultimo = (controle.get('avisos_equipe') or {}).get(chave)
    return not ultimo or (hoje - date.fromisoformat(ultimo)).days >= ALERTA_EQUIPE_A_CADA_DIAS
