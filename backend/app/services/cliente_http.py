"""Cliente HTTP de saída, com o contexto de TLS carregado uma vez só.

`httpx.AsyncClient()` recarrega os certificados a cada instância, e esse trabalho
bloqueia o event loop: medido em 368 ms por cliente no Windows, contra 0,1 ms
reaproveitando o contexto. Como o roster cria dois clientes por chamada, uma sala
cheia deixava o servidor inteiro travado recarregando certificados.

O contexto é o mesmo que o httpx montaria sozinho: a validação não muda.
"""
import httpx

_CONTEXTO_TLS = httpx.create_ssl_context()


def cliente_http(**opcoes) -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=_CONTEXTO_TLS, **opcoes)
