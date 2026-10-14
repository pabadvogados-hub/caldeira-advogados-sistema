"""
Exemplo de ponta a ponta com dados FICTICIOS (python FLUXOS/main.py exemplo). Nada sai da maquina:
o CRM e os casos sao de mentira e o estado vai para uma pasta temporaria.

Cada pessoa testa uma regra:
  Joao      lead quente que entrou hoje                       -> quentes, toque 1
  Pedro     lead quente que respondeu "ja tenho advogado"     -> para, vai para Perdido, avisa a equipe
  Maria     pos-reuniao ha 2 dias, 2 toques ja feitos         -> fechamento, toque 3
  Ana       "agora nao" ha 61 dias                            -> reaquecimento, toque 1
  Carlos    lead que falou em leilao hoje                     -> avisa a equipe: LIGAR JA
  Rosa      entrou em "Fechou" hoje                           -> boas-vindas
  Luiz      em "Fechou" ha 5 dias sem mandar nada             -> vai para "Ligar: reaquecer" e avisa a equipe
  Jose      contrato no ZapSign ha 2 dias, nao assinou        -> assinatura, toque 1
  Antonio   assinou ontem a noite                             -> agradece, avisa, move o card; a cobranca de
                                                                 documentos espera o dia seguinte (1 msg/dia)
  Sebastiana assinou ha 3 dias; disse que nao consegue extrato -> documentos sem o extrato (e equipe avisada)
  Benedito  notificacao ao banco enviada ontem                -> aviso ao cliente
  Joana     todos os documentos na pasta                      -> documentos completos
"""
import json
import os
import tempfile
from datetime import date, datetime, timedelta

from config import fluxos as CFG
from FLUXOS import fluxos_clientes
from FLUXOS.crm import CRMExemplo
from FLUXOS.main import rodar
from FLUXOS.nucleo import Contexto, chave

E = CFG.ETAPAS


def _st(id_, nome, situacao, obrig=True, sensivel=False):
    return {'id': id_, 'nome': nome, 'situacao': situacao, 'obrigatorio': obrig, 'sensivel': sensivel}


def dados(hoje, momento):
    d = lambda n: (hoje - timedelta(days=n)).isoformat()  # noqa: E731
    h = lambda dias, hora: datetime.combine(hoje - timedelta(days=dias), datetime.min.time()) + timedelta(hours=hora)  # noqa: E731
    cards = [
        {'id': 'c1', 'nome': 'João da Silva', 'telefone': '69 99911-0001', 'etapa': E['lead_quente']},
        {'id': 'c2', 'nome': 'Pedro Alves', 'telefone': '69 99911-0002', 'etapa': E['lead_quente']},
        {'id': 'c3', 'nome': 'Maria Souza', 'telefone': '69 99911-0003', 'etapa': E['pos_reuniao']},
        {'id': 'c4', 'nome': 'Ana Lima', 'telefone': '69 99911-0004', 'etapa': E['nao_agora']},
        {'id': 'c5', 'nome': 'Carlos Rocha', 'telefone': '69 99911-0005', 'etapa': E['lead_novo']},
        {'id': 'c6', 'nome': 'Rosa Martins', 'telefone': '69 99911-0006', 'etapa': E['fechou']},
        {'id': 'c7', 'nome': 'Luiz Pereira', 'telefone': '69 99911-0007', 'etapa': E['fechou']},
        {'id': 'c8', 'nome': 'Antônio Ferreira', 'telefone': '69 99911-0009', 'etapa': E['contrato_enviado']},
    ]
    desde = {'c1': 0, 'c2': 1, 'c3': 2, 'c4': 61, 'c5': 0, 'c6': 0, 'c7': 5, 'c8': 1}
    msgs = {
        chave('69 99911-0002'): [{'quem': 'cliente', 'tipo': 'text', 'texto': 'já tenho advogado cuidando disso',
                                  'quando': h(1, 15)}],
        chave('69 99911-0005'): [{'quem': 'cliente', 'tipo': 'text', 'quando': momento - timedelta(hours=1),
                                  'texto': 'o banco marcou o leilão da minha terra pra semana que vem'}],
        chave('69 99911-0011'): [{'quem': 'cliente', 'tipo': 'text', 'quando': h(1, 9),
                                  'texto': 'o extrato eu não consigo tirar, não tenho o aplicativo do banco'}],
    }
    pessoas = {
        chave('69 99911-0002'): {'nome': 'Pedro Alves', 'telefone': '69 99911-0002', 'fluxos': {'quentes': {
            'inicio': d(1), 'encerrado': False, 'toques': [{'data': d(1), 'toque': 1, 'quando': h(1, 10).isoformat()}]}}},
        chave('69 99911-0003'): {'nome': 'Maria Souza', 'telefone': '69 99911-0003', 'fluxos': {'fechamento': {
            'inicio': d(2), 'encerrado': False, 'toques': [{'data': d(2), 'toque': 1, 'quando': h(2, 10).isoformat()},
                                                           {'data': d(1), 'toque': 2, 'quando': h(1, 10).isoformat()}]}}},
        chave('69 99911-0007'): {'nome': 'Luiz Pereira', 'telefone': '69 99911-0007', 'fluxos': {'boas_vindas': {
            'inicio': d(5), 'encerrado': False, 'toques': [{'data': d(5 - i), 'toque': i + 1} for i in range(5)]}}},
    }
    status_completo = [_st(i, i, 'NA PASTA') for i in ('pessoais', 'endereco', 'contratos', 'extratos', 'pagamentos',
                                                         'matricula', 'fiscal')] + \
        [_st('govbr', 'Senha GOV.BR', 'NAO FALADO', sensivel=True), _st('frustracao', 'Frustração', 'NAO FALADO', False)]
    casos = [
        {'qualificacao': {'nome': 'José Batista', 'telefone': '69 99911-0008'}, 'enviado_em': d(2),
         'zapsign': [{'documento': 'Contrato', 'status': 'pendente'}]},
        {'qualificacao': {'nome': 'Antônio Ferreira', 'telefone': '69 99911-0009'}, 'enviado_em': d(1),
         'zapsign': [{'documento': 'Contrato', 'status': 'pendente'}], '_vai_assinar': True,
         '_status': [_st('contratos', 'Contratos', 'VAI ENVIAR')], 'triagem': {}},
        {'qualificacao': {'nome': 'Sebastiana Cruz', 'telefone': '69 99911-0011'}, 'assinado_em': d(3), 'triagem': {},
         'zapsign': [{'status': 'assinado'}], '_status': [
             _st('pessoais', 'Documentos pessoais', 'NA PASTA'), _st('endereco', 'Comprovante de endereço', 'NA PASTA'),
             _st('contratos', 'Contratos e cédulas', 'VAI ENVIAR'), _st('extratos', 'Extratos', 'NAO FALADO'),
             _st('pagamentos', 'Comprovantes de pagamento', 'JA ENTREGOU'), _st('matricula', 'Matrícula', 'NAO TEM'),
             _st('fiscal', 'Notas fiscais', 'NAO FALADO'), _st('frustracao', 'Frustração de safra', 'NAO FALADO', False),
             _st('govbr', 'Senha GOV.BR', 'NAO FALADO', sensivel=True)]},
        {'qualificacao': {'nome': 'Benedito Santos', 'telefone': '69 99911-0012'}, 'assinado_em': d(30),
         'etapa': 'DOCUMENTOS COMPLETOS', 'extrajudicial': {'notificacoes': [{'banco': 'Banco do Brasil', 'enviada_em': d(1)}]}},
        {'qualificacao': {'nome': 'Joana Prado', 'telefone': '69 99911-0013'}, 'assinado_em': d(6), 'triagem': {},
         'zapsign': [{'status': 'assinado'}], '_status': status_completo},
    ]
    estado = {'semeado_em': d(90), 'avisos_semeados_em': d(90), 'avisos': {}, 'pessoas': pessoas,
              'cards': {c['id']: {'etapa': c['etapa'], 'desde': d(desde[c['id']]), 'semente': False} for c in cards}}
    return cards, msgs, casos, estado


def rodar_exemplo():
    hoje = date.today()
    while hoje.weekday() >= 5:            # roda num dia de semana, para o horario comercial valer
        hoje -= timedelta(days=1)
    momento = datetime.combine(hoje, datetime.min.time()) + timedelta(hours=10)
    cards, msgs, casos, estado = dados(hoje, momento)
    pasta = tempfile.mkdtemp(prefix='fluxos_exemplo_')
    with open(os.path.join(pasta, 'estado.json'), 'w', encoding='utf-8') as f:
        json.dump(estado, f, ensure_ascii=False)
    crm = CRMExemplo(cards, msgs)
    ctx = Contexto(crm, enviar=True, pasta=pasta, hoje=hoje, momento=momento)
    rodar(ctx, fluxos_clientes.CasosExemplo(casos))
    print(f'\nEXEMPLO: {len(crm.enviados)} mensagens "enviadas" (nada saiu da máquina). Cards no fim:')
    for c in cards:
        print(f"   {c['nome']:18} {c['etapa']}")
    print(f'Estado do exemplo em: {pasta}')
    return 0
