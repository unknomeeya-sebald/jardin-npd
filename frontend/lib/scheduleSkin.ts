/**
 * 일정관리(iframe으로 띄운 원본 HTML)를 앱의 디자인 토큰에 맞추는 스킨.
 * - 원본의 색 변수(--white, --acc …)를 앱 변수(--surface, --accent …)로 연결한다.
 * - 값은 앱(부모 창)의 현재 테마에서 읽어 와서, 밝게/어둡게 전환 때 같이 바뀐다.
 * - 원본 파일은 건드리지 않는다(원본이 바뀌어도 그대로 다시 입힐 수 있다).
 */

/** 원본 변수 ← 앱 변수 */
const MAP: Record<string, string> = {
  "--bg": "--bg",
  "--white": "--surface",
  "--band": "--surface",
  "--s1": "--sunken",
  "--s2": "--sunken",
  "--ink": "--ink",
  "--sub": "--muted",
  "--mute": "--faint",
  "--faint": "--line-strong",
  "--line": "--line",
  "--acc": "--accent",
  "--acc2": "--accent",
  "--acc-s": "--accent-soft",
  "--accv": "--accent-soft",
  "--teal": "--accent",
  "--teal-s": "--accent-soft",
  "--teal-l": "--accent-soft",
  "--blue": "--accent",
  "--sig-r": "--bad",
  "--sig-y": "--warn",
  "--sig-g": "--ok",
  "--sig-n": "--none",
};

/** 부모 창의 현재 테마 값을 iframe 문서의 :root에 반영 */
export function applySkinVars(doc: Document) {
  const parent = getComputedStyle(document.documentElement);
  const root = doc.documentElement;
  for (const [mine, app] of Object.entries(MAP)) {
    const v = parent.getPropertyValue(app).trim();
    if (v) root.style.setProperty(mine, v);
  }
  root.style.setProperty("--shade", document.documentElement.classList.contains("dark") ? "rgba(0,0,0,.6)" : "rgba(20,26,46,.35)");
  root.style.setProperty("color-scheme", document.documentElement.classList.contains("dark") ? "dark" : "light");
}

/** 구조·모양 덮어쓰기. 변수 값은 applySkinVars가 넣는다. */
export const SKIN_CSS = `
html,body{background:var(--bg)}
body{font-family:"IBM Plex Sans KR","IBM Plex Sans","Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;font-size:13.5px;-webkit-font-smoothing:antialiased;font-feature-settings:"tnum" 1}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px;border-radius:6px}

/* 머리띠: 앱 화면에 이미 제목이 있으므로 얇은 정보줄로 */
header.ci{background:transparent;border-bottom:1px solid var(--line)}
header.ci .in{padding:10px 24px}
header.ci .logo{font-size:15px;font-weight:600;letter-spacing:0}
header.ci .cn{letter-spacing:0;font-weight:500;color:var(--sub)}
header.ci .ttl{display:none}
.page{padding-top:16px}

/* 면(카드·패널): 흰 상자 → 앱 패널 */
.kpi,.card,.box,.bar2,.pane,.tw,.sum,#tbox,#fpos,.dash div,.wz{
  background:var(--white);border:1px solid var(--line);border-radius:12px}
.pane,.tw{overflow:hidden}
.kpi .v{font-weight:600;letter-spacing:-.02em}
.sum{border-left:3px solid var(--acc)}
.bn{border-left:3px solid var(--acc);border-radius:0 10px 10px 0}
.plain{border:0!important}

/* 칩 */
.chip{border-radius:999px;padding:1px 9px;font-weight:600;font-size:11px}
.mbar .md{border-radius:8px;font-weight:600}

/* 버튼 */
button{font:inherit;border:1px solid var(--line);background:var(--white);color:var(--ink);
  border-radius:8px;padding:3px 11px;transition:background-color .15s,border-color .15s}
button:hover:not(:disabled){background:var(--s1);border-color:var(--faint)}
button:disabled{opacity:.4;cursor:not-allowed}
.views{gap:2px;padding:3px;background:var(--s1);border-radius:10px;width:max-content;max-width:100%}
.views button,#nav .t{border:0;background:transparent;color:var(--sub);border-radius:8px;font-weight:500;padding:6px 14px}
.views button:hover,#nav .t:hover{background:transparent;color:var(--ink)}
.views button.on,#nav .t.on{background:var(--white);color:var(--acc);font-weight:600;box-shadow:0 1px 2px rgb(0 0 0/.08)}
.op{border-radius:8px;background:var(--white)}
.op.on{background:var(--acc);border-color:var(--acc);color:var(--white)}
#fst[aria-pressed="true"]{background:var(--acc);border-color:var(--acc);color:var(--white)}
#nav{background:var(--bg);border-bottom:1px solid var(--line);padding:8px 0}
#nav label.fb{background:var(--white);border:1px solid var(--line);border-radius:8px;padding:3px 10px}

/* 입력 */
input:not([type=checkbox]):not([type=radio]):not([type=range]),select,textarea{
  font:inherit;color:var(--ink);background:var(--white);border:1px solid var(--line);
  border-radius:8px;padding:3px 8px;transition:border-color .15s}
input:not([type=checkbox]):not([type=radio]):not([type=range]):hover,select:hover,textarea:hover{border-color:var(--faint)}
input:not([type=checkbox]):not([type=radio]):not([type=range]):focus,select:focus,textarea:focus{outline:none;border-color:var(--acc)}
input:disabled,select:disabled{opacity:.5}
input[type=checkbox],input[type=radio],input[type=range]{accent-color:var(--acc)}
input[type=date]::-webkit-calendar-picker-indicator{opacity:.55;cursor:pointer}
html[style*="color-scheme: dark"] input[type=date]::-webkit-calendar-picker-indicator{filter:invert(1)}

/* 표 */
table{font-size:13px}
th,td{border-bottom:1px solid var(--line)}
th{background:var(--s1);color:var(--sub);font-weight:500}
tbody tr:hover td{background:var(--s1)}
tfoot td,tr.tot td,tr.tot th{background:var(--s1);font-weight:600}
tr.hit td,.lateL td,#plist tr.cur td{background:var(--acc-s)}
td.pk{text-decoration-color:var(--faint)}

/* 간트·순서도 글자 테두리가 새 배경색을 따르도록 */
#g text,#flow text.side{stroke:var(--white)}

/* 모달 */
#modal .in{background:var(--white);border:1px solid var(--line);border-radius:14px;box-shadow:0 12px 40px -8px rgb(0 0 0/.35)}
.mini{border:1px solid var(--line);border-radius:10px;background:var(--white);box-shadow:0 4px 16px -6px rgb(0 0 0/.25)}

/* 우하단 나가기 버튼 */
#joutb{background:var(--acc)!important;color:var(--white)!important;border-radius:999px;box-shadow:0 4px 16px rgb(0 0 0/.25)}
`;

/** 원본 HTML 머리에 스킨 스타일을 꽂는다 (원본 스타일보다 뒤) */
export function skinHtml(html: string): string {
  const tag = `<style id="app-skin">${SKIN_CSS}</style>`;
  return html.includes("</head>") ? html.replace("</head>", `${tag}</head>`) : tag + html;
}
