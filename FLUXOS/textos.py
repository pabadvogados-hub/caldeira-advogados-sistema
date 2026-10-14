"""
Textos de todos os fluxos (WhatsApp), na voz do escritorio para o produtor rural.

Regras de escrita:
  - simples, de quem vive no campo; sem juridiques;
  - lead: NADA de promessa de resultado, valor, prazo, chance ou honorario (Provimento 205/2021);
    tom informativo e convite para conversar; sem urgencia de pressao;
  - cliente: explica o porque de cada pedido; nunca pede senha, codigo nem pagamento por mensagem;
  - cada texto termina com o nome do escritorio.
Mudou um texto? Rode `python MARKETING/main.py conferir arquivo.txt` com o texto novo antes de ligar.
"""
import os


def escritorio():
    try:
        from config.escritorio import ESCRITORIO
        return ESCRITORIO['nome']
    except Exception:  # noqa: BLE001 - fora do sistema (testes)
        return os.getenv('NOME_ESCRITORIO', 'Caldeira Advogados Associados')


def nome1(nome):
    return (nome or '').strip().split(' ')[0].title() or 'tudo bem'


def _assina(txt):
    return f'{txt}\n\n{escritorio()}'


SEGURANCA = 'Importante: a gente nunca pede senha, código de verificação nem pagamento por aqui.'

# ============================================================
# LEADS
# ============================================================

def quentes(n, nome):
    p = nome1(nome)
    textos = {
        1: (f'Olá, {p}! Aqui é do {escritorio()}. Vi que você falou com a gente sobre a dívida no banco. '
            'Para eu entender melhor o seu caso: você já tem advogado cuidando disso ou alguma ação em andamento?'),
        2: (f'{p}, tudo bem? Fiquei de entender a sua situação com o banco. Se puder, me conta em poucas palavras '
            'qual banco e que tipo de financiamento é (custeio, investimento, CPR...).'),
        3: (f'Oi, {p}! Muita gente do campo só descobre o que a lei prevê para a dívida rural quando a parcela já '
            'venceu. Se quiser, a gente marca uma conversa rápida por aqui mesmo para olhar o seu caso.'),
        4: (f'{p}, vou deixar o seu atendimento em aberto por aqui. Quando quiser conversar sobre a dívida com o '
            'banco, é só responder esta mensagem.'),
    }
    return _assina(textos[n])


def fechamento(n, nome):
    p = nome1(nome)
    textos = [
        f'{p}, obrigado pela conversa! Ficou alguma dúvida sobre o que conversamos? Estou por aqui.',
        f'Oi, {p}! Se quiser, posso te mandar de novo, por escrito, os próximos passos que combinamos na reunião.',
        f'{p}, tudo bem? Conseguiu pensar no que conversamos? Se tiver alguma dúvida, me pergunta por aqui.',
        f'Oi, {p}! Se ajudar, a gente pode fazer uma ligação rápida com a sua família ou sócio para explicar o caminho.',
        f'{p}, só passando para saber se posso te ajudar em alguma coisa sobre a dívida com o banco.',
        f'Oi, {p}! Lembrando que, quanto antes o banco for notificado, antes o seu caso começa a andar.',
        f'{p}, ficou alguma dúvida sobre o contrato ou sobre os documentos? Posso explicar item por item.',
        f'Oi, {p}! Se o momento não for agora, sem problema: me fala e eu volto a falar com você mais para frente.',
        f'{p}, tudo certo por aí? Sigo à disposição para o que precisar.',
        f'Oi, {p}! Caso queira retomar, é só responder aqui que eu te mando os próximos passos.',
        f'{p}, passando para saber como está a situação com o banco. Mudou alguma coisa desde a nossa conversa?',
        f'Oi, {p}! Vou encerrar este atendimento por enquanto. Quando quiser retomar, é só me chamar por aqui.',
    ]
    return _assina(textos[min(n, len(textos)) - 1])


def reaquecimento(n, nome):
    p = nome1(nome)
    textos = {
        1: f'Olá, {p}! Aqui é do {escritorio()}. Como está a situação com o banco? Se precisar, estamos por aqui.',
        2: f'Oi, {p}! Passando para saber como foi a safra e se a dívida com o banco está sob controle.',
        3: f'{p}, tudo bem? Se a parcela do banco voltou a apertar, a gente pode olhar o seu caso de novo.',
        4: f'Oi, {p}! Faz um tempo que conversamos. Se precisar de ajuda com o banco, é só responder esta mensagem.',
    }
    return _assina(textos[n])


# ============================================================
# CONTRATACAO
# ============================================================

def boas_vindas(nome):
    p = nome1(nome)
    return _assina(
        f'Seja bem-vindo, {p}! Aqui é do {escritorio()} e a partir de agora a gente cuida do seu caso com o banco.\n\n'
        'Para preparar o seu contrato e a procuração, preciso de:\n'
        '1. foto da CNH ou do RG (frente e verso)\n'
        '2. um comprovante de endereço (conta de luz, água ou telefone). Se não tiver, pode me escrever o endereço '
        'completo: rua, número, bairro, cidade, estado e CEP.\n\n'
        'Pode mandar foto pelo celular mesmo, aqui nesta conversa.')


def lembrete_docs_contrato(n, nome):
    p = nome1(nome)
    textos = {
        1: f'Oi, {p}! Para eu preparar o seu contrato, falta só a foto da CNH (ou RG) e o comprovante de endereço.',
        2: f'{p}, se ficar mais fácil, pode mandar só a foto da CNH agora e me escrever o endereço completo.',
        3: f'Oi, {p}! Estou com o seu contrato quase pronto, esperando só o documento com foto e o endereço.',
        4: f'{p}, se tiver alguma dificuldade para mandar as fotos, me fala que alguém da equipe te liga para ajudar.',
    }
    return _assina(textos[n])


def assinatura(n, nome):
    p = nome1(nome)
    textos = {
        1: f'Oi, {p}! O seu contrato e a procuração estão prontos para assinar pelo celular, pelo link que mandamos.',
        2: f'{p}, conseguiu assinar? Se o link não abriu, me fala que eu mando de novo.',
        3: f'Oi, {p}! A assinatura é rápida: abre o link, confere o nome e assina com o dedo na tela.',
        4: f'{p}, é com a procuração assinada que a gente consegue notificar os bancos em seu nome.',
        5: f'Oi, {p}! Se preferir, alguém da equipe te liga e assina junto com você, passo a passo.',
        6: f'{p}, o seu contrato segue esperando a assinatura. Se tiver alguma dúvida sobre ele, me pergunta aqui.',
    }
    return _assina(textos[n])


def assinou(nome):
    return _assina(f'{nome1(nome)}, recebemos a sua assinatura. Obrigado pela confiança! Agora vamos aos documentos '
                   'do caso: daqui a pouco te mando a lista.')


# ============================================================
# DOCUMENTOS DO CASO
# ============================================================

COMO_MANDAR = {
    'pessoais': 'foto da CNH ou do RG (frente e verso)',
    'endereco': 'uma conta de luz, água ou telefone recente no seu nome',
    'contratos': 'cópia de TODOS os contratos e cédulas de TODOS os bancos, com os aditivos',
    'extratos': 'extratos das contas nos bancos onde tem financiamento',
    'pagamentos': 'comprovantes das parcelas que já pagou',
    'frustracao': 'o que tiver sobre a perda da safra (laudo, fotos, decreto de emergência, Proagro)',
    'matricula': 'matrícula do imóvel rural (do cartório, ou o CAR/CCIR)',
    'fiscal': 'notas fiscais de venda da produção',
    'procuracao': 'a procuração assinada (pelo link que mandamos)',
    'pecuaria': 'GTA e extrato do rebanho no órgão de defesa agropecuária',
    'ir': 'declaração do Imposto de Renda dos últimos 3 anos',
}

ONDE_ACHAR = {
    'contratos': 'a cédula e os aditivos ficam com o gerente do banco: pode pedir a cópia na agência',
    'extratos': 'o extrato sai pelo aplicativo do banco ou no caixa da agência',
    'pagamentos': 'os comprovantes ficam no aplicativo do banco, no histórico de pagamentos',
    'matricula': 'a matrícula sai no cartório de registro de imóveis; o CAR sai no site do CAR',
    'fiscal': 'as notas ficam com quem comprou a produção ou no talão de produtor',
    'endereco': 'serve qualquer conta de consumo recente no seu nome ou no do cônjuge',
}


def _item(s):
    return COMO_MANDAR.get(s.get('id'), s.get('nome', ''))


def _lista(itens):
    return '\n'.join(f'{i}. {_item(s)}' for i, s in enumerate(itens, 1))


def documentos(n, nome, itens):
    p = nome1(nome)
    if n == 1:
        txt = (f'Olá, {p}! Com os seus documentos em mãos a gente já notifica os bancos e o seu caso começa a andar. '
               f'Separei a lista do que falta (pode mandar foto pelo celular mesmo):\n\n{_lista(itens)}\n\n'
               'Manda o que já tiver, que o resto a gente vai completando.')
    elif n == 2:
        txt = (f'Oi, {p}! Se conseguir mandar só um agora, manda este: *{_item(itens[0])}*. '
               'É ele que libera a notificação aos bancos. Pode ser foto ou print.')
    elif n == 3:
        txt = (f'{p}, o seu caso está pronto para andar e esperando só estes documentos:\n\n{_lista(itens)}\n\n'
               'Quanto antes chegarem, antes a gente notifica os bancos. Foto pelo celular resolve.')
    elif n == 4:
        dicas = [f'- {ONDE_ACHAR[s["id"]]}' for s in itens if s.get('id') in ONDE_ACHAR][:3]
        txt = (f'Oi, {p}! Se algum documento estiver difícil de achar, a gente ajuda:\n\n'
               + ('\n'.join(dicas) + '\n\n' if dicas else '') + 'Me diz qual está faltando que eu explico o caminho.')
    else:
        txt = (f'{p}, para não deixar o seu caso parado, uma pessoa da nossa equipe vai te ligar para a gente '
               'reunir os documentos junto com você.')
    if any(s.get('id') == 'extratos' for s in itens):
        txt += f'\n\n{SEGURANCA}'
    return _assina(txt)


def documentos_completos(nome):
    return _assina(f'{nome1(nome)}, recebemos os documentos. Obrigado! Agora o seu caso segue com a equipe jurídica '
                   'e em breve você recebe as novidades por aqui.')


# ============================================================
# AVISOS DE FASE
# ============================================================

def aviso_notificacao(nome, bancos):
    alvo = ('o banco: ' + ', '.join(bancos)) if len(bancos) == 1 else (
        'os bancos: ' + ', '.join(bancos) if bancos else 'o banco')
    return _assina(f'{nome1(nome)}, novidade no seu caso: já notificamos {alvo}. Agora o banco tem um prazo para '
                   'responder e a gente acompanha. Qualquer resposta, você fica sabendo por aqui.')


def aviso_protocolo(nome):
    return _assina(f'{nome1(nome)}, novidade no seu caso: a ação foi protocolada na Justiça. A partir de agora a gente '
                   'acompanha cada andamento e te avisa por aqui. Se o banco ou alguém da Justiça te procurar, '
                   'fala com a gente antes de responder.')


# ============================================================
# EQUIPE
# ============================================================

def equipe(nome, telefone, texto):
    return f'[Fluxos] {nome or "?"} ({telefone or "sem telefone"}): {texto}'
