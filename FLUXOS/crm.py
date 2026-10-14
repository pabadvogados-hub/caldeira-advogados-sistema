"""
De onde os fluxos leem o funil e as conversas, e por onde mandam as mensagens.

CRMAtendeDireito: o funil e as conversas reais (Atende Direito FLOW API). Envio pela Flow API; sem ela,
pela API antiga (ATENDE_DIREITO_TOKEN), que so manda texto (os fluxos de funil ficam desligados).
CRMExemplo: dados ficticios em memoria (python FLUXOS/main.py exemplo). Nada sai da maquina.

Card = {'id', 'contato_id', 'nome', 'telefone', 'etapa', 'papel', 'atualizado_em'}
Mensagem = {'quem': 'cliente'|'equipe'|'robo'|'sistema', 'tipo', 'texto', 'quando' (datetime)}

[CONFERIR no 1o uso com a conta real] nomes dos campos do card/negocio na Flow API (contact, phone,
pipeline_stage_id). O adaptador tenta as variacoes conhecidas e avisa quando nao acha o telefone.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
import ambiente  # noqa: E402

from config import fluxos as CFG  # noqa: E402

QUEM = {'contact': 'cliente', 'agent': 'equipe', 'bot': 'robo', 'system': 'sistema'}


def _quando(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None


def papel_da_etapa(nome_etapa):
    alvo = (nome_etapa or '').strip().lower()
    return next((p for p, n in CFG.ETAPAS.items() if n.strip().lower() == alvo), None)


class CRMAtendeDireito:
    def __init__(self):
        import atendedireito_flow as flow
        self.flow = flow
        self.funil = os.getenv('ATENDE_DIREITO_FLOW_FUNIL')
        self._msgs = {}
        self._contatos = {}

    def funil_configurado(self):
        return self.flow.configurado() and bool(self.funil)

    def etapas_reais(self):
        return self.flow.etapas(self.funil) if self.funil_configurado() else {}

    def cards(self):
        if not self.funil_configurado():
            return []
        por_id = {v: k for k, v in self.flow.etapas(self.funil).items()}
        saida = []
        for b in self.flow.negocios_do_pipeline(self.funil):
            contato = b.get('contact') or {}
            if not contato and b.get('contact_id'):
                contato = self._contatos.get(b['contact_id']) or self.flow._data(
                    self.flow._req('GET', f"/api/flow/contacts/{b['contact_id']}")) or {}
                self._contatos[b['contact_id']] = contato
            etapa_id = b.get('pipeline_stage_id') or (b.get('stage') or {}).get('id')
            etapa = (b.get('stage') or {}).get('name') or por_id.get(etapa_id, '')
            saida.append({'id': b.get('id'), 'contato_id': contato.get('id') or b.get('contact_id'),
                          'nome': contato.get('name') or b.get('name') or '',
                          'telefone': contato.get('phone') or contato.get('phone_number') or '',
                          'etapa': etapa, 'papel': papel_da_etapa(etapa),
                          'atualizado_em': b.get('updated_at')})
        return saida

    def mensagens(self, telefone):
        k = ''.join(c for c in str(telefone or '') if c.isdigit())[-8:]
        if k in self._msgs:
            return self._msgs[k]
        saida = []
        if self.flow.configurado():
            c = self.flow.contato_por_telefone(telefone)
            for m in (self.flow.mensagens_do_contato(c.get('id')) if c else []):
                texto = m.get('content') or m.get('text') or m.get('body') or m.get('transcription') or ''
                if isinstance(texto, dict):
                    texto = texto.get('text') or texto.get('body') or ''
                saida.append({'quem': QUEM.get(m.get('sender_type'), m.get('sender_type')),
                              'tipo': m.get('message_type') or m.get('type') or 'text', 'texto': str(texto),
                              'quando': _quando(m.get('created_at') or m.get('sent_at'))})
        self._msgs[k] = saida
        return saida

    def equipe_escreveu_desde(self, telefone, desde):
        return any(m['quem'] == 'equipe' and m['quando'] and m['quando'] >= desde for m in self.mensagens(telefone))

    def enviar(self, telefone, texto):
        if self.flow.configurado():
            return self.flow.enviar_texto(telefone, texto)
        if ambiente.tem_credencial('ATENDE_DIREITO_TOKEN'):
            from atendedireito_integration import enviar_texto_por_telefone
            ok, _ = enviar_texto_por_telefone(telefone, texto)
            return ok, 'API antiga do Atende Direito'
        return False, 'sem credencial do Atende Direito no .env'

    def mover(self, card, papel):
        etapas = self.flow.etapas(self.funil)
        destino = etapas.get(CFG.ETAPAS[papel])
        if not destino:
            print(f'   etapa "{CFG.ETAPAS[papel]}" não existe no funil: card não movido')
            return False
        return self.flow.mover_negocio(card['id'], destino) is not None


class CRMExemplo:
    """Funil e conversas ficticios. Enviar so 'imprime'."""

    def __init__(self, cards, mensagens):
        self._cards = cards
        self._mensagens = mensagens
        self.enviados = []

    def funil_configurado(self):
        return True

    def etapas_reais(self):
        return {v: f'exemplo-{k}' for k, v in CFG.ETAPAS.items()}

    def cards(self):
        for c in self._cards:
            c['papel'] = papel_da_etapa(c['etapa'])
        return self._cards

    def mensagens(self, telefone):
        k = ''.join(c for c in str(telefone or '') if c.isdigit())[-8:]
        return self._mensagens.get(k, [])

    def equipe_escreveu_desde(self, telefone, desde):
        return any(m['quem'] == 'equipe' and m['quando'] >= desde for m in self.mensagens(telefone))

    def enviar(self, telefone, texto):
        self.enviados.append((telefone, texto))
        return True, 'exemplo (nada saiu da máquina)'

    def mover(self, card, papel):
        card['etapa'], card['papel'] = CFG.ETAPAS[papel], papel
        return True
