# -*- coding: utf-8 -*-
"""A prova da voz do encontro mede alguma coisa?

    python -B provas/falsifica_voz.py

Verde so vale se ficar vermelho quando o defeito volta. Cada estrago aqui e a
forma PLAUSIVEL do erro -- o que alguem escreveria de boa-fe. Nenhum deles daria
erro na tela: todos dariam uma sala que parece funcionar e fala errado, fala em
dobro, fala a secao errada ou paga a mesma sintese para sempre.

Os arquivos sao alterados no disco e restaurados no `finally`, inclusive se a
prova estourar. Nada fica modificado.
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
PROVA = RAIZ / "provas/prova_voz.py"

VOZ = RAIZ / "app/services/voz.py"
PORTA = RAIZ / "app/services/voz_porta.py"
ROOMS = RAIZ / "app/routers/rooms.py"
AULA = RAIZ / "app/routers/openpbl_class.py"
FRONT = RAIZ.parent / "frontend/src/components/video/VideoRoom.tsx"
#: A tela do roteiro saiu do VideoRoom para modulo proprio quando o painel admin
#: passou a mostrar o preview de cada etapa com os MESMOS componentes da aula.
ROTEIRO = RAIZ.parent / "frontend/src/components/video/RoteiroStage.tsx"
SDK = RAIZ.parent / "frontend/src/lib/video-rooms-sdk.ts"

#: (rotulo, arquivo, trecho original, trecho estragado)
ESTRAGOS = [
    # ── A chave ─────────────────────────────────────────────────────────────
    ("o texto deixa de ser normalizado antes do hash",
     VOZ,
     '    return re.sub(r"\\s+", " ", (texto or "").strip())',
     '    return (texto or "").strip()'),

    ("a chave perde a VERSAO (trocar a voz nao invalida nada)",
     VOZ,
     '        f"{VERSAO}|{perfil}|{normalizar(texto)}".encode("utf-8")).hexdigest()',
     '        f"{perfil}|{normalizar(texto)}".encode("utf-8")).hexdigest()'),

    # O defeito que a configuracao de voz criou: a chave do mp3 e o hash do
    # TEXTO, e o mesmo texto em duas vozes daria o mesmo endereco. Trocar a voz
    # no painel serviria o audio da voz velha para sempre, sem erro nenhum.
    ("a chave perde o PERFIL (trocar a voz serve o audio antigo)",
     VOZ,
     '        f"{VERSAO}|{perfil}|{normalizar(texto)}".encode("utf-8")).hexdigest()',
     '        f"{VERSAO}|{normalizar(texto)}".encode("utf-8")).hexdigest()'),

    ("a chave deixa de ir para o prefixo proprio",
     VOZ,
     '    return f"{PREFIXO}/{digest}.mp3"',
     '    return f"{digest}.mp3"'),

    # ── Quais paragrafos ────────────────────────────────────────────────────
    ("o mesmo aviso em duas secoes volta a ser duas sinteses",
     VOZ,
     '                limpo = normalizar(str(paragrafo or ""))\n'
     "                if limpo and limpo not in vistos:",
     '                limpo = normalizar(str(paragrafo or ""))\n'
     "                if limpo:"),

    ("os paragrafos saem sem normalizar (espacamento gera chave nova)",
     VOZ,
     '                limpo = normalizar(str(paragrafo or ""))\n'
     "                if limpo and limpo not in vistos:",
     '                limpo = str(paragrafo or "").strip()\n'
     "                if limpo and limpo not in vistos:"),

    # ── O ALINHAMENTO: o defeito que parece funcionar ───────────────────────
    ("o paragrafo vazio e descartado e desloca os indices",
     VOZ,
     '                if not limpo:\n                    audios.append("")\n                    continue',
     "                if not limpo:\n                    continue"),

    ("assinatura que falha passa a derrubar a sala",
     VOZ,
     "                try:\n"
     "                    audios.append(assinar(chave(limpo, perfil)))\n"
     "                except Exception:   # noqa: BLE001\n"
     '                    audios.append("")   # voz indisponível não pode quebrar a sala',
     "                audios.append(assinar(chave(limpo, perfil)))"),

    # ── O que se pede ───────────────────────────────────────────────────────
    ("deixa de conferir o bucket e pede tudo, sempre",
     VOZ,
     '            if tem(alvo):\n                contas["ja_tinha"] += 1\n                continue',
     "            pass"),

    ("o mesmo texto passa a ser pedido duas vezes na rodada",
     VOZ,
     "        if not limpo or limpo in feitos:\n            continue",
     "        if not limpo:\n            continue"),

    ("uma fala que falha passa a calar as seguintes",
     VOZ,
     '        except Exception as exc:   # noqa: BLE001\n'
     '            contas["falhas"] += 1\n'
     '            logger.error("[voz] %s: %s", alvo, exc)',
     "        except Exception:   # noqa: BLE001\n            raise"),

    ("mp3 vazio do sintetizador passa a ser gravado como voz",
     VOZ,
     '            if not mp3:\n                raise RuntimeError("o sintetizador devolveu vazio")',
     "            pass"),

    ("erro de credencial no bucket passa a valer como 'ausente'",
     PORTA,
     '        codigo = str(exc.response.get("Error", {}).get("Code", ""))\n'
     '        if codigo in ("404", "NoSuchKey", "NotFound"):\n'
     "            return False\n"
     "        raise",
     "        return False"),

    # ── Quando a sintese acontece ───────────────────────────────────────────
    ("criar sala deixa de aquecer a voz (a sala nasce muda)",
     ROOMS,
     "    if body.roteiro:\n        _aquecer_voz(body.roteiro)\n",
     ""),

    ("o aquecimento perde a referencia forte e a coleta o mata na metade",
     ROOMS,
     "    _aquecimentos.add(tarefa)\n    tarefa.add_done_callback(_aquecimentos.discard)",
     "    return"),

    ("sem loop de eventos a criacao de sala passa a estourar",
     ROOMS,
     "    except RuntimeError:\n        return      # sem loop (teste, script): a sala é criada sem voz",
     "    except KeyError:\n        return"),

    ("a sala deixa de receber as URLs na carga",
     ROOMS,
     '            "roteiro": _roteiro_com_voz(_roteiro_com_banner(',
     '            "roteiro": (_roteiro_com_banner('),

    ("a rota de preparar a voz fica aberta ao aluno",
     AULA,
     '    await _require_host(user)\n    linha = await pool().fetchrow("SELECT roteiro FROM video_rooms WHERE id=$1", room_id)',
     '    linha = await pool().fetchrow("SELECT roteiro FROM video_rooms WHERE id=$1", room_id)'),

    ("o conserto passa a ter implementacao propria, separada do aquecimento",
     AULA,
     "    return await voz_porta.preparar(roteiro)",
     "    return {\"pedidos\": 0, \"prontos\": 0, \"falhas\": 0, \"ja_tinha\": 0}"),

    # ── A tela ──────────────────────────────────────────────────────────────
    ("volta a existir uma SEGUNDA copia do mapa etapa->secao",
     ROTEIRO,
     "  const blocos = blocosDaEtapa(roteiro, stage);",
     '  const secao = stage === "registration_open" || stage === "registration_close" ? "abertura"\n'
     '    : stage === "synopsis" ? "revisitando"\n'
     '      : stage === "groups" ? "aquecimento"\n'
     '        : stage === "plenary" ? "plenaria"\n'
     '          : stage === "release_risks" ? "analise"\n'
     '            : "feedback";\n'
     "  const blocos = rBlocos(roteiro, secao);"),

    ("`amplify_code` volta a cair no default e mostra a secao de FEEDBACK",
     ROTEIRO,
     '    case "registration_open": case "amplify_code": case "registration_close":',
     '    case "registration_open": case "registration_close":'),

    ("o mapa volta a ter catch-all e a voz anuncia o FEEDBACK no meio da analise",
     ROTEIRO,
     "    default:\n      return null;\n  }\n}",
     '    default:\n      return "feedback";\n  }\n}'),

    ("as questoes da plenaria voltam a falar a secao inteira",
     ROTEIRO,
     '  if (stage === "question") return rIntroQuestoes(r);\n',
     ""),

    ("o card 'Relembrando o episodio' volta a aparecer sem voz",
     FRONT,
     '        : pblStage === "plenary" ? paresRelembrando\n',
     ""),

    ("o texto fixo volta a ser relido em toda etapa da mesma secao",
     FRONT,
     "      const repete = !!chaveDosFixos && chaveDosFixos === antes.fixos;",
     "      const repete = false;"),

    ("o repetir volta a tocar so o ultimo card revelado",
     FRONT,
     "            onRepetir={repetirAEtapa}",
     "            onRepetir={voz.repetir}"),

    ("a aba espelho do grupo passa a falar junto (instrucao em dobro)",
     FRONT,
     '  const voz = useVozDaEtapa(filaDaVoz, pblActive && !isBroadcast(identity || ""));',
     "  const voz = useVozDaEtapa(filaDaVoz, pblActive);"),

    ("a recusa do autoplay deixa de seguir para a proxima fala",
     FRONT,
     "      audio.play().catch(() => segue(i, false));",
     "      audio.play();"),

    ("`ended` + recusa na mesma fala passam a engolir uma instrucao",
     FRONT,
     "      if (morto || i !== atual) return;",
     "      if (morto) return;",),

    ("o controle de silenciar aparece para o aluno",
     FRONT,
     "        {pblActive && amStaff && temVozNaEtapa && (\n          <ControleDaVoz",
     "        {pblActive && temVozNaEtapa && (\n          <ControleDaVoz"),

    # ── O conteudo que varia por episodio ───────────────────────────────────
    ("a chave do banner (imagem) passa a ser mandada ao Polly",
     VOZ,
     'CAMPOS_SEM_VOZ: frozenset[str] = frozenset({"bannerFundo"})',
     "CAMPOS_SEM_VOZ: frozenset[str] = frozenset()"),

    ("a voz dos campos entra DENTRO de `campos` (a sinopse vira link na tela)",
     VOZ,
     '            roteiro["audiosDosCampos"] = vozes',
     '            roteiro["campos"] = vozes'),

    ("a lista de vozes perde os vazios e desalinha dos itens",
     VOZ,
     "                vozes[nome] = [_assinar_texto(item, assinar, perfil) for item in valor]",
     "                vozes[nome] = [u for u in (_assinar_texto(i, assinar, perfil) for i in valor) if u]"),

    ("fixos e campos voltam a ser pedidos duas vezes quando repetem",
     VOZ,
     "        if texto not in vistos:\n            vistos.add(texto)\n            fora.append(texto)",
     "        fora.append(texto)"),

    ("a tela volta a filtrar texto e voz separados",
     ROTEIRO,
     "  return rListaComVoz(r, name).map((p) => p.texto);",
     '  const v = r?.campos?.[name];\n'
     '  return Array.isArray(v) ? v.map((x) => String(x || "").trim()).filter(Boolean) : [];'),

    ("revelar um card passa a repetir a etapa inteira em voz alta",
     FRONT,
     "      setFilaDaVoz(cards.slice(antes.ate, shownCount).filter(Boolean));",
     "      setFilaDaVoz(cards.slice(0, shownCount).filter(Boolean));"),

    ("o SDK deixa de declarar a voz de cada paragrafo",
     SDK,
     "  audios?: string[];",
     "  audios?: Record<string, string>;"),
]


def prova_passa() -> bool:
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", str(PROVA)], cwd=str(RAIZ),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode == 0


print("sanidade: a prova passa com a arvore intacta?")
if not prova_passa():
    raise SystemExit("[ERRO] a prova ja falha ANTES de qualquer estrago; "
                     "conserte a arvore antes de falsificar.")
print("   sim\n")

falhas = 0
for rotulo, arquivo, de, para in ESTRAGOS:
    original = io.open(arquivo, encoding="utf-8").read()
    if de not in original:
        print(f"   NAO MEDIDO  {rotulo}")
        print(f"               trecho ausente em {arquivo.name}: {de!r}")
        falhas += 1
        continue
    if original.count(de) > 1:
        # Ancora ambigua: `replace(..., 1)` estragaria a PRIMEIRA ocorrencia,
        # que pode nao ser a que a prova mede -- e a prova ficaria verde com o
        # defeito de volta em outro lugar. Ja aconteceu neste repositorio.
        print(f"   AMBIGUO     {rotulo}")
        print(f"               {original.count(de)} ocorrencias em {arquivo.name}")
        falhas += 1
        continue
    try:
        io.open(arquivo, "w", encoding="utf-8", newline="\n").write(
            original.replace(de, para, 1))
        pegou = not prova_passa()
    finally:
        io.open(arquivo, "w", encoding="utf-8", newline="\n").write(original)
    print(f"   {'ok   ' if pegou else 'PASSOU'}      {rotulo}")
    if not pegou:
        print("               a prova ficou VERDE com o defeito de volta")
    falhas += not pegou

print(f"\nestragos nao detectados: {falhas}")
raise SystemExit(1 if falhas else 0)
