import asyncpg
from .config import settings

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    assert _pool is not None, "DB pool not initialized"
    return _pool


#: Colunas já conferidas. O schema não muda enquanto o processo vive, e sem o
#: cache cada divisão de grupos iria ao `information_schema` à toa.
_COLUNAS: dict[tuple[str, str], bool] = {}


async def tem_coluna(tabela: str, coluna: str) -> bool:
    """A coluna existe no banco AGORA?

    Publicar a videoconference **não aplica migration**: o `publish.ps1` manda o
    fonte e rebuilda o container, e o `schema.sql` montado em
    `docker-entrypoint-initdb.d` só roda com o diretório de dados vazio. Existe,
    portanto, uma janela em que o código novo conversa com o schema antigo — e
    já custou caro uma vez: na 018, o botão verde do host passou a escrever
    cinco colunas que ainda não existiam e virou 500 no meio da aula.

    A regra que saiu dali: funcionalidade nova pode nascer inerte, mas não pode
    levar embora a antiga. Quem escreve coluna nova em caminho que já existia
    pergunta aqui primeiro.
    """
    chave = (tabela, coluna)
    if chave not in _COLUNAS:
        _COLUNAS[chave] = bool(await pool().fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=$1 AND column_name=$2", tabela, coluna))
    return _COLUNAS[chave]


_TABELAS: dict[str, bool] = {}


async def tem_tabela(tabela: str) -> bool:
    """A tabela existe no banco AGORA? Mesma razao de `tem_coluna`.

    Publicar nao aplica migration, entao todo caminho que ja existia e passou a
    gravar numa tabela NOVA pergunta aqui antes -- senao a funcionalidade nova
    leva a antiga junto na janela entre o deploy e o `.sql`.
    """
    if tabela not in _TABELAS:
        _TABELAS[tabela] = bool(await pool().fetchval(
            "SELECT 1 FROM information_schema.tables WHERE table_name=$1", tabela))
    return _TABELAS[tabela]
