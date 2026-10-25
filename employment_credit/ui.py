# -*- coding: utf-8 -*-
"""
통합고용세액공제 화면 — 1단계(자료 업로드) · 2단계(사원정보)

app.py에서 두 함수만 부릅니다.
  render_credit_sidebar()                         ← 사이드바 '내 작업공간' 카드 바로 아래
  render_credit_wizard(extract_file_fn, ...)      ← 메인 화면
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode

from . import rules as R
from . import headcount as H
from . import parsers as P

STEPS = ["자료 업로드", "사원정보", "공제액 계산", "보고서"]
MONTH_COLS = [f"M{m:02d}" for m in range(1, 13)]
INFO_COLS = ["성명", "생년월일", "입사일", "퇴사일"]
CLASS_COLS = ["고용유형", "제외사유", "청년등"]


# ══════════════════════════════════════════════════════════════════
# 0. 상태 보관
# ══════════════════════════════════════════════════════════════════
def _S() -> dict:
    if "ec" not in st.session_state:
        st.session_state.ec = {
            "step": 1,
            "tax_year": R.DEFAULT_TAX_YEAR,
            "files": {},            # 파일명 → {"key": 서류종류, "text": 본문}
            "uploader_ver": 0,
            "ext": None, "ext_sig": None, "built_sig": None,
            "biz": {}, "biz_confirmed": [],
            "people": {}, "year_recs": {},
            "grid_ver": {}, "last_sent": {},
            "industry_alert_for": "",
        }
    return st.session_state.ec


def _years(s: dict) -> list[int]:
    t = int(s["tax_year"])
    return [t - i for i in range(R.YEARS_SHOWN_BACK + 1)]          # [2026, 2025, 2024]


def _ctx(s: dict, year: int) -> dict:
    b = s["biz"]
    t = int(s["tax_year"])
    key = {t: "당해_월수", t - 1: "전년_월수", t - 2: "전전년_월수"}.get(year, "당해_월수")
    try:
        n = int(b.get(key, 12))
    except (TypeError, ValueError):
        n = 12
    return {"corp_size": b.get("기업구분", "중소기업"), "months_in_year": n if n > 0 else 12}


# ══════════════════════════════════════════════════════════════════
# 1. 공통 스타일·진행표시줄
# ══════════════════════════════════════════════════════════════════
CSS = """
<style>
.ec-steps{display:flex;gap:6px;margin:4px 0 18px 0}
.ec-step{flex:1;padding:9px 12px;border-radius:6px;background:#f1f5f9;color:#64748b;font-size:.9rem;font-weight:600;
         border-bottom:3px solid #cbd5e1}
.ec-step.done{background:#e0f2fe;color:#0369a1;border-bottom-color:#38bdf8}
.ec-step.now{background:#0f172a;color:#fff;border-bottom-color:#0f172a}
.st-key-ec_drop [data-testid="stFileUploaderDropzone"]{min-height:190px;border:2px dashed #94a3b8;
         background:#f8fafc;align-items:center;justify-content:center}
.st-key-ec_biz input:not(:disabled), .st-key-ec_biz textarea:not(:disabled){color:#1d4ed8 !important;background:#fff !important}
.st-key-ec_biz input:disabled, .st-key-ec_biz textarea:disabled{color:#111827 !important;-webkit-text-fill-color:#111827 !important;
         background:#e5e7eb !important}
.ec-legend span{display:inline-block;padding:1px 8px;margin-right:6px;border-radius:3px;font-size:.8rem}
.ec-sum{font-size:.95rem;margin:2px 0 22px 2px;color:#0f172a}
.ec-sum b{color:#0369a1}
</style>
"""


def _progress(step: int):
    cells = []
    for i, name in enumerate(STEPS, start=1):
        cls = "now" if i == step else ("done" if i < step else "")
        cells.append(f"<div class='ec-step {cls}'>{i}. {name}</div>")
    st.markdown(f"<div class='ec-steps'>{''.join(cells)}</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════
# 2. 별도 창(대화상자)
# ══════════════════════════════════════════════════════════════════
@st.dialog("자료 확인 안내")
def _dlg_missing(msgs: list[str]):
    for m in msgs:
        st.markdown(f"- {m}")
    st.caption("확인을 누르면 지금 자료로 다음 단계로 넘어갑니다. 부족한 정보는 사원정보 화면에서 직접 입력할 수 있습니다.")
    if st.button("확인", type="primary", use_container_width=True):
        _S()["go_step2"] = True
        st.rerun()


@st.dialog("통합고용세액공제 적용 불가 업종")
def _dlg_industry(text: str):
    st.markdown(f"업태·종목: **{text}**")
    st.markdown("소비성서비스업(호텔업·여관업(관광숙박업 제외), 일반유흥·무도유흥주점, 단란주점, 오락·유흥 목적 사업)은 "
                "통합고용세액공제를 적용받을 수 없습니다. (조특법 제29조의8 제1항, 조특령 제29조 제3항)")
    st.caption("업종이 잘못 읽혔다면 사이드바에서 업태·종목을 고친 뒤 계속 진행하세요.")
    if st.button("확인", type="primary", use_container_width=True):
        st.rerun()


@st.dialog("오류 검토 결과", width="large")
def _dlg_review(items: list[tuple[str, str]]):
    errs = [m for lv, m in items if lv == "오류"]
    chks = [m for lv, m in items if lv == "확인"]
    if not items:
        st.success("발견된 오류가 없습니다.")
    if errs:
        st.markdown(f"**오류 {len(errs)}건** — 고쳐야 정확한 계산이 됩니다.")
        for m in errs:
            st.markdown(f"- :red[{m}]")
    if chks:
        st.markdown(f"**확인 필요 {len(chks)}건** — 맞다면 그대로 두셔도 됩니다.")
        for m in chks:
            st.markdown(f"- {m}")
    if st.button("닫기", use_container_width=True):
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 3. 사이드바: 귀속사업연도 · 사업자정보
# ══════════════════════════════════════════════════════════════════
def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def render_credit_sidebar():
    s = _S()
    with st.container(border=True):
        st.markdown("**📅 귀속사업연도**")
        new_year = st.selectbox("통합고용세액공제 계산 기준 사업연도", [2026, 2027, 2028],
                                index=[2026, 2027, 2028].index(int(s["tax_year"])),
                                label_visibility="collapsed")
        if new_year != s["tax_year"]:
            s["tax_year"] = new_year
            s["built_sig"] = None            # 연도가 바뀌면 사원표 다시 구성
            st.rerun()

    with st.container(border=True, key="ec_biz"):
        st.markdown("**🏢 사업자정보**")
        b, conf = s["biz"], set(s["biz_confirmed"])

        def txt(label, field):
            v = st.text_input(label, value=str(b.get(field, "") or ""), disabled=field in conf, key=f"ec_biz_{field}")
            b[field] = v

        txt("상호", "상호")
        txt("설립일", "설립일")
        txt("사업자번호", "사업자번호")
        txt("업태", "업태")
        txt("종목", "종목")
        txt("사업장 소재지", "사업장소재지")

        cap = H.is_capital_area(b.get("사업장소재지", ""))
        if cap is not None:
            st.caption("수도권 사업장" if cap else "수도권 밖 사업장")

        b["기업구분"] = st.selectbox("기업 구분", R.CORP_SIZES,
                                  index=R.CORP_SIZES.index(b.get("기업구분", "중소기업")), key="ec_biz_size")
        c1, c2 = st.columns(2)
        b["전년_월수"] = c1.number_input("전년도 사업연도 월수", 0, 12, _int(b.get("전년_월수"), 12), key="ec_biz_pm")
        b["당해_월수"] = c2.number_input("당해 사업연도 월수", 0, 12, _int(b.get("당해_월수"), 12), key="ec_biz_cm")

    ind = f"{b.get('업태', '')} {b.get('종목', '')}".strip()
    if ind and H.is_excluded_industry(ind) and s["industry_alert_for"] != ind:
        s["industry_alert_for"] = ind
        _dlg_industry(ind)


# ══════════════════════════════════════════════════════════════════
# 4. 1단계: 자료 업로드
# ══════════════════════════════════════════════════════════════════
def _page_upload(extract_file_fn, log_tokens_fn, room_key):
    s = _S()
    if s.pop("go_step2", False):
        _enter_step2()
        st.rerun()

    st.subheader("자료 업로드")
    st.caption("아래 자료를 한 번에 끌어다 놓으면 종류를 자동으로 구분합니다. 잘못 구분된 파일은 오른쪽에서 바꿀 수 있습니다.")

    have = {}
    for name, f in s["files"].items():
        if f.get("key"):
            have.setdefault(f["key"], []).append(name)

    rows = []
    for key, label, required, _ in R.DOC_TYPES:
        state = "✅ 업로드됨" if have.get(key) else ("❗ 필수" if required else "선택")
        rows.append({"자료": label, "상태": state, "용도": R.DOC_HELP.get(key, ""),
                     "파일": ", ".join(have.get(key, []))})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    _, mid, _ = st.columns([1, 4, 1])
    with mid:
        with st.container(key="ec_drop"):
            ups = st.file_uploader("파일을 이곳에 끌어다 놓으세요 (PDF·엑셀·이미지)", accept_multiple_files=True,
                                   type=["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
                                   key=f"ec_up_{s['uploader_ver']}")
    new = [u for u in (ups or []) if u.name not in s["files"]]
    if new:
        with st.spinner(f"{len(new)}개 파일을 읽는 중입니다..."):
            for u in new:
                text = extract_file_fn(u, room_key) or ""
                s["files"][u.name] = {"key": P.classify_file(u.name, text), "text": text}
        s["uploader_ver"] += 1
        st.rerun()

    if s["files"]:
        st.markdown("**올린 파일**")
        opts = [None] + [k for k, *_ in R.DOC_TYPES]
        for name, f in list(s["files"].items()):
            c1, c2, c3 = st.columns([5, 4, 1])
            c1.markdown(f"📄 {name}")
            f["key"] = c2.selectbox("종류", opts, index=opts.index(f.get("key")), key=f"ec_k_{name}",
                                    format_func=lambda k: "종류를 선택하세요" if k is None else R.DOC_LABEL[k],
                                    label_visibility="collapsed")
            if c3.button("삭제", key=f"ec_del_{name}"):
                s["files"].pop(name)
                st.rerun()

    st.write("")
    _, right = st.columns([5, 1])
    if right.button("다음", type="primary", use_container_width=True, disabled=not s["files"]):
        classified = {}
        for name, f in s["files"].items():
            if f.get("key"):
                classified.setdefault(f["key"], []).append(name)
        sig = json.dumps(sorted((n, f.get("key")) for n, f in s["files"].items()), ensure_ascii=False)
        if s["ext_sig"] != sig:
            texts = {k: "\n\n".join(s["files"][n]["text"] for n in names) for k, names in classified.items()}
            with st.spinner("서류에서 사업자·근로자 정보를 읽는 중입니다... (1~2분 걸릴 수 있습니다)"):
                s["ext"] = P.extract_all(texts, log_tokens_fn, room_key)
                s["ext_sig"] = sig
                msgs = P.check_missing(classified, s["ext"], int(s["tax_year"]))
                msgs += [m for m in P.ai_extra_warnings(s["ext"], log_tokens_fn, room_key) if m not in msgs]
                s["pending_msgs"] = msgs
        msgs = s.get("pending_msgs") or []
        if msgs:
            _dlg_missing(msgs)
        else:
            _enter_step2()
            st.rerun()


def _enter_step2():
    s = _S()
    sig = f"{s['ext_sig']}|{s['tax_year']}"
    if s["built_sig"] != sig:
        ext = s["ext"] or {}
        s["biz"], s["biz_confirmed"] = P.build_biz_info(ext, int(s["tax_year"]))
        s["people"], s["year_recs"] = P.build_people(ext, _years(s))
        s["grid_ver"], s["last_sent"] = {}, {}
        s["built_sig"] = sig
        for k in list(st.session_state.keys()):          # 사이드바 입력칸을 새 값으로
            if str(k).startswith("ec_biz_"):
                del st.session_state[k]
    s["step"] = 2


# ══════════════════════════════════════════════════════════════════
# 5. 2단계: 사원정보 표
# ══════════════════════════════════════════════════════════════════
JS_LOCKED = JsCode("""
function(p){
  if (p.node.rowPinned) return false;
  const L = (p.data._lock || '').split(',');
  return !L.includes(p.colDef.field);
}""")

JS_STYLE = JsCode("""
function(p){
  if (p.node.rowPinned) return {backgroundColor:'#eef2f7', color:'#0f172a', fontWeight:'700'};
  const L = (p.data._lock || '').split(',');
  if (L.includes(p.colDef.field)) return {backgroundColor:'#e5e7eb', color:'#111827'};
  return {backgroundColor:'#ffffff', color:'#1d4ed8'};
}""")

JS_STYLE_REGULAR = JsCode("""
function(p){
  if (p.node.rowPinned) return {backgroundColor:'#eef2f7'};
  const ovr = p.data._sovr === '1';
  const base = p.value === 'O' ? {color:'#047857', fontWeight:'700'} : {color:'#b91c1c', fontWeight:'700'};
  base.backgroundColor = '#ffffff';
  if (ovr) { base.border = '2px solid #f59e0b'; }
  return base;
}""")

JS_MONTH_EDITABLE = JsCode("""
function(p){
  if (p.node.rowPinned) return false;
  const i = parseInt(p.colDef.field.slice(1)) - 1;
  if ((p.data._inact || '')[i] === '1') return false;
  return !(p.data._lock || '').split(',').includes('M');
}""")

JS_MONTH_STYLE = JsCode("""
function(p){
  if (p.node.rowPinned) return {backgroundColor:'#eef2f7', color:'#0f172a', fontWeight:'700', textAlign:'center'};
  const i = parseInt(p.colDef.field.slice(1)) - 1;
  const s = {textAlign:'center'};
  if ((p.data._inact || '')[i] === '1') { s.backgroundColor = '#f1f5f9'; s.color = '#cbd5e1'; return s; }
  if ((p.data._lock || '').split(',').includes('M')) { s.backgroundColor = '#e5e7eb'; s.color = '#9ca3af'; return s; }
  s.color = '#1d4ed8';
  s.backgroundColor = (p.data._ymask || '')[i] === '1' ? '#dcfce7' : '#ffffff';
  if ((p.data._nopay || '')[i] === '1') s.backgroundColor = '#fef9c3';
  if ((p.data._movr || '')[i] === '1') { s.border = '2px solid #f59e0b'; s.fontWeight = '700'; }
  return s;
}""")

JS_YOUTH_PARAMS = JsCode("""
function(p){ return {values: (p.data._yopts || '').split('|')}; }""")

JS_NUM_FMT = JsCode("""
function(p){
  if (p.value === null || p.value === undefined || p.value === '') return '';
  const v = Number(p.value); if (isNaN(v)) return p.value;
  return (Math.round(v * 10000) / 10000).toString();
}""")


def _build_year_rows(s: dict, year: int) -> tuple[list[dict], dict, dict]:
    people, recs = s["people"], s["year_recs"].setdefault(year, {})
    ctx = _ctx(s, year)
    computed, rows = {}, []
    for pid, p in people.items():
        if not H.worked_in_year(p, year):
            continue
        yrec = recs.setdefault(pid, P.new_year_rec())
        c = H.compute_row(p, yrec, year, ctx)
        computed[pid] = c

        unlocked = yrec.get("_unlocked")
        lock = []
        if not unlocked:
            lock += [f for f in INFO_COLS if f in (p.get("_confirmed") or [])]
            lock += [f for f in ("고용유형",) if f in (yrec.get("_confirmed") or [])]
            if p.get("주주관계") or p.get("외국인"):
                lock.append("제외사유")
        if c["excl_locked"]:
            lock.append("제외사유")
        if c["상시"] == "X":
            lock += ["청년등", "M"]
        if c["상시"] == "X" or (yrec.get("고용유형") or R.EMP_REGULAR) in R.EMP_NOT_YOUTH_REGULAR:
            lock.append("병역개월")

        ovr = {int(k) for k in (yrec.get("월_override") or {})}
        row = {
            "pid": pid,
            **{f: p.get(f, "") for f in INFO_COLS},
            "고용유형": yrec.get("고용유형") or R.EMP_REGULAR,
            "제외사유": c["제외사유"],
            "병역개월": int(p.get("병역개월", 0) or 0),
            "청년등": c["청년등"],
            "상시": c["상시"],
            **{MONTH_COLS[i]: c["months"][i] for i in range(12)},
            "합계": float(c["row_sum"]),
            "평균": round(c["row_avg"], 4),
            "_lock": ",".join(lock),
            "_yopts": "|".join(c["youth_options"]),
            "_ymask": "".join("1" if f else "0" for f in c["youth_flags"]),
            "_inact": "".join("1" if v is None else "0" for v in c["months"]),
            "_nopay": "".join("1" if (i + 1) in c["no_pay_months"] else "0" for i in range(12)),
            "_movr": "".join("1" if (i + 1) in ovr else "0" for i in range(12)),
            "_sovr": "1" if yrec.get("상시_override") else "0",
            "_sauto": c["상시_auto"],
        }
        rows.append(row)
    totals = H.year_totals(list(computed.values()), ctx["months_in_year"])
    return rows, computed, totals


def _grid_options(df: pd.DataFrame, totals: dict) -> dict:
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(resizable=True, sortable=False, filter=False, suppressMovable=True,
                                editable=JS_LOCKED, cellStyle=JS_STYLE, minWidth=60)
    for c in [c for c in df.columns if c.startswith("_") or c == "pid"]:
        gb.configure_column(c, hide=True, editable=False)

    gb.configure_column("성명", pinned="left", width=90)
    for c in ("생년월일", "입사일", "퇴사일"):
        gb.configure_column(c, width=104)
    gb.configure_column("고용유형", width=150, cellEditor="agSelectCellEditor",
                        cellEditorParams={"values": R.EMP_TYPES})
    gb.configure_column("제외사유", headerName="상시근로자 제외사유", width=190, cellEditor="agSelectCellEditor",
                        cellEditorParams={"values": R.EXCL_REASONS})
    gb.configure_column("병역개월", headerName="병역(개월)", width=88, cellEditor="agNumberCellEditor",
                        cellEditorParams={"min": 0, "max": R.MILITARY_MAX_MONTHS, "precision": 0})
    gb.configure_column("청년등", headerName="청년등 상시근로자", width=150, cellEditor="agSelectCellEditor",
                        cellEditorParams=JS_YOUTH_PARAMS)
    gb.configure_column("상시", headerName="상시(O/X)", width=86, editable=True, cellStyle=JS_STYLE_REGULAR,
                        cellEditor="agSelectCellEditor", cellEditorParams={"values": ["O", "X"]})
    for i, c in enumerate(MONTH_COLS, start=1):
        gb.configure_column(c, headerName=f"{i}월", width=58, editable=JS_MONTH_EDITABLE, cellStyle=JS_MONTH_STYLE,
                            cellEditor="agSelectCellEditor", cellEditorParams={"values": R.MONTH_CHOICES},
                            valueFormatter=JS_NUM_FMT)
    sum_style = {"backgroundColor": "#f8fafc", "color": "#0f172a", "fontWeight": "600", "textAlign": "center"}
    gb.configure_column("합계", width=70, editable=False, valueFormatter=JS_NUM_FMT, cellStyle=sum_style)
    gb.configure_column("평균", width=76, editable=False, valueFormatter=JS_NUM_FMT, cellStyle=sum_style)
    gb.configure_grid_options(singleClickEdit=True, stopEditingWhenCellsLoseFocus=True, rowHeight=30)
    go = gb.build()

    n = totals["months_in_year"]
    pinned = []
    for label, mk, sk, ak in (("상시근로자", "월별_상시", "상시_합계", "상시_평균"),
                              ("청년등", "월별_청년등", "청년등_합계", "청년등_평균"),
                              ("청년등 외", "월별_청년외", "청년외_합계", "청년외_평균")):
        r = {"성명": label, "생년월일": "", "고용유형": f"÷ {n}개월"}
        r.update({MONTH_COLS[i]: totals[mk][i] for i in range(12)})
        r["합계"], r["평균"] = totals[sk], totals[ak]
        pinned.append(r)
    go["pinnedBottomRowData"] = pinned
    return go


def _norm(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def _apply_changes(s: dict, year: int, sent: list[dict], back: pd.DataFrame) -> bool:
    """표에서 바뀐 칸을 찾아 사람정보·연도별 입력값에 반영. 바뀐 게 있으면 True"""
    if back is None or back.empty or "pid" not in back.columns:
        return False
    before = {r["pid"]: r for r in sent}
    changed = False
    for _, nr in back.iterrows():
        pid = nr.get("pid")
        old = before.get(pid)
        if old is None:
            continue
        p, yrec = s["people"][pid], s["year_recs"][year][pid]
        us = yrec.setdefault("_user_set", [])

        for f in INFO_COLS:
            nv = _norm(nr.get(f))
            if nv != _norm(old.get(f)):
                d = H.parse_date(nv) if f != "성명" else None
                p[f] = nv if f == "성명" else (d.isoformat() if d else nv)
                changed = True

        nv = _norm(nr.get("병역개월"))
        if nv != _norm(old.get("병역개월")) and not _same_num(nv or "0", _norm(old.get("병역개월")) or "0"):
            try:
                months = int(float(nv or 0))
            except ValueError:
                months = 0
            p["병역개월"] = max(0, min(months, R.MILITARY_MAX_MONTHS))      # 최대 6년(72개월)
            changed = True

        nv = _norm(nr.get("고용유형"))
        if nv and nv != _norm(old.get("고용유형")):
            yrec["고용유형"] = nv
            yrec["_user_set"] = [x for x in us if x not in ("제외사유", "청년등")] + ["고용유형"]   # 대분류가 바뀌면 하위 선택 초기화
            us = yrec["_user_set"]
            changed = True

        nv = _norm(nr.get("제외사유"))
        if nv and nv != _norm(old.get("제외사유")):
            yrec["제외사유"] = nv
            yrec["_user_set"] = [x for x in us if x != "청년등"] + (["제외사유"] if "제외사유" not in us else [])
            us = yrec["_user_set"]
            changed = True

        nv = _norm(nr.get("청년등"))
        if nv and nv != _norm(old.get("청년등")):
            yrec["청년등"] = nv
            if "청년등" not in us:
                us.append("청년등")
            changed = True

        nv = _norm(nr.get("상시"))
        if nv in ("O", "X") and nv != _norm(old.get("상시")):
            if nv == old.get("_sauto"):
                yrec["상시_override"] = ""
            else:
                yrec["상시_override"] = nv
                yrec["_unlocked"] = True           # 상시 O/X를 직접 바꾸면 회색 칸도 수정 가능
            changed = True

        mo = yrec.setdefault("월_override", {})
        for i, c in enumerate(MONTH_COLS, start=1):
            nv, ov = _norm(nr.get(c)), _norm(old.get(c))
            if nv == ov or (nv and ov and _same_num(nv, ov)):
                continue
            if nv == R.MONTH_AUTO or nv == "":
                mo.pop(str(i), None)
            else:
                try:
                    mo[str(i)] = float(nv)
                except ValueError:
                    continue
            changed = True
    return changed


def _same_num(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return False


def _render_year(s: dict, year: int, room_key: str) -> tuple[dict, dict]:
    rows, computed, totals = _build_year_rows(s, year)
    tax_year = int(s["tax_year"])
    note = ""
    if year == tax_year - 2:
        note = " — 신규 공제(A)에는 쓰지 않고, 2024년 귀속 기공제분의 연속공제·사후관리 확인용"
    st.markdown(f"#### {year}년{note}")

    if not rows:
        st.info(f"{year}년에 근무한 근로자가 없습니다. 원천징수부를 올렸는지 확인하거나 아래 [사원 추가]로 입력하세요.")
        return computed, totals

    df = pd.DataFrame(rows)
    s["last_sent"][year] = rows
    ver = s["grid_ver"].get(year, 0)
    resp = AgGrid(
        df, gridOptions=_grid_options(df, totals), update_mode=GridUpdateMode.VALUE_CHANGED,
        allow_unsafe_jscode=True, theme="balham", key=f"ec_grid_{year}_{ver}",
        height=min(640, 78 + 30 * (len(rows) + 3)), fit_columns_on_grid_load=False,
    )
    back = getattr(resp, "data", None)
    if back is None:
        try:
            back = resp["data"]
        except Exception:
            back = None
    if isinstance(back, pd.DataFrame) and _apply_changes(s, year, rows, back):
        for y in _years(s):                     # 이름·날짜·병역은 다른 연도 표에도 영향
            s["grid_ver"][y] = s["grid_ver"].get(y, 0) + 1
        st.rerun()

    st.markdown(
        f"<div class='ec-sum'>{year}년 평균 — 상시근로자 <b>{totals['상시_평균']}</b>명 / "
        f"청년등 <b>{totals['청년등_평균']}</b>명 / 청년등 외 <b>{totals['청년외_평균']}</b>명 "
        f"<span style='color:#64748b'>(사업연도 {totals['months_in_year']}개월, 소수점 셋째 자리 이하 버림)</span></div>",
        unsafe_allow_html=True)
    return computed, totals


def _page_employees(room_key: str):
    s = _S()
    st.subheader("사원정보")
    st.markdown(
        "<div class='ec-legend'>"
        "<span style='background:#e5e7eb;color:#111827'>서류로 확인된 값</span>"
        "<span style='background:#fff;color:#1d4ed8;border:1px solid #cbd5e1'>입력·선택 가능</span>"
        "<span style='background:#dcfce7'>청년등 인정 월</span>"
        "<span style='background:#fef9c3'>급여 지급 없는 달</span>"
        "<span style='border:2px solid #f59e0b'>직접 고친 값</span>"
        "</div>", unsafe_allow_html=True)
    st.caption("왼쪽부터 고용유형 → 제외사유 → 병역(개월) → 청년등 순서로 고르세요. "
               "병역기간은 현역·사회복무요원 등 복무 개월 수를 넣으면 최대 72개월까지 나이에서 빼고 청년을 판정합니다.  앞에서 제외되면 뒤 칸은 자동으로 잠깁니다. "
               "회색 칸을 고쳐야 하면 그 사람의 상시(O/X)를 바꾸면 잠금이 풀립니다. "
               "월별 칸은 자동 계산되며, 눌러서 다른 값이나 '자동'을 고를 수 있습니다.")

    if not s["people"]:
        st.info("읽어온 근로자가 없습니다. [사원 추가]로 직접 입력하세요.")

    computed_all, ctx_all = {}, {}
    for y in _years(s):
        computed_all[y], _ = _render_year(s, y, room_key)
        ctx_all[y] = _ctx(s, y)

    c_add, _, c_prev, c_rev, c_next = st.columns([1.2, 3, 1, 1, 1])
    if c_add.button("➕ 사원 추가", use_container_width=True):
        pid = f"new_{len(s['people']) + 1}_{len(s['last_sent'])}"
        s["people"][pid] = {"pid": pid, "성명": "새 사원", "생년월일": "", "입사일": "", "퇴사일": "",
                            "병역개월": 0, "월급여": {}, "_confirmed": []}
        for y in _years(s):
            s["year_recs"].setdefault(y, {})[pid] = P.new_year_rec()
            s["grid_ver"][y] = s["grid_ver"].get(y, 0) + 1
        st.rerun()
    if c_prev.button("이전", use_container_width=True):
        s["step"] = 1
        st.rerun()
    if c_rev.button("오류 검토", use_container_width=True):
        prev = ((s.get("ext") or {}).get("prev_filing") or {}).get("연도별")
        _dlg_review(H.review(s["people"], s["year_recs"], _years(s), ctx_all, computed_all, prev))
    if c_next.button("다음", type="primary", use_container_width=True):
        s["step"] = 3
        st.rerun()


# ══════════════════════════════════════════════════════════════════
# 6. 진입점
# ══════════════════════════════════════════════════════════════════
def render_credit_wizard(extract_file_fn, log_tokens_fn=None, active_room_key: str = "", **_):
    s = _S()
    st.markdown(CSS, unsafe_allow_html=True)
    _progress(s["step"])

    if s["step"] == 1:
        _page_upload(extract_file_fn, log_tokens_fn, active_room_key)
    elif s["step"] == 2:
        _page_employees(active_room_key)
    else:
        st.info("3단계(공제액 계산)와 4단계(보고서)는 2단계 확인이 끝난 뒤 이어서 만듭니다.")
        if st.button("이전"):
            s["step"] = 2
            st.rerun()
