import { useMemo } from "react";
import qrcode from "qrcode-generator";

/** QR no visual da sala: módulos em ponto, cantos arredondados e o play no centro.
 *
 *  A correção de erro é a mais alta (H, ~30%): é ela que paga o furo do centro e os
 *  pontos menores que o módulo. O fundo é claro de propósito: leitor de celular costuma
 *  falhar em QR invertido, e esta tela é projetada para a turma inteira ler de longe. */

const MARGEM = 4;          // zona de silêncio exigida pelo padrão, em módulos
const OLHO = 7;            // os três quadrados de canto têm 7x7 módulos
const FRACAO_DO_CENTRO = 0.2;

export default function QrPersonalizado({ valor, rotulo }: { valor: string; rotulo: string }) {
  const { lado, pontos, centro, furo } = useMemo(() => {
    const q = qrcode(0, "H");
    q.addData(valor, "Byte");
    q.make();
    const n = q.getModuleCount();
    // Ímpar, para o furo ficar centrado na grade.
    const f = Math.floor(n * FRACAO_DO_CENTRO) | 1;
    const ini = (n - f) / 2;
    const noOlho = (l: number, c: number) =>
      (l < OLHO && c < OLHO) || (l < OLHO && c >= n - OLHO) || (l >= n - OLHO && c < OLHO);
    const noFuro = (l: number, c: number) => l >= ini && l < ini + f && c >= ini && c < ini + f;
    let d = "";
    for (let l = 0; l < n; l++) {
      for (let c = 0; c < n; c++) {
        if (!q.isDark(l, c) || noOlho(l, c) || noFuro(l, c)) continue;
        const x = c + MARGEM + 0.5, y = l + MARGEM + 0.5, r = 0.47;
        d += `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
      }
    }
    return { lado: n + 2 * MARGEM, pontos: d, centro: n / 2 + MARGEM, furo: f };
  }, [valor]);

  const olho = (x: number, y: number) => (
    <g key={`${x}-${y}`}>
      <path fillRule="evenodd" fill="#0c1218"
        d={`M${x + 2} ${y}h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-3a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2z
            M${x + 2} ${y + 1}a1 1 0 0 0-1 1v3a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-3a1 1 0 0 0-1-1z`} />
      <rect x={x + 2} y={y + 2} width="3" height="3" rx="0.9" fill="#128a4a" />
    </g>
  );

  const selo = furo - 1;
  const fim = lado - MARGEM - OLHO;
  return (
    <svg className="vr-qr-arte" viewBox={`0 0 ${lado} ${lado}`} role="img" aria-label={rotulo}>
      <rect width={lado} height={lado} rx="3" fill="#f6f8f7" />
      <path d={pontos} fill="#0c1218" />
      {olho(MARGEM, MARGEM)}
      {olho(fim, MARGEM)}
      {olho(MARGEM, fim)}
      <rect x={centro - selo / 2} y={centro - selo / 2} width={selo} height={selo} rx={selo * 0.26} fill="#2fbf5f" />
      <path fill="#06220f"
        d={`M${centro - selo * 0.17} ${centro - selo * 0.25}L${centro + selo * 0.27} ${centro}L${centro - selo * 0.17} ${centro + selo * 0.25}z`} />
    </svg>
  );
}
