# -*- coding: utf-8 -*-
"""
전역 UI 테마 모듈 — Toss Web (TDS) 디자인 시스템 에디션
(toss_web_design_system_prompt.md [1]~[7] 규격 100% 반영)
"""
from __future__ import annotations

TOKENS = {
    "ink": "#191F28", "body": "#4E5968", "muted": "#8B95A1", "faint": "#B0B8C1",
    "line": "#E5E8EB", "line2": "#F2F4F6", "canvas": "#F4F6FA",
    "brand": "#3182F6", "brand2": "#1B64DA", "brandsoft": "#E8F3FF",
    "agent": "#3182F6", "agentsoft": "#E8F3FF",
    "ec": "#3182F6", "ecsoft": "#E8F3FF",
    "pay": "#3182F6", "paysoft": "#E8F3FF",
    "biz": "#3182F6", "bizsoft": "#E8F3FF",
    "ok": "#00A660", "warn": "#D97706", "bad": "#F04452",
}

_ICONS = {
    "scale": '<path d="M12 3v18"/><path d="M5 7h14"/><path d="M5 7l-3 7a4 4 0 0 0 6 0z"/><path d="M19 7l-3 7a4 4 0 0 0 6 0z"/><path d="M8 21h8"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    "building": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/><path d="M8 6h.01M12 6h.01M16 6h.01M8 10h.01M12 10h.01M16 10h.01M8 14h.01M12 14h.01M16 14h.01"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "layers": '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
}


def icon(name: str, size: int = 13, color: str = "#3182F6") -> str:
    path = _ICONS.get(name, _ICONS["grid"])
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' stroke='{color}' stroke-width='2' "
            f"stroke-linecap='round' stroke-linejoin='round' style='flex:none;vertical-align:-2px'>{path}</svg>")


def sb_title(icon_name: str, text: str, pill: str = "") -> str:
    ic = icon(icon_name, 13, "#3182F6") if icon_name else ""
    return f"<div class='sb-card-title'><span class='sb-t'>{ic}{text}</span>{pill}</div>"


def brand_html() -> str:
    import streamlit as _st
    cur_mode = str(_st.session_state.get("app_top_mode", "CALENDAR"))
    prev_mode = _st.session_state.get("_sbx_last_top_mode")
    jump_seq = int(_st.session_state.get("_sbx_cat_jump_seq", 0))
    if prev_mode is not None and prev_mode != cur_mode:
        jump_seq += 1
        _st.session_state["_sbx_cat_jump_seq"] = jump_seq
    _st.session_state["_sbx_last_top_mode"] = cur_mode

    jump_cls = ""
    if jump_seq > 0:
        jump_cls = " sbx-cat-jump-a" if (jump_seq % 2 == 1) else " sbx-cat-jump-b"

    cat_svg = (
        "<svg width='26' height='26' viewBox='0 0 32 32' fill='none' xmlns='http://www.w3.org/2000/svg' "
        "style='flex:none;display:block;'>"
        "<path d='M6.5 15.5 L7.5 6.2 C7.6 5.3 8.7 5.0 9.3 5.6 L13.2 9.5 C14.1 9.2 15.0 9.1 16.0 9.1 "
        "C17.0 9.1 17.9 9.2 18.8 9.5 L22.7 5.6 C23.3 5.0 24.4 5.3 24.5 6.2 L25.5 15.5 "
        "C26.0 17.0 26.2 18.6 25.8 20.3 C24.8 24.5 20.9 27.0 16.0 27.0 C11.1 27.0 7.2 24.5 6.2 20.3 "
        "C5.8 18.6 6.0 17.0 6.5 15.5 Z' stroke='#FFFFFF' stroke-width='2.8' stroke-linecap='round' stroke-linejoin='round'/>"
        "</svg>"
    )
    return (
        f"<div class='sbx-brand' data-jump-seq='{jump_seq}'>"
        f"<div class='sbx-logo{jump_cls}' id='sbx-cat-logo-box'>{cat_svg}</div>"
        "<div class='sbx-brand-t'>세무 <span style='color:#3182F6;'>AI</span> 에이전트</div>"
        "</div>"
    )


SIDEBAR_CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');

/* ═════════ [3] 좌측 사이드바 레이아웃 & 입력 폼 그룹화 규격 (Toss Web TDS) ═════════ */
[data-testid="stApp"] section[data-testid="stSidebar"]{
  background:#FFFFFF !important;
  border-right:1px solid #E5E8EB !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"]{padding-top:.4rem !important;}

/* 기본 묶음 구역은 심플한 상단 구분선, 핵심 입력 카드(.st-key-ec_biz, .st-key-pay_sb_biz_card)는 입체 화이트 카드 */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not([class*="st-key-"]){
  background:transparent !important;border:none !important;border-top:1px solid #F2F4F6 !important;border-radius:0 !important;
  box-shadow:none !important;padding:10px 2px 6px !important;margin-bottom:2px !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]{
  border-top:none !important;padding:0 !important;
}
/* 핵심 입력 폼인 『사업자정보』 카드(.st-key-pay_sb_biz_card, .st-key-ec_biz) 입체 화이트 카드 강조 */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-ec_biz,
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-pay_sb_biz_card{
  background:#FFFFFF !important;
  border:1px solid #E5E8EB !important;
  border-radius:14px !important;
  padding:14px 12px 10px !important;
  margin:6px 0 8px !important;
  box-shadow:0 2px 10px rgba(0,27,55,.04) !important;
}

/* 접이식 아코디언 (개정사항·신규 세법 / 작업 자료 관리) 압축 스타일 */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stExpander"],
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stExpander"] details{
  background:#F9FAFB !important;
  border:1px solid #F2F4F6 !important;
  border-radius:10px !important;
  margin-bottom:4px !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stExpander"] summary{
  padding:8px 10px !important;
  font-size:.80rem !important;
  font-weight:700 !important;
  color:#4E5968 !important;
}

/* 묶음 제목 & 보더리스 파스텔 캡슐 배지 */
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-card-title{
  display:flex !important;align-items:center !important;justify-content:space-between !important;
  font-size:.80rem !important;font-weight:700 !important;color:#4E5968 !important;letter-spacing:-.1px !important;margin-bottom:6px !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-card-title .sb-t{display:inline-flex;align-items:center;gap:6px;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-green,
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-amber,
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-pro,
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-green,
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-orange{
  font-size:.70rem !important;font-weight:700 !important;padding:2px 8px !important;border-radius:999px !important;border:none !important;white-space:nowrap;
}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-green,
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-green{background:#E5F9F0 !important;color:#00A660 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-amber,
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-orange{background:#FFF5E5 !important;color:#D97706 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-pro{background:#E8F3FF !important;color:#3182F6 !important;}

/* 최상단 브랜드 영역 (.sbx-brand): '세무 AI 에이전트' 문구 확대 + 4대 메뉴 이동 시 고양이 웅크림 -> 0.5배 점프 -> 제자리 착지 애니메이션 */
@keyframes sbxCatCrouchJumpA {
  0%   { transform: translateY(0px) scaleX(1) scaleY(1); }
  22%  { transform: translateY(4px) scaleX(1.18) scaleY(0.76); }
  52%  { transform: translateY(-21px) scaleX(0.90) scaleY(1.12); }
  76%  { transform: translateY(2px) scaleX(1.09) scaleY(0.90); }
  88%  { transform: translateY(-4px) scaleX(0.97) scaleY(1.03); }
  100% { transform: translateY(0px) scaleX(1) scaleY(1); }
}
@keyframes sbxCatCrouchJumpB {
  0%   { transform: translateY(0px) scaleX(1) scaleY(1); }
  22%  { transform: translateY(4px) scaleX(1.18) scaleY(0.76); }
  52%  { transform: translateY(-21px) scaleX(0.90) scaleY(1.12); }
  76%  { transform: translateY(2px) scaleX(1.09) scaleY(0.90); }
  88%  { transform: translateY(-4px) scaleX(0.97) scaleY(1.03); }
  100% { transform: translateY(0px) scaleX(1) scaleY(1); }
}
.sbx-brand{
  display:flex;
  align-items:center;
  gap:12px;
  padding:18px 2px 14px;
  overflow:visible !important;
}
.sbx-logo{
  width:42px;
  height:42px;
  border-radius:14px;
  background:#3898FF;
  display:flex;
  align-items:center;
  justify-content:center;
  box-shadow:0 5px 14px rgba(49,130,246,.32), inset 0 1px 1px rgba(255,255,255,.38);
  flex:none;
  transform-origin:center bottom;
  will-change:transform;
  cursor:pointer;
}
.sbx-logo.sbx-cat-jump-a{
  animation:sbxCatCrouchJumpA 0.52s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.sbx-logo.sbx-cat-jump-b{
  animation:sbxCatCrouchJumpB 0.52s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.sbx-brand-t{
  font-size:1.38rem !important;
  font-weight:800 !important;
  color:#191F28 !important;
  letter-spacing:-0.03em !important;
  line-height:1.15 !important;
  white-space:nowrap !important;
}

/* 최상단 메뉴 네비게이션: 모든 활성 메뉴를 소프트 블루(#E8F3FF) + 토스 블루(#3182F6, 800)로 단일 통일 */
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button{
  justify-content:flex-start !important;background:transparent !important;border:none !important;box-shadow:none !important;
  color:#4E5968 !important;min-height:40px !important;height:40px !important;padding:0 12px !important;border-radius:10px !important;font-weight:600 !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button > div{justify-content:flex-start !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button p{color:inherit !important;font-weight:inherit !important;font-size:.94rem !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button:hover{background:#F2F4F6 !important;color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button[kind="primary"]{
  background:#E8F3FF !important;color:#3182F6 !important;font-weight:800 !important;border:none !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button[kind="primary"] p,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button[kind="primary"] span{
  color:#3182F6 !important;font-weight:800 !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_nav{gap:2px !important;margin-bottom:6px !important;}

/* 세그먼트 탭 스위치 (업무 화면: 급여명세서 | 사업소득) */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_pay_seg{background:#F2F4F6 !important;border-radius:11px !important;padding:4px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_pay_seg [data-testid="stHorizontalBlock"]{gap:4px !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"] div.stButton button{
  background:transparent !important;border:none !important;box-shadow:none !important;color:#8B95A1 !important;min-height:32px !important;height:32px !important;border-radius:8px !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_submode_emp_active div.stButton button,
[data-testid="stApp"][data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_submode_free_active div.stButton button,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_submode_free_active div.stButton button{
  background:#FFFFFF !important;color:#3182F6 !important;box-shadow:0 1px 4px rgba(0,27,55,.10) !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"] div.stButton button p{
  color:inherit !important;font-weight:800 !important;font-size:.86rem !important;
}

/* 사이드바 일반 버튼 & 주요 버튼 & 삭제 버튼 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button:not([kind="primary"]),
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stDownloadButton > button{
  min-height:34px !important;border-radius:9px !important;border:1px solid #E5E8EB !important;border-bottom:1px solid #E5E8EB !important;
  background:#FFFFFF !important;box-shadow:none !important;color:#4E5968 !important;font-weight:600 !important;transform:none !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button:not([kind="primary"]):hover,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stDownloadButton > button:hover{
  background:#F2F4F6 !important;border-color:#D1D6DB !important;color:#191F28 !important;
}
/* 1순위 Primary 사이드바 버튼 (당월 검토보고 등): 솔리드 토스 블루 #3182F6 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button[kind="primary"]:not([class*="btn_top_mode"]),
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button{
  background:#3182F6 !important;border:none !important;border-radius:10px !important;color:#FFFFFF !important;
  font-weight:800 !important;box-shadow:0 2px 8px rgba(49,130,246,.26) !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button[kind="primary"]:not([class*="btn_top_mode"]):hover,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button:hover{
  background:#1B64DA !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button[kind="primary"]:not([class*="btn_top_mode"]) p,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button p{
  color:#FFFFFF !important;font-weight:800 !important;
}
/* 메뉴 버튼은 다시 소프트 블루 우선 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button[kind="primary"]{
  background:#E8F3FF !important;box-shadow:none !important;color:#3182F6 !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button[kind="primary"] p{
  color:#3182F6 !important;
}

/* 3순위 Destructive 사이드바 버튼 (자료 초기화 / 현재 방 비우기): 보더리스 토스 소프트 레드 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_ec_sidebar_reset_ask div.stButton button:not(:disabled),
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_reset_ask div.stButton button:not(:disabled),
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_clear_current_room div.stButton button{
  background:#FFEEEE !important;color:#F04452 !important;border:none !important;font-weight:700 !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_ec_sidebar_reset_ask div.stButton button:not(:disabled) p,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_reset_ask div.stButton button:not(:disabled) p,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_clear_current_room div.stButton button p{
  color:#F04452 !important;font-weight:700 !important;
}

/* 통합고용 연동 버튼: 소프트 그린 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_bridge_credit div.stButton button:not(:disabled){
  background:#E5F9F0 !important;border:none !important;color:#00A660 !important;font-weight:700 !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_bridge_credit div.stButton button:not(:disabled) p{
  color:#00A660 !important;font-weight:700 !important;
}

/* 대화방 목록: 지금 방만 소프트 블루(#E8F3FF) + 토스 블루(#3182F6) */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button{
  justify-content:flex-start !important;border:none !important;background:transparent !important;min-height:32px !important;height:32px !important;padding:0 10px !important;border-radius:9px !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button > div{justify-content:flex-start !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button p{font-size:.84rem !important;font-weight:500 !important;color:#4E5968 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button:hover{background:#F2F4F6 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"][class*="_active"] div.stButton button{background:#E8F3FF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"][class*="_active"] div.stButton button p{color:#3182F6 !important;font-weight:800 !important;}

/* 입력 필드: 1px solid #E5E8EB, 포커스 시 #3182F6 + 0 0 0 2px #E8F3FF */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stTextInputRootElement"],
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stNumberInputContainer"],
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stSelectbox"] div:has(> input),
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stDateInput"] > div > div{
  border:1px solid #E5E8EB !important;border-radius:9px !important;background:#FFFFFF !important;
}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stNumberInputContainer"]:focus-within,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stSelectbox"] div:has(> input):focus-within{
  border-color:#3182F6 !important;box-shadow:0 0 0 2px #E8F3FF !important;
}
[data-testid="stApp"] section[data-testid="stSidebar"] label p{font-size:.78rem !important;color:#4E5968 !important;font-weight:600 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stToggle"] div[role="checkbox"][aria-checked="true"]{background:#3182F6 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_footer{border-top:1px solid #F2F4F6;padding-top:10px;margin-top:4px;}
</style>
"""


def ec_main_css() -> str:
    return EC_MAIN_CSS


EC_MAIN_CSS = """
<style>
/* ═════════ [1] & [2] & [7] 본문 캔버스 고정 (#F4F6FA) 및 통합고용세액공제 Toss Web 스타일 ═════════ */
[data-testid="stApp"] [data-testid="stMain"],
[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],
[data-testid="stApp"] [data-testid="stBottom"] > div{background:#F4F6FA !important;}

/* [2]-1 상단 페이지 헤더 */
.ecx-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 6px;}
.ecx-crumb{font-size:.86rem;color:#8B95A1;font-weight:500;}
.ecx-crumb .sep{color:#B0B8C1;margin:0 4px;}
.ecx-chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;}
.ecx-chip{display:inline-flex;align-items:center;gap:6px;font-size:.80rem;font-weight:700;padding:4px 12px;border-radius:999px;background:#FFFFFF;border:1px solid #E5E8EB;color:#4E5968;white-space:nowrap;}
.ecx-chip.ec, .ecx-chip.pay, .ecx-chip.biz{background:#E8F3FF;border-color:#90C2FF;color:#3182F6;}
.ecx-chip .dot{width:7px;height:7px;border-radius:50%;background:#3182F6;display:inline-block;}
.ecx-h1{font-size:1.78rem;font-weight:800;color:#191F28;letter-spacing:-.6px;line-height:1.25;margin-top:4px;}
.ecx-sub{font-size:.95rem;color:#4E5968;margin:4px 0 12px;}

/* [2]-2 상단 KPI 요약 카드 그리드 (최종 금액 강조 카드는 토스 차콜 네이비 다크 카드 #191F28 -> #1E293B + #00C471) */
.ecx-kpi{
  background:#FFFFFF;border:1px solid #E5E8EB;border-radius:14px;padding:14px 18px;
  box-shadow:0 2px 10px rgba(0,27,55,.04);min-width:0;
}
.ecx-kpi .l{font-size:.80rem;color:#4E5968;font-weight:600;}
.ecx-kpi .v{font-size:1.38rem;font-weight:800;margin-top:4px;letter-spacing:-.4px;color:#191F28;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ecx-kpi .s{font-size:.76rem;color:#8B95A1;margin-top:3px;}
.ecx-kpi.money, .ecx-kpi.money.biz{
  background:linear-gradient(135deg,#191F28 0%,#1E293B 100%) !important;
  border:1px solid #191F28 !important;
  box-shadow:0 4px 16px rgba(0,27,55,.08) !important;
}
.ecx-kpi.money .l, .ecx-kpi.money.biz .l{color:#B0B8C1 !important;}
.ecx-kpi.money .v, .ecx-kpi.money.biz .v{color:#FFFFFF !important;font-size:1.50rem !important;font-weight:800 !important;}
.ecx-kpi.money .s, .ecx-kpi.money.biz .s{color:#00C471 !important;font-weight:700 !important;}

/* [7]-1 상단 4단계 진행 스텝퍼 (.st-key-ecx_stepper): 완료(#00C471 ✓ + #3182F6 선), 현재(#3182F6 + #E8F3FF 4px 링), 대기(#F2F4F6/#8B95A1) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_stepper{
  background:#FFFFFF;border:1px solid #E5E8EB;border-radius:16px;padding:12px 20px;margin-bottom:8px;box-shadow:0 2px 10px rgba(0,27,55,.04);
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button{
  display:flex !important;align-items:center !important;justify-content:flex-start !important;gap:12px !important;
  background:transparent !important;border:none !important;box-shadow:none !important;min-height:52px !important;height:52px !important;padding:0 2px !important;transform:none !important;opacity:1 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button > div{flex:0 1 auto !important;width:auto !important;min-width:0 !important;justify-content:flex-start !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button::before{
  flex:none;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:.9rem;border:2px solid #E5E8EB;color:#8B95A1;background:#F2F4F6;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button::after{content:"";flex:1;height:2px;background:#E5E8EB;margin-left:6px;border-radius:2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"][class*="_4"] div.stButton button::after{display:none;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button p{font-size:.95rem !important;font-weight:700 !important;color:#8B95A1 !important;text-align:left !important;line-height:1.25 !important;white-space:nowrap;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button p::after{display:block;font-size:.76rem;font-weight:600;margin-top:2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_1 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_1 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_1 div.stButton button::before{content:"1";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_2 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_2 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_2 div.stButton button::before{content:"2";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_3 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_3 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_3 div.stButton button::before{content:"3";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_4 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_4 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_4 div.stButton button::before{content:"4";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button::before{content:"✓";background:#00C471;border-color:#00C471;color:#FFFFFF;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button::after{background:#3182F6;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button p{color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button p::after{content:"완료";color:#00A660;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button::before{background:#3182F6;border-color:#3182F6;color:#FFFFFF;box-shadow:0 0 0 4px #E8F3FF;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button p{color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button p::after{content:"진행 중";color:#3182F6;font-weight:800;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_open_"] div.stButton button p{color:#4E5968 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_open_"] div.stButton button p::after{content:"눌러서 이동";color:#8B95A1;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_wait_"] div.stButton button p::after{content:"대기";color:#B0B8C1;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button:hover:not(:disabled) p{color:#3182F6 !important;}

/* [4]-1 본문 버튼 3단계 위계 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]),
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[data-testid="stPopover"] button{
  background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-bottom:1px solid #E5E8EB !important;
  box-shadow:none !important;border-radius:10px !important;color:#191F28 !important;transform:none !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]) p,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button p,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[data-testid="stPopover"] button p{
  color:#191F28 !important;font-weight:600 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]):hover:not(:disabled),
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button:hover{
  border-color:#90C2FF !important;background:#F8FBFF !important;
}
/* 1순위 Primary 버튼: 솔리드 토스 블루 (#3182F6) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"]{
  background:#3182F6 !important;border:none !important;border-radius:10px !important;
  box-shadow:0 2px 8px rgba(49,130,246,.26) !important;color:#FFFFFF !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"]:hover{
  background:#1B64DA !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"] p{
  color:#FFFFFF !important;font-weight:800 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button:not([kind="primary"]){
  background:transparent !important;border:none !important;box-shadow:none !important;
}

/* 3순위 Destructive 버튼 (선택 행 삭제 / 전체 파일 비우기): 보더리스 토스 소프트 레드 (#FFEEEE / #F04452) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_del_rows_"] div.stButton button:not(:disabled),
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_clear_all_files div.stButton button:not(:disabled){
  background:#FFEEEE !important;border:none !important;color:#F04452 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_del_rows_"] div.stButton button:not(:disabled) p,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_clear_all_files div.stButton button:not(:disabled) p{
  color:#F04452 !important;font-weight:700 !important;
}

/* [7]-2 서류 체크리스트 표 (.ec-docs) 화이트 카드 & 보더리스 토스 파스텔 캡슐 배지 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs{
  width:100% !important;border-collapse:separate !important;border-spacing:0 !important;
  border-radius:16px !important;border:1px solid #E5E8EB !important;background:#FFFFFF !important;
  overflow:hidden !important;box-shadow:0 2px 10px rgba(0,27,55,.04) !important;margin:8px 0 14px !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs th{
  background:#F9FAFB !important;color:#4E5968 !important;font-weight:700 !important;font-size:.82rem !important;
  padding:11px 14px !important;border:none !important;border-bottom:1px solid #E5E8EB !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs td{
  padding:12px 14px !important;border:none !important;border-bottom:1px solid #F2F4F6 !important;color:#191F28 !important;background:#FFFFFF !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs tr:last-child td{border-bottom:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs td.led-cell,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs th.led-cell{
  width:116px !important;min-width:116px !important;text-align:center !important;white-space:nowrap !important;padding:10px 12px !important;
}
.ec-status-badge{
  display:inline-flex !important;align-items:center !important;justify-content:center !important;gap:5px !important;
  padding:4px 11px !important;border-radius:999px !important;font-size:.76rem !important;font-weight:800 !important;white-space:nowrap !important;border:none !important;
}
.ec-status-badge.done{background:#E5F9F0 !important;color:#00A660 !important;}
.ec-status-badge.req-wait{background:#FFF5E5 !important;color:#D97706 !important;}
.ec-status-badge.empty{background:#F2F4F6 !important;color:#8B95A1 !important;}
.ec-file-pill{
  display:inline-flex !important;align-items:center !important;gap:5px !important;
  padding:4px 10px !important;border-radius:8px !important;background:#E8F3FF !important;color:#3182F6 !important;
  font-size:.80rem !important;font-weight:700 !important;margin:2px 4px 2px 0 !important;
}
.ec-req-pill{background:#FFEEEE !important;color:#F04452 !important;font-weight:800 !important;font-size:.72rem !important;padding:2px 8px !important;border-radius:999px !important;margin-left:6px !important;}
.ec-opt-pill{background:#F2F4F6 !important;color:#8B95A1 !important;font-weight:700 !important;font-size:.72rem !important;padding:2px 8px !important;border-radius:999px !important;margin-left:6px !important;}

/* [7]-3 하단 한글 토스 스타일 파일 업로더 드롭존 (.st-key-ec_drop) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzone"]{
  background:#FFFFFF !important;
  border:2px dashed #90C2FF !important;
  border-radius:16px !important;
  padding:22px 24px !important;
  min-height:84px !important;
  box-shadow:0 2px 10px rgba(0,27,55,.03) !important;
  transition:all .18s ease !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzone"]:hover{
  background:#F8FBFF !important;
  border-color:#3182F6 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzoneInstructions"] > div{
  font-size:0 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzoneInstructions"] > div::before{
  content:"여기로 신고서·원천징수부 파일을 끌어다 놓거나 우측 [파일 선택]을 클릭하세요";
  display:block;font-size:.98rem;font-weight:800;color:#191F28;margin-bottom:4px;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzoneInstructions"] > div::after{
  content:"PDF, 엑셀(XLSX·XLS·CSV·한셀), 한글(HWP), 워드(DOCX), 이미지(PNG·JPG), 인건비백업(.paybak) 지원";
  display:block;font-size:.82rem;font-weight:500;color:#8B95A1;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzone"] button{
  background:#E8F3FF !important;color:#3182F6 !important;border:none !important;border-radius:10px !important;
  font-weight:800 !important;padding:8px 16px !important;font-size:0 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzone"] button::after{
  content:"파일 선택";font-size:.86rem;font-weight:800;color:#3182F6;
}

/* [6]-3 내려받기 파일 포맷 배지 (PDF #F04452, DOCX #3182F6, XLSX #00C471, MD #4E5968) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stDownloadButton button p::before,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stButton button p::before{content:"PDF";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_docx div.stDownloadButton button p::before{content:"DOCX";background:#3182F6 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_xlsx div.stDownloadButton button p::before{content:"XLSX";background:#00C471 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_md div.stDownloadButton button p::before{content:"MD";background:#4E5968 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] button p::before,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ecx_dl_"] button p::before{
  display:inline-block;background:#F04452;color:#FFFFFF;font-size:10px;font-weight:800;
  letter-spacing:.3px;padding:2px 6px;border-radius:5px;margin-right:8px;vertical-align:1px;line-height:1.2;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_xlsx div.stDownloadButton button{
  background:#E5F9F0 !important;border-color:#A7F3D0 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_xlsx div.stDownloadButton button p{
  color:#00A660 !important;font-weight:700 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dlcard{
  background:#FFFFFF;border:1px solid #E5E8EB;border-radius:16px;padding:14px 16px;margin-top:10px;box-shadow:0 2px 10px rgba(0,27,55,.04);
}
.ecx-dl-title{font-size:.95rem;font-weight:800;color:#191F28;margin:0 0 2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_actionbar{
  background:#FFFFFF;border:1px solid #E5E8EB;border-radius:16px;padding:10px 14px;margin-top:12px;box-shadow:0 -2px 10px rgba(0,27,55,.04);
}

/* 2단계 연도 머리 · 요약 줄 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-year-header{background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-left:4px solid #3182F6 !important;border-radius:10px !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-year-title{color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-bar{background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-left:4px solid #3182F6 !important;border-radius:12px !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-total-pill{background:#191F28 !important;color:#FFFFFF !important;border:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-total-pill b{color:#00C471 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-matrix-tbl th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-inc-tbl th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap th{background:#F9FAFB !important;color:#4E5968 !important;border:1px solid #E5E8EB !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-matrix-tbl th.active-yr{background:#E8F3FF !important;color:#3182F6 !important;box-shadow:inset 0 -3px 0 #3182F6 !important;}
</style>
"""


def page_header(crumbs: list, chips_html: str, title: str, sub: str) -> str:
    crumb = " <span class='sep'>›</span> ".join(crumbs)
    return (f"<div class='ecx-top'><div class='ecx-crumb'>{crumb}</div><div class='ecx-chips'>{chips_html}</div></div>"
            f"<div class='ecx-h1'>{title}</div><div class='ecx-sub'>{sub}</div>")


def kpi_row(items: list) -> str:
    n = max(1, len(items))
    cols = " ".join(["1fr"] * (n - 1) + ["1.3fr"])
    cells_list = []
    for it in items:
        if isinstance(it, dict):
            l = it.get("label", "")
            v = it.get("value", "")
            sub = it.get("sub", "")
            cls = "money" if it.get("money") else ""
        else:
            l, v, sub, cls = it
        cells_list.append(
            f"<div class='ecx-kpi {cls}'><div class='l'>{l}</div><div class='v'>{v}</div>"
            + (f"<div class='s'>{sub}</div>" if sub else "")
            + "</div>"
        )
    cells = "".join(cells_list)
    return f"<div class='ecx-kpis' style='display:grid;grid-template-columns:{cols};gap:12px;margin:2px 0 14px;'>{cells}</div>"


def pay_main_css() -> str:
    return PAY_MAIN_CSS


PAY_MAIN_CSS = EC_MAIN_CSS + """
<style>
/* ═════════ [4] & [6] 인건비 자동화 (급여명세서 · 사업소득) Toss Web 전용 스타일 ═════════ */
.pgx-hint{font-size:.80rem;color:#8B95A1;margin:2px 2px 6px;}
.pgx-card-title{font-size:.98rem;font-weight:800;color:#191F28;margin:0 0 4px;}
.pgx-card-title small{font-size:.80rem;color:#8B95A1;font-weight:500;margin-left:6px;}

/* [6]-1 표 카드(.st-key-pay_table_card) 및 다운로드 카드(.st-key-pay_dlcard) 분리 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_table_card,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_dlcard{
  background:#FFFFFF;border:1px solid #E5E8EB;border-radius:16px;padding:14px 16px;box-shadow:0 2px 10px rgba(0,27,55,.04);
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_dlcard{margin-top:6px;}

/* [4]-1 툴바 버튼 3단계 위계:
   - 1순위 Primary ([+ 행 추가]): 솔리드 토스 블루 (#3182F6)
   - 2순위 Secondary ([전월 급여/사업소득 불러오기]): 보더리스 토스 소프트 그레이 (#F2F4F6 / #191F28)
   - 3순위 Destructive ([선택한 행 삭제]): 보더리스 토스 소프트 레드 (#FFEEEE / #F04452) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_add_row div.stButton button{
  background:#3182F6 !important;border:none !important;border-radius:10px !important;
  color:#FFFFFF !important;font-weight:800 !important;box-shadow:0 2px 8px rgba(49,130,246,.26) !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_add_row div.stButton button:hover{
  background:#1B64DA !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_add_row div.stButton button p{
  color:#FFFFFF !important;font-weight:800 !important;
}

[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_load_prev_month div.stButton button{
  background:#F2F4F6 !important;border:none !important;border-radius:10px !important;color:#191F28 !important;font-weight:700 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_load_prev_month div.stButton button:hover{
  background:#E5E8EB !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_load_prev_month div.stButton button p{
  color:#191F28 !important;font-weight:700 !important;
}

[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_del_row div.stButton button{
  background:#FFEEEE !important;border:none !important;border-radius:10px !important;color:#F04452 !important;font-weight:700 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_del_row div.stButton button p{
  color:#F04452 !important;font-weight:700 !important;
}

/* 경고·주의 상태 칩: 보더리스 파스텔 배경 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button{background:#FFEEEE !important;border:none !important;border-radius:10px !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button span{color:#F04452 !important;font-weight:700 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button{background:#FFF5E5 !important;border:none !important;border-radius:10px !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button span{color:#D97706 !important;font-weight:700 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button{background:#E5F9F0 !important;border:none !important;border-radius:10px !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button span{color:#00A660 !important;font-weight:700 !important;}

/* [1번 시안] 급여명세서·사업소득 공통: '기준금액 [ 세전 | 세후 ]' 컴팩트 1줄 토스 세그먼트 알약 스위치 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"],
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div[data-testid="stTooltipHoverTarget"],
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div.stButton{
  display:flex !important;align-items:center !important;justify-content:center !important;
  width:auto !important;white-space:nowrap !important;gap:0 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div.stButton::before{
  content:"기준금액" !important;
  font-size:.85rem !important;font-weight:800 !important;color:#191F28 !important;
  margin-right:8px !important;white-space:nowrap !important;flex:none !important;letter-spacing:-.2px !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div.stButton button{
  background:#F2F4F6 !important;border:1px solid #E5E8EB !important;border-radius:999px !important;
  width:auto !important;min-width:118px !important;max-width:132px !important;
  height:36px !important;min-height:36px !important;padding:3px !important;gap:2px !important;
  display:inline-flex !important;align-items:center !important;justify-content:center !important;
  box-shadow:none !important;flex:none !important;white-space:nowrap !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div.stButton button > div,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div.stButton button p{
  display:none !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_free_sw_gross div.stButton button::before{
  content:"세전" !important;
  background:#FFFFFF !important;color:#3182F6 !important;font-size:.82rem !important;font-weight:800 !important;
  padding:5px 13px !important;border-radius:999px !important;box-shadow:0 1px 3px rgba(0,27,55,.10) !important;
  white-space:nowrap !important;line-height:1.15 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_free_sw_gross div.stButton button::after{
  content:"세후" !important;
  background:transparent !important;color:#8B95A1 !important;font-size:.82rem !important;font-weight:700 !important;
  padding:5px 13px !important;border-radius:999px !important;
  white-space:nowrap !important;line-height:1.15 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_free_sw_net div.stButton button::before{
  content:"세전" !important;
  background:transparent !important;color:#8B95A1 !important;font-size:.82rem !important;font-weight:700 !important;
  padding:5px 13px !important;border-radius:999px !important;
  white-space:nowrap !important;line-height:1.15 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_free_sw_net div.stButton button::after{
  content:"세후" !important;
  background:#FFFFFF !important;color:#3182F6 !important;font-size:.82rem !important;font-weight:800 !important;
  padding:5px 13px !important;border-radius:999px !important;box-shadow:0 1px 3px rgba(0,27,55,.10) !important;
  white-space:nowrap !important;line-height:1.15 !important;
}

/* [6]-3 내려받기 파일 포맷 배지 (PDF #F04452, JPG #3182F6, XLSX #00C471) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_dl_"] button p::before{
  display:inline-block;color:#FFFFFF;font-size:10px;font-weight:800;letter-spacing:.3px;padding:2px 6px;border-radius:5px;margin-right:8px;vertical-align:1px;line-height:1.2;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payslips_zip button p::before,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payroll_ledger_pdf button p::before,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_pdf_each button p::before,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_ledger_pdf button p::before{content:"PDF";background:#F04452;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payslips_jpg_each button p::before,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_jpg_each button p::before{content:"JPG";background:#3182F6;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button p::before,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button p::before{content:"XLSX";background:#00C471;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button{
  background:#E5F9F0 !important;border-color:#A7F3D0 !important;
}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button p,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button p{
  color:#00A660 !important;font-weight:700 !important;
}

/* [6]-4 최하단 올인원 입력창 (st.chat_input) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [data-testid="stChatInput"],
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"]{
  border-radius:14px !important;border:1.5px solid #90C2FF !important;background:#FFFFFF !important;
  box-shadow:0 4px 14px rgba(15,23,42,.06) !important;
}
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"]:focus-within,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [data-testid="stChatInput"]:focus-within{
  border-color:#3182F6 !important;box-shadow:0 4px 20px rgba(49,130,246,.16) !important;
}
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"] > div{border-color:transparent !important;}
</style>
"""
