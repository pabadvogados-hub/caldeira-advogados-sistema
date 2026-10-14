"""
Fluxos de CLIENTE (do "fechou" em diante). Leem o caso do cliente (caso.json da pasta, gravado pelo
CONTRATACAO) e o funil do Atende Direito.

  boas_vindas   card em "Fechou": boas-vindas + pedido de CNH/RG e comprovante de endereco (ou endereco escrito).
                Lembrete 1x por dia (nunca no mesmo dia do pedido). Chegou foto/arquivo ou endereco: para e avisa
                a equipe. 5 dias sem nada: card vai para "Ligar: reaquecer" e a equipe liga.
  assinatura    contrato enviado ao ZapSign e nao assinado: confere o ZapSign a cada rodada; D+1 a D+6 uma mensagem
                por dia; D+7 passa para a equipe. Assinou: agradece, avisa a equipe e move o card para "Assinado".
  documentos    depois da assinatura: cobra so o que o CASO precisa (regras_documentos.py); a cada 2 dias, ate 5
                toques; completo: agradece, marca o caso e move o card para "Documentos Completos".
  avisos_fase   avisa o cliente UMA vez quando a notificacao ao banco sai e quando a acao e protocolada.
"""
import re
from datetime import date, datetime

import ambiente
from FLUXOS import regras_documentos as R
from FLUXOS import textos

CEP = re.compile(r'\b\d{5}-?\d{3}\b')
MIDIA = {'image', 'document', 'video', 'file', 'imagem', 'documento', 'pdf'}


# ============================================================
# DE ONDE VEM OS CASOS
# ============================================================

class CasosSistema:
    """Casos reais: pastas dos clientes (CONTRATACAO)."""

    def listar(self):
        from CONTRATACAO.pasta_cliente import listar_casos
        return listar_casos()

    def status_documentos(self, base, caso):
        if not caso.get('triagem'):
            return None
        from CONTRATACAO.pasta_cliente import arquivos_por_item
        from CONTRATACAO.relatorio_triagem import status_documentos
        return status_documentos(caso['triagem'], arquivos_por_item(base))

    def pode_checar_assinatura(self):
        return ambiente.tem_credencial('ZAPSIGN_API_TOKEN')

    def checar_assinaturas(self, base, caso):
        from CONTRATACAO.acompanhamento import assinaturas
        return assinaturas(base, caso)

    def salvar(self, base, caso, enviar):
        if enviar:
            from CONTRATACAO.pasta_cliente import salvar_caso
            salvar_caso(base, caso)


class CasosExemplo:
    def __init__(self, casos):
        self._casos = casos

    def listar(self):
        return [(None, c) for c in self._casos]

    def status_documentos(self, base, caso):
        return caso.get('_status')

    def pode_checar_assinatura(self):
        return True

    def checar_assinaturas(self, base, caso):
        if caso.get('_vai_assinar'):
            for l in caso.get('zapsign') or []:
                l['status'] = 'assinado'
            caso['assinado_em'] = date.today().isoformat()
            return True
        return False

    def salvar(self, base, caso, enviar):
        pass


def _q(caso):
    q = caso.get('qualificacao') or {}
    return q.get('nome', ''), q.get('telefone', '')


# ============================================================
# BOAS-VINDAS (card em "fechou")
# ============================================================

def boas_vindas(ctx, cards):
    for card in cards:
        if card['papel'] != 'fechou' or card['semente']:
            continue
        pessoa = ctx.pessoa(card['telefone'], card['nome'])
        if not pessoa:
            continue
        f = ctx.fluxo(pessoa, 'boas_vindas', inicio=card['desde'], reiniciar_se_mudou=True)
        if f['encerrado']:
            continue
        inicio = datetime.combine(card['desde'], datetime.min.time())
        recebidos = [m for m in ctx.crm.mensagens(card['telefone']) if m['quem'] == 'cliente' and m['quando']
                     and m['quando'] >= inicio and ((m['tipo'] or '').lower() in MIDIA or CEP.search(m['texto'] or ''))]
        if recebidos:
            ctx.encerrar(pessoa, 'boas_vindas', 'cliente mandou documento/endereço')
            ctx.avisar_equipe(pessoa, 'docs_contrato', 'chegaram documentos/endereço para o contrato: conferir e gerar')
            continue
        if not f['toques']:
            ctx.mandar(pessoa, 'boas_vindas', textos.boas_vindas(card['nome']), toque=1)
            continue
        dias = (ctx.hoje - card['desde']).days
        if dias >= 5:
            ctx.mover(card, 'ligar_reaquecer')
            ctx.avisar_equipe(pessoa, 'docs_contrato_5d', '5 dias sem documentos para o contrato: LIGAR')
            ctx.encerrar(pessoa, 'boas_vindas', '5 dias sem documentos (passou para ligação)')
            continue
        n = len(f['toques'])           # ja mandou o pedido + (n-1) lembretes
        if n <= 4 and dias >= n and f['toques'][-1]['data'] != ctx.hoje.isoformat():
            ctx.mandar(pessoa, 'boas_vindas', textos.lembrete_docs_contrato(n, card['nome']), toque=n + 1)


# ============================================================
# ASSINATURA (ZapSign)
# ============================================================

def assinatura(ctx, casos):
    for base, caso in casos.listar():
        links = caso.get('zapsign') or []
        if not links or caso.get('assinado_em') or caso.get('etapa') == 'ENCERRADO' or not caso.get('enviado_em'):
            continue
        nome, tel = _q(caso)
        pessoa = ctx.pessoa(tel, nome)
        if not pessoa:
            continue
        f = ctx.fluxo(pessoa, 'assinatura', inicio=caso['enviado_em'])
        if f['encerrado']:
            continue
        if not casos.pode_checar_assinatura():
            print(f'   [assinatura] {nome}: sem ZAPSIGN_API_TOKEN, não dá para saber se assinou: não cobro')
            continue
        casos.checar_assinaturas(base, caso)
        if caso.get('assinado_em'):
            casos.salvar(base, caso, ctx.enviar)
            ctx.encerrar(pessoa, 'assinatura', 'assinou')
            ctx.mandar(pessoa, 'assinatura', textos.assinou(nome))
            ctx.avisar_equipe(pessoa, 'assinou', 'assinou o contrato e a procuração')
            ctx.mover(ctx.card_por_telefone(tel), 'assinado')
            continue
        dias = (ctx.hoje - date.fromisoformat(caso['enviado_em'])).days
        n = len(f['toques']) + 1
        if dias >= 7:
            ctx.avisar_equipe(pessoa, 'assinatura_7d', '7 dias sem assinar: ligar e assinar junto com o cliente')
            ctx.encerrar(pessoa, 'assinatura', '7 dias sem assinar (passou para a equipe)')
        elif 1 <= dias and n <= 6 and n <= dias:
            ctx.mandar(pessoa, 'assinatura', textos.assinatura(n, nome), toque=n)


# ============================================================
# DOCUMENTOS DO CASO
# ============================================================

def documentos(ctx, casos):
    for base, caso in casos.listar():
        if not caso.get('assinado_em'):
            continue
        nome, tel = _q(caso)
        pessoa = ctx.pessoa(tel, nome)
        if not pessoa:
            continue
        novo = 'documentos' not in pessoa['fluxos']
        f = ctx.fluxo(pessoa, 'documentos', inicio=caso['assinado_em'])
        if novo:   # o robo antigo do CONTRATACAO ja cobrou? continua a contagem de onde parou
            f['toques'] = [{'data': t['data'], 'toque': t['toque'], 'origem': 'CONTRATACAO'}
                           for t in caso.get('toques_documentos') or [] if t.get('enviado')]
        if f['encerrado']:
            continue
        motivo = R.caso_encerrado(caso)
        if motivo:
            ctx.encerrar(pessoa, 'documentos', motivo)
            continue
        status = casos.status_documentos(base, caso)
        if status is None:
            ctx.avisar_equipe(pessoa, 'sem_triagem', 'sem a análise da reunião (triagem) não cobro documento às cegas: '
                              'gerar o Relatório de Triagem do caso')
            continue
        cobrar, para_equipe, _fora = R.lista_do_caso(status, tem_zapsign=bool(caso.get('zapsign')))
        for item in para_equipe:
            ctx.avisar_equipe(pessoa, 'doc:' + item[:25], item)
        falas = [m['texto'] for m in ctx.crm.mensagens(tel) if m['quem'] == 'cliente' and m['texto']]
        cobrar, tirados = R.podar_pelo_que_disse(cobrar, falas)
        if tirados:
            f.setdefault('podados', [])
            novos = [s['id'] for s, _ in tirados if s['id'] not in f['podados']]
            if novos:
                f['podados'] += novos
                ctx.avisar_equipe(pessoa, 'podados', 'tirei da cobrança o que o cliente disse que não tem: ' +
                                  '; '.join(f'{s["nome"]} ("{frase[:80]}")' for s, frase in tirados) +
                                  '. Se precisar de prova substituta, combinar com ele.')
        if not cobrar:
            na_pasta = all(s['situacao'] == R.NA_PASTA or not s.get('obrigatorio') or s.get('sensivel')
                           or (s['id'] == 'procuracao' and caso.get('zapsign')) for s in status)
            if na_pasta:
                if not caso.get('documentos_completos_em'):
                    caso['documentos_completos_em'], caso['etapa'] = ctx.hoje.isoformat(), 'DOCUMENTOS COMPLETOS'
                    casos.salvar(base, caso, ctx.enviar)
                agradeceu = ctx.mandar(pessoa, 'documentos', textos.documentos_completos(nome))
                ctx.mover(ctx.card_por_telefone(tel), 'documentos_completos')
                ctx.avisar_equipe(pessoa, 'docs_completos', 'documentos completos: caso pronto para a notificação')
                if agradeceu or not ctx.enviar:      # sem envio hoje (limite/horario): agradece na proxima rodada
                    ctx.encerrar(pessoa, 'documentos', 'documentos completos')
            else:
                ctx.avisar_equipe(pessoa, 'docs_nada_a_cobrar', 'o que falta o cliente disse que não tem ou a equipe '
                                  'resolve: seguir com o que tem')
                ctx.encerrar(pessoa, 'documentos', 'nada mais a cobrar do cliente')
            continue
        n, motivo = R.proximo_toque(f, ctx.hoje)
        if n is None:
            if motivo.startswith('já foram'):
                ctx.avisar_equipe(pessoa, 'docs_regua', f'{R.MAX_TOQUES} cobranças sem completar os documentos: ligar')
                ctx.encerrar(pessoa, 'documentos', motivo)
            continue
        ctx.mandar(pessoa, 'documentos', textos.documentos(n, nome, cobrar), toque=n)


# ============================================================
# AVISOS DE FASE
# ============================================================

def _protocolada(caso):
    j = caso.get('judicial') or {}
    etapa = (caso.get('etapa') or '').upper()
    return bool(j.get('protocolado_em') or j.get('numero_processo') or 'PROTOCOL' in etapa or 'DISTRIBU' in etapa)


def avisos_fase(ctx, casos):
    primeira_rodada = ctx.estado.get('avisos_semeados_em', ctx.hoje.isoformat()) == ctx.hoje.isoformat()
    ctx.estado.setdefault('avisos_semeados_em', ctx.hoje.isoformat())
    for base, caso in casos.listar():
        nome, tel = _q(caso)
        pessoa = ctx.pessoa(tel, nome)
        if not pessoa:
            continue
        f = ctx.fluxo(pessoa, 'avisos_fase')
        feitos = f.setdefault('feitos', [])
        notifs = [n for n in (caso.get('extrajudicial') or {}).get('notificacoes') or [] if n.get('enviada_em')]
        eventos = []
        if notifs and 'notificacao' not in feitos:
            bancos = sorted({n.get('banco') for n in notifs if n.get('banco')})
            eventos.append(('notificacao', textos.aviso_notificacao(nome, bancos)))
        if _protocolada(caso) and 'protocolo' not in feitos:
            eventos.append(('protocolo', textos.aviso_protocolo(nome)))
        for chave_evento, texto in eventos:
            if primeira_rodada:        # o que ja tinha acontecido antes de ligar o sistema nao vira aviso
                feitos.append(chave_evento)
                continue
            if ctx.mandar(pessoa, 'avisos_fase', texto):
                feitos.append(chave_evento)
            break                      # no maximo 1 aviso por rodada (e 1 mensagem por dia)
