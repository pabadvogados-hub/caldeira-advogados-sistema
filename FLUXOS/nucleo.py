"""
Nucleo dos fluxos: estado, travas, envio e aviso a equipe. Todos os fluxos passam por aqui.

Travas que valem para TODOS os fluxos (cada uma veio de um erro real em producao):
  - simulacao e o padrao: sem --enviar nada sai e nada e gravado como enviado;
  - no maximo 1 mensagem por pessoa por dia, somando todos os fluxos (a pessoa e o TELEFONE,
    pelos 8 ultimos digitos: o mesmo cliente ja apareceu duas vezes com o nome escrito diferente);
  - so de segunda a sabado, das 8h as 20h; no maximo MAX_ENVIOS_POR_RODADA por rodada;
  - se alguem da equipe escreveu para a pessoa nas ultimas 12h, o robo nao manda (a conversa e humana);
  - `parar --telefone` encerra a pessoa em TODOS os fluxos de uma vez;
  - aviso a equipe sobre o mesmo assunto no maximo a cada 3 dias.
Estado em SAIDA/fluxos/estado.json; cada acao em SAIDA/fluxos/eventos.jsonl.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'NUCLEO'))
import ambiente  # noqa: E402  (carrega .env e caminhos)

from config import fluxos as CFG  # noqa: E402

AVISO_A_CADA_DIAS = 3


def digitos(tel):
    return ''.join(c for c in str(tel or '') if c.isdigit())


def chave(tel):
    d = digitos(tel)
    return d[-8:] if len(d) >= 8 else ''


def agora():
    return datetime.now()


class Contexto:
    def __init__(self, crm, enviar=False, pasta=None, hoje=None, momento=None):
        self.crm = crm
        self.enviar = enviar
        self.hoje = hoje or date.today()
        self.momento = momento or agora()
        self.pasta = pasta or ambiente.pasta_saida('fluxos')
        self.caminho = os.path.join(self.pasta, 'estado.json')
        self.estado = self._ler()
        self.enviados_rodada = 0
        self.resumo = []

    # ---------------------------------------------------------- estado
    def _ler(self):
        if os.path.exists(self.caminho):
            with open(self.caminho, encoding='utf-8') as f:
                return json.load(f)
        return {'cards': {}, 'semeado_em': None, 'pessoas': {}, 'avisos': {}}

    def salvar(self):
        with open(self.caminho, 'w', encoding='utf-8') as f:
            json.dump(self.estado, f, ensure_ascii=False, indent=1)

    def evento(self, tipo, pessoa, texto, **extra):
        linha = {'quando': self.momento.isoformat(timespec='seconds'), 'modo': 'ENVIO' if self.enviar else 'SIMULACAO',
                 'tipo': tipo, 'nome': pessoa.get('nome'), 'telefone': pessoa.get('telefone'), 'texto': texto, **extra}
        self.resumo.append(linha)
        with open(os.path.join(self.pasta, 'eventos.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps(linha, ensure_ascii=False) + '\n')

    def pessoa(self, telefone, nome=''):
        k = chave(telefone)
        if not k:
            return None
        p = self.estado['pessoas'].setdefault(k, {'nome': nome, 'telefone': telefone, 'fluxos': {}})
        if nome and not p.get('nome'):
            p['nome'] = nome
        if telefone and not p.get('telefone'):
            p['telefone'] = telefone
        return p

    def fluxo(self, pessoa, nome, inicio=None, reiniciar_se_mudou=False):
        """Estado do fluxo da pessoa. reiniciar_se_mudou: o card entrou de novo na etapa -> ciclo novo."""
        ini = inicio or self.hoje
        ini = ini.isoformat() if isinstance(ini, date) else str(ini)
        f = pessoa['fluxos'].get(nome)
        if f is None or (reiniciar_se_mudou and f.get('inicio') != ini):
            f = pessoa['fluxos'][nome] = {'inicio': ini, 'toques': [], 'encerrado': False}
        return f

    def encerrar(self, pessoa, nome_fluxo, motivo):
        f = self.fluxo(pessoa, nome_fluxo)
        if not f.get('encerrado'):
            f['encerrado'], f['motivo'], f['encerrado_em'] = True, motivo, self.hoje.isoformat()
            self.evento('encerrado', pessoa, motivo, fluxo=nome_fluxo)
            print(f"   [{nome_fluxo}] {pessoa.get('nome')}: encerrado ({motivo})")

    # ---------------------------------------------------------- travas
    def pode_mandar(self, pessoa):
        """(ok, motivo). Vale para todo envio ao cliente/lead."""
        if pessoa.get('parado'):
            return False, f"parado manualmente ({pessoa.get('parado_motivo', '')})"
        hi, hf = CFG.HORARIO
        if self.momento.weekday() >= CFG.DIAS_DA_SEMANA or not (hi <= self.momento.hour < hf):
            return False, 'fora do horário (seg a sáb, 8h às 20h)'
        if pessoa.get('ultimo_envio') == self.hoje.isoformat():
            return False, 'já recebeu mensagem hoje'
        if self.enviados_rodada >= CFG.MAX_ENVIOS_POR_RODADA:
            return False, f'limite de {CFG.MAX_ENVIOS_POR_RODADA} envios por rodada'
        try:
            if self.crm.equipe_escreveu_desde(pessoa.get('telefone'), self.momento - timedelta(
                    hours=CFG.HORAS_SILENCIO_SE_EQUIPE_ESCREVEU)):
                return False, 'alguém da equipe falou com a pessoa nas últimas 12h'
        except Exception as e:  # noqa: BLE001 - sem leitura da conversa, segue (o resto das travas vale)
            print(f'   (não consegui ler a conversa: {str(e)[:80]})')
        return True, ''

    # ---------------------------------------------------------- envio
    def mandar(self, pessoa, nome_fluxo, texto, toque=None):
        """Manda (ou simula). Devolve True so quando enviou de verdade."""
        ok, motivo = self.pode_mandar(pessoa)
        rotulo = f"[{nome_fluxo}]{f' toque {toque}' if toque else ''} {pessoa.get('nome')} ({pessoa.get('telefone')})"
        if not ok:
            print(f'   {rotulo}: não enviado - {motivo}')
            return False
        print(f'   {rotulo}:\n      ' + texto.replace('\n', '\n      '))
        if not self.enviar:
            print('      (simulação: não enviado)')
            self.evento('simulado', pessoa, texto, fluxo=nome_fluxo, toque=toque)
            return False
        enviado, detalhe = self.crm.enviar(pessoa.get('telefone'), texto)
        print(f'      {"ENVIADO" if enviado else "NÃO ENVIADO"} ({detalhe})')
        self.evento('enviado' if enviado else 'falha', pessoa, texto, fluxo=nome_fluxo, toque=toque, detalhe=detalhe)
        if enviado:
            pessoa['ultimo_envio'] = self.hoje.isoformat()
            self.enviados_rodada += 1
            if toque:
                self.fluxo(pessoa, nome_fluxo)['toques'].append({'data': self.hoje.isoformat(), 'toque': toque,
                                                                 'quando': self.momento.isoformat(timespec='seconds')})
        return enviado

    def avisar_equipe(self, pessoa, assunto, texto):
        """Aviso interno (WhatsApp da equipe), no maximo a cada 3 dias por pessoa+assunto."""
        k = f"{chave(pessoa.get('telefone')) or pessoa.get('nome')}:{assunto}"
        ultimo = self.estado['avisos'].get(k)
        if ultimo and (self.hoje - date.fromisoformat(ultimo)).days < AVISO_A_CADA_DIAS:
            return False
        from FLUXOS import textos
        msg = textos.equipe(pessoa.get('nome'), pessoa.get('telefone'), texto)
        print(f'   >> EQUIPE: {msg}')
        self.evento('aviso_equipe', pessoa, texto, assunto=assunto)
        if not self.enviar:
            return False
        destino = os.getenv('FLUXOS_TEL_EQUIPE') or os.getenv('ALERTA_WHATSAPP')
        if destino:
            enviado, _ = self.crm.enviar(destino, msg)
            if enviado:
                self.estado['avisos'][k] = self.hoje.isoformat()
            return enviado
        self.estado['avisos'][k] = self.hoje.isoformat()   # sem telefone da equipe: fica no log e no resumo
        return False

    def mover(self, card, papel):
        """Move o card para a etapa do papel, so para frente na ORDEM (ou para uma etapa de saida)."""
        if not card or papel not in CFG.ETAPAS:
            return False
        destino = CFG.ETAPAS[papel]
        atual = card.get('papel')
        if atual == papel:
            return False
        if papel not in CFG.SAIDAS and atual in CFG.ORDEM and CFG.ORDEM.index(papel) <= CFG.ORDEM.index(atual):
            print(f"   (não movo {card.get('nome')} para trás: {card.get('etapa')} -> {destino})")
            return False
        print(f"   MOVER {card.get('nome')}: {card.get('etapa')} -> {destino}" + ('' if self.enviar else ' (simulação)'))
        if not self.enviar:
            return False
        ok = self.crm.mover(card, papel)
        if ok:
            card['papel'], card['etapa'] = papel, destino
        return ok
