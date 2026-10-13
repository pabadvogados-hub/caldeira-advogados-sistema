"""
MARKETING - Caldeira Advogados Associados

Conteudo (Instagram, sem agencia):
    python MARKETING/main.py calendario --mes 10/2026          calendario editorial do mes
    python MARKETING/main.py post --tema "..." --formato carrossel --arte
    python MARKETING/main.py conferir texto.txt                 checagem do Provimento 205/2021
    python MARKETING/main.py concorrentes anuncios.txt          angulos dos concorrentes + variacoes eticas
    python MARKETING/main.py ideias --quantidade 20             banco de pautas
    python MARKETING/main.py agro --mes 7                       ganchos do calendario do produtor

Trafego pago e funil (Meta):
    python MARKETING/main.py plano --orcamento-mensal 3000      campanha por regiao (radar de credito rural)
    python MARKETING/main.py criativos --dias 7                 escalar / manter / pausar / trocar criativo
    python MARKETING/main.py acoes [--aplicar]                  so executa com confirmacao item a item
    python MARKETING/main.py funil --mes 09/2026                gasto -> leads -> reunioes -> contratos (CAC, ROI)
    python MARKETING/main.py landing --whatsapp 5569...         pagina de captacao
    python MARKETING/main.py utm --campanha X --conjunto Y --anuncio Z

Copia e replicacao de campanhas (Meta):
    python MARKETING/main.py backup [--videos]                  copia TUDO da conta + mapa completo (so leitura)
    python MARKETING/main.py replicar --campanha <id|nome> [--ia] [--aplicar]
                                                                recria a campanha corrigida; nasce PAUSADA

Nada e publicado nem alterado na conta de anuncios sem ordem humana.
Detalhes: docs/POP_MARKETING_CONTEUDO.md, docs/POP_MARKETING_TRAFEGO.md, docs/GUIA_MONITOR_CAMPANHAS.md
"""
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

CONTEUDO = {'calendario', 'post', 'conferir', 'concorrentes', 'ideias', 'agro'}
TRAFEGO = {'plano', 'criativos', 'acoes', 'funil', 'landing', 'utm'}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'ajuda'):
        print(__doc__)
        return 0
    comando = argv[0]
    if comando in CONTEUDO:
        import conteudo
        retorno = conteudo.main(argv)
    elif comando in TRAFEGO:
        import trafego
        retorno = trafego.main(argv)
    elif comando == 'backup':
        import meta_backup
        retorno = meta_backup.main(argv)
    elif comando == 'replicar':
        import meta_replicar
        retorno = meta_replicar.main(argv[1:])
    else:
        print(f'Comando desconhecido: {comando}\n{__doc__}')
        return 1
    # os modulos devolvem ora codigo de saida (0 ok, 2 = conteudo bloqueado), ora o resultado (caminho, lista)
    return retorno if isinstance(retorno, int) else 0


if __name__ == '__main__':
    sys.exit(main())
