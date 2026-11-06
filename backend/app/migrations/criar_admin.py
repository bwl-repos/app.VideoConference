# -*- coding: utf-8 -*-
"""Cria (ou redefine a senha de) uma conta do painel administrativo.

    DATABASE_URL=postgres://... python criar_admin.py <email> "<Nome>"
    DATABASE_URL=postgres://... python criar_admin.py <email> "<Nome>" --superadmin
    DATABASE_URL=postgres://... python criar_admin.py <email> --resetar

POR QUE ISTO E UM SCRIPT, E NAO UMA ROTA
----------------------------------------
Nao ha nenhuma rota que crie conta de admin -- nem para o superadmin. E a
ausencia e deliberada: uma rota que cria admin e uma rota que, se vazar, cria
acesso total ao painel de todas as licencas. O custo dessa decisao e este
arquivo: abrir conta para alguem exige acesso ao banco, que e o que se quer.

`seed_admin.py` faz o mesmo para UM e-mail fixo, e so na primeira vez
(`ON CONFLICT DO NOTHING`). Este aqui serve para quem chegou depois, e para o
caso em que a senha sorteada na criacao se perdeu -- que nao tem outra saida,
porque o banco guarda so o hash bcrypt.

A SENHA E SORTEADA AQUI E IMPRESSA UMA VEZ
------------------------------------------
Nao se escolhe senha por parametro: ela ficaria no historico do shell. O script
sorteia, grava o hash e imprime o valor uma unica vez -- copie na hora. Perdeu,
roda de novo com `--resetar`.

Quem recebe a conta deve trocar a senha no proprio painel (botao "Trocar
senha"), que e a unica forma de a senha passar a ser conhecida so por ela.
"""
from __future__ import annotations

import asyncio
import os
import secrets
import sys

import asyncpg
import bcrypt

USO = __doc__.split("POR QUE")[0].strip()


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sinal = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(USO)
        return 2

    email = args[0].strip().lower()
    resetar = "--resetar" in sinal
    nome = args[1] if len(args) > 1 else email.split("@")[0]
    # `admin` por padrao, e nao `superadmin`: so o superadmin mexe em planos e
    # licencas, e dar o nivel maximo por omissao e o jeito classico de todo
    # mundo acabar com ele.
    papel = "superadmin" if "--superadmin" in sinal else "admin"

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[ERRO] defina DATABASE_URL (o banco da webconf).")
        return 2

    senha = secrets.token_urlsafe(12)
    hash_ = bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()

    conn = await asyncpg.connect(url)
    try:
        existente = await conn.fetchrow(
            "SELECT id, name, role, status FROM admin_users WHERE lower(email)=lower($1)",
            email)
        if existente and not resetar:
            print(f"[JA EXISTE] {email} ({existente['name']}, {existente['role']}, "
                  f"{existente['status']}).")
            print("            Para trocar a senha desta conta, rode de novo com --resetar.")
            return 1
        if existente:
            await conn.execute(
                "UPDATE admin_users SET password_hash=$2, status='active' WHERE id=$1",
                existente["id"], hash_)
            print(f"[SENHA REDEFINIDA] {email}")
        else:
            await conn.execute(
                "INSERT INTO admin_users (email, password_hash, name, role, status) "
                "VALUES ($1,$2,$3,$4,'active')",
                email, hash_, nome, papel)
            print(f"[CRIADA] {email} ({nome}, {papel})")
    finally:
        await conn.close()

    print()
    print(f"  senha: {senha}")
    print()
    print("  Aparece UMA vez. Entregue por um canal privado e peca para a pessoa")
    print("  troca-la no painel (Trocar senha) na primeira entrada.")
    return 0


raise SystemExit(asyncio.run(main()))
