"""
화면 디자인 B안 (토스 웹 TDS 컬러 시스템 에디션) — 공통 디자인 기준 (색·글자·버튼·사이드바)

- 배경색 고정: 본문 캔버스(#F4F6FA) · 카드 및 사이드바(#FFFFFF)
- 포인트 컬러 단일화: 토스 시그니처 블루(#3182F6) + 소프트 블루 틴트(#E8F3FF)
- 타이포그래피: 토스 쿨그레이 스케일(Grey 900 #191F28 · Grey 700 #4E5968 · Grey 500 #8B95A1)
- 시맨틱 배지: 테두리 없는 파스텔 틴트(그린 #E5F9F0/#00A660 · 레드 #FFEEEE/#F04452 · 앰버 #FFF5E5/#D97706)
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
    "ok": "#00C471", "warn": "#D97706", "bad": "#F04452",
}

# 선 아이콘 (24x24, stroke)
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
}


def icon(name: str, size: int = 13, color: str = "currentColor") -> str:
    path = _ICONS.get(name, "")
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 24 24' fill='none' stroke='{color}' stroke-width='2' "
            f"stroke-linecap='round' stroke-linejoin='round' style='flex:none;vertical-align:-2px'>{path}</svg>")


def sb_title(icon_name: str, text: str, pill: str = "") -> str:
    """사이드바 묶음 제목: 선 아이콘 + 토스 그레이 제목 + (오른쪽) 상태 꼬리표."""
    ic = icon(icon_name) if icon_name else ""
    return f"<div class='sb-card-title'><span class='sb-t'>{ic}{text}</span>{pill}</div>"


def brand_html() -> str:
    return (
        "<div class='sbx-brand'><div class='sbx-logo'>" + icon("scale", 18, "#ffffff") + "</div>"
        "<div><div class='sbx-brand-t'>세무 에이전트</div><div class='sbx-brand-s'>세무사 사무실 업무 도구</div></div></div>"
    )


SIDEBAR_CSS = """
<style>
/* ═════════ 토스 웹(TDS) 사이드바 ═════════ */
[data-testid="stApp"] section[data-testid="stSidebar"]{background:#FFFFFF !important;border-right:1px solid #E5E8EB !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"]{padding-top:.45rem !important;}
/* 기본 묶음 구역 → 얇은 구분선, 단 핵심 입력 카드(.st-key-ec_biz, .st-key-pay_sb_biz_card)는 입체 화이트 카드로 강조 */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not([class*="st-key-"]){
  background:transparent !important;border:none !important;border-top:1px solid #F2F4F6 !important;border-radius:0 !important;
  box-shadow:none !important;padding:12px 2px 6px !important;margin-bottom:2px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] > .st-key-ec_biz,
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] > .st-key-pay_sb_biz_card{
  background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-radius:14px !important;
  box-shadow:0 2px 10px rgba(0,27,55,.04) !important;padding:14px 12px 10px !important;margin:6px 0 8px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]{border-top:none !important;padding:0 !important;}
/* 묶음 제목: 토스 그레이 + 선 아이콘 */
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-card-title{font-size:.81rem !important;font-weight:700 !important;color:#4E5968 !important;letter-spacing:-.1px !important;margin-bottom:6px !important;display:flex;align-items:center;justify-content:space-between;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-card-title .sb-t{display:inline-flex;align-items:center;gap:6px;color:#191F28;font-weight:800;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-green,[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-amber,[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-pro,
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-green,[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-orange{
  font-size:.71rem !important;font-weight:700 !important;padding:2px 8px !important;border-radius:999px !important;border:none !important;white-space:nowrap;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-green,[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-green{background:#E5F9F0 !important;color:#00A660 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-amber,[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-orange{background:#FFF5E5 !important;color:#D97706 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-pro{background:#E8F3FF !important;color:#3182F6 !important;}
/* 로고: 토스 블루 스쿼클 */
.sbx-brand{display:flex;align-items:center;gap:10px;padding:2px 2px 10px;}
.sbx-logo{width:36px;height:36px;border-radius:11px;background:linear-gradient(135deg,#3182F6,#1B64DA);display:flex;align-items:center;justify-content:center;box-shadow:0 3px 8px rgba(49,130,246,.25);}
.sbx-brand-t{font-size:1.06rem;font-weight:800;color:#191F28;letter-spacing:-.3px;line-height:1.2;}
.sbx-brand-s{font-size:.76rem;color:#8B95A1;font-weight:500;}
/* 메뉴 3개: 세로 목록, 선택된 메뉴는 모두 토스 소프트 블루(#E8F3FF) + 토스 블루(#3182F6)로 통일 */
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button{
  justify-content:flex-start !important;background:transparent !important;border:none !important;box-shadow:none !important;
  color:#4E5968 !important;min-height:40px !important;height:40px !important;padding:0 12px !important;border-radius:10px !important;font-weight:600 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button p{color:inherit !important;font-weight:inherit !important;font-size:.94rem !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button:hover{background:#F2F4F6 !important;color:#191F28 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_top_mode_agent div.stButton button[kind="primary"],
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_top_mode_credit div.stButton button[kind="primary"],
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_top_mode_payroll div.stButton button[kind="primary"]{
  background:#E8F3FF !important;color:#3182F6 !important;font-weight:800 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_nav{gap:3px !important;margin-bottom:6px !important;}
/* 일반 버튼: 토스 스타일 소프트 테두리 */
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button,[data-testid="stApp"] section[data-testid="stSidebar"] div.stDownloadButton > button,[data-testid="stApp"] section[data-testid="stSidebar"] a[data-testid="stBaseLinkButton-secondary"]{
  min-height:36px !important;height:auto !important;border-radius:10px !important;border:1px solid #E5E8EB !important;border-bottom:1px solid #E5E8EB !important;
  background:#FFFFFF !important;box-shadow:none !important;color:#4E5968 !important;font-weight:600 !important;transform:none !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button p,[data-testid="stApp"] section[data-testid="stSidebar"] div.stDownloadButton > button p,[data-testid="stApp"] section[data-testid="stSidebar"] a[data-testid="stBaseLinkButton-secondary"] p{
  font-size:.86rem !important;font-weight:600 !important;color:inherit !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button:hover,[data-testid="stApp"] section[data-testid="stSidebar"] div.stDownloadButton > button:hover{background:#F2F4F6 !important;border-color:#D1D6DB !important;color:#191F28 !important;}
/* 주요 버튼(사이드바): 토스 블루 채움 */
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button[kind="primary"]{background:#3182F6 !important;border-color:#3182F6 !important;color:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button[kind="primary"] p{color:#FFFFFF !important;}
/* 지우는 버튼: 보더리스 토스 소프트 레드 */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_ec_sidebar_reset_ask div.stButton button,[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_reset_ask div.stButton button,
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_clear_current_room div.stButton button{color:#F04452 !important;border-color:transparent !important;background:#FFEEEE !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_clear_current_room{border-bottom:none !important;padding-bottom:0 !important;margin-bottom:4px !important;}
/* [+ 새 대화방 시작] 버튼: 토스 소프트 그레이 보더리스 버튼 */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_new_chat_room div.stButton button{
  background:#F2F4F6 !important;border:none !important;color:#191F28 !important;min-height:36px !important;border-radius:10px !important;font-weight:700 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_new_chat_room div.stButton button:hover{background:#E8F3FF !important;color:#3182F6 !important;}
/* 인건비: 당월 검토보고(토스 블루) · 통합고용 연동(토스 소프트 블루) */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button{background:#3182F6 !important;border-color:#3182F6 !important;color:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button p{color:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_bridge_credit div.stButton button{background:#E8F3FF !important;border-color:transparent !important;color:#3182F6 !important;}
/* 인건비: 업무 화면 전환(급여명세서/사업소득) = 토스식 회색 트랙(#F2F4F6) 위 순백색 알약 탭 */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_pay_seg{background:#F2F4F6 !important;border-radius:11px !important;padding:4px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_pay_seg [data-testid="stHorizontalBlock"]{gap:4px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"] div.stButton button{background:transparent !important;border:none !important;box-shadow:none !important;color:#8B95A1 !important;min-height:32px !important;height:32px !important;border-radius:8px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_submode_emp_active div.stButton button,
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_submode_free_active div.stButton button{
  background:#FFFFFF !important;color:#3182F6 !important;box-shadow:0 1px 4px rgba(0,27,55,.10) !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"] div.stButton button p{color:inherit !important;font-weight:700 !important;}
/* 대화방 목록: 왼쪽 정렬 목록형, 지금 방만 토스 소프트 블루(#E8F3FF) */
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button{justify-content:flex-start !important;border:none !important;background:transparent !important;min-height:34px !important;height:34px !important;padding:0 10px !important;border-radius:9px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button p{font-size:.85rem !important;font-weight:500 !important;color:#4E5968 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button:hover{background:#F2F4F6 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"][class*="_active"] div.stButton button{background:#E8F3FF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"][class*="_active"] div.stButton button p{color:#3182F6 !important;font-weight:700 !important;}
/* 입력칸·선택칸 */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="input"],[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="select"] > div{border-radius:9px !important;border-color:#E5E8EB !important;background:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="input"] input{background:#FFFFFF !important;color:#191F28 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] label p{font-size:.80rem !important;color:#4E5968 !important;font-weight:600 !important;}
/* 법령 상태 줄: 평평한 작은 점 */
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-status-row,[data-testid="stApp"] section[data-testid="stSidebar"] .pay-law-row{background:#F9FAFB !important;border:1px solid #F2F4F6 !important;box-shadow:none !important;border-radius:9px !important;padding:6px 10px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-status-left{font-size:.82rem !important;font-weight:600 !important;color:#191F28 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d{width:8px !important;height:8px !important;border:none !important;box-shadow:none !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d.green{background:#00C471 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d.orange{background:#FF9900 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d.yellow{background:#3182F6 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d.gray{background:#B0B8C1 !important;}
/* 탭(내려받기/불러오기) */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="tab-list"] button p{font-size:.82rem !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="tab-highlight"]{background:#3182F6 !important;}
/* 맨 아래 결제·API 키 */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_footer{border-top:1px solid #F2F4F6;padding-top:10px;margin-top:4px;}
/* 스위치 색 */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stToggle"] div[role="checkbox"][aria-checked="true"]{background:#3182F6 !important;}
/* 보강: 선택된 메뉴 글자색 · 왼쪽 정렬 (모두 토스 블루 #3182F6 통일) */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button > div{justify-content:flex-start !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_top_mode_agent div.stButton button[kind="primary"] p,
[data-testid="stApp"][data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_top_mode_credit div.stButton button[kind="primary"] p,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_top_mode_credit div.stButton button[kind="primary"] p,
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_top_mode_payroll div.stButton button[kind="primary"] p{color:#3182F6 !important;font-weight:800 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button[kind="primary"] span{color:inherit !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button > div{justify-content:flex-start !important;}
/* 보강: 각 화면 전용 3D 버튼도 토스 스타일 버튼으로 통일 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button:not([kind="primary"]),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stDownloadButton > button{border:1px solid #E5E8EB !important;border-bottom:1px solid #E5E8EB !important;box-shadow:none !important;background:#FFFFFF !important;transform:none !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button:disabled{background:#F9FAFB !important;color:#B0B8C1 !important;border-color:#F2F4F6 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_ec_sidebar_reset_ask div.stButton button:not(:disabled),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_reset_ask div.stButton button:not(:disabled),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_clear_current_room div.stButton button{color:#F04452 !important;border-color:transparent !important;background:#FFEEEE !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_ec_sidebar_reset_ask div.stButton button:not(:disabled) p,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_reset_ask div.stButton button:not(:disabled) p,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_clear_current_room div.stButton button p{color:#F04452 !important;font-weight:700 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_new_chat_room div.stButton button{background:#F2F4F6 !important;border:none !important;color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_new_chat_room div.stButton button p{color:#191F28 !important;font-weight:700 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_new_chat_room div.stButton button:hover{background:#E8F3FF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_new_chat_room div.stButton button:hover p{color:#3182F6 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button{background:#3182F6 !important;border-color:#3182F6 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button p{color:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_bridge_credit div.stButton button{background:#E8F3FF !important;border-color:transparent !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_bridge_credit div.stButton button p{color:#3182F6 !important;font-weight:700 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"] div.stButton button{border:none !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button:not([kind="primary"]),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"]:not([class*="_active"]) div.stButton button,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"]:not([class*="_active"]) div.stButton button{background:transparent !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"][class*="_active"] div.stButton button{background:#E8F3FF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_submode_emp_active div.stButton button,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_submode_free_active div.stButton button{background:#FFFFFF !important;box-shadow:0 1px 4px rgba(0,27,55,.10) !important;}
/* 입력칸 테두리 · 아코디언(Expander) 토스 스타일 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-baseweb="input"],[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-baseweb="select"] > div,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-baseweb="base-input"]{border:1px solid #E5E8EB !important;border-radius:9px !important;background:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-baseweb="input"] [data-baseweb="base-input"]{border:none !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stForm"]{border:none !important;padding:0 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stExpander"] details{border:1px solid #F2F4F6 !important;border-radius:10px !important;background:#F9FAFB !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stExpander"] summary{padding:6px 10px !important;font-size:.82rem !important;font-weight:700 !important;color:#4E5968 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stTextInputRootElement"],[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stNumberInputContainer"],[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stSelectbox"] div:has(> input),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stDateInput"] > div > div{border:1px solid #E5E8EB !important;border-radius:9px !important;background:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stTextInputRootElement"]:focus-within,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stNumberInputContainer"]:focus-within{border-color:#3182F6 !important;box-shadow:0 0 0 2px #E8F3FF !important;}
</style>
"""


def ec_main_css() -> str:
    """통합고용세액공제 본문 토스 웹 스타일 (머리·진행 표시·서류 상태 배지·한글 드롭존·동작 바)."""
    return EC_MAIN_CSS


EC_MAIN_CSS = """
<style>
[data-testid="stApp"] [data-testid="stMain"],[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],[data-testid="stApp"] [data-testid="stBottom"] > div{background:#F4F6FA !important;}
/* 머리: 위치 표시 + 꼬리표 + 큰 제목 */
.ecx-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 6px;}
.ecx-crumb{font-size:.86rem;color:#8B95A1;font-weight:600;}
.ecx-crumb .sep{color:#B0B8C1;margin:0 4px;}
.ecx-chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;}
.ecx-chip{display:inline-flex;align-items:center;gap:6px;font-size:.80rem;font-weight:700;padding:5px 12px;border-radius:999px;background:#FFFFFF;border:1px solid #E5E8EB;color:#4E5968;white-space:nowrap;}
.ecx-chip.ec{background:#E8F3FF;border-color:transparent;color:#3182F6;}
.ecx-chip .dot{width:7px;height:7px;border-radius:50%;background:#3182F6;display:inline-block;}
.ecx-h1{font-size:1.78rem;font-weight:800;color:#191F28;letter-spacing:-.6px;line-height:1.25;margin-top:4px;}
.ecx-sub{font-size:.95rem;color:#4E5968;margin:4px 0 12px;}
/* 상단 안내 배너: 토스 소프트 블루 틴트 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-law-banner{
  background:#E8F3FF !important;border:none !important;border-left:4px solid #3182F6 !important;
  color:#191F28 !important;border-radius:12px !important;padding:11px 16px !important;margin-bottom:12px !important;font-size:.89rem !important;line-height:1.58 !important;}
/* 진행 표시(스텝퍼): 토스 블루(#3182F6) 원 + 이름 + 상태 글자 + 잇는 선 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_stepper{background:#FFFFFF;border:1px solid #E5E8EB;border-radius:16px;padding:12px 20px;margin-bottom:10px;box-shadow:0 2px 10px rgba(0,27,55,.04);}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button{display:flex !important;align-items:center !important;justify-content:flex-start !important;gap:12px !important;
  background:transparent !important;border:none !important;box-shadow:none !important;min-height:52px !important;height:52px !important;padding:0 2px !important;transform:none !important;opacity:1 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button > div{flex:0 1 auto !important;width:auto !important;min-width:0 !important;justify-content:flex-start !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button::before{flex:none;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:.9rem;border:none;color:#8B95A1;background:#F2F4F6;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button::after{content:"";flex:1;height:2.5px;background:#E5E8EB;margin-left:6px;border-radius:2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"][class*="_4"] div.stButton button::after{display:none;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button p{font-size:.95rem !important;font-weight:700 !important;color:#8B95A1 !important;text-align:left !important;line-height:1.25 !important;white-space:nowrap;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button p::after{display:block;font-size:.76rem;font-weight:600;margin-top:2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_1 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_1 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_1 div.stButton button::before{content:"1";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_2 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_2 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_2 div.stButton button::before{content:"2";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_3 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_3 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_3 div.stButton button::before{content:"3";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_4 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_4 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_4 div.stButton button::before{content:"4";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button::before{content:"✓";background:#00C471;color:#FFFFFF;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button::after{background:#3182F6;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button p{color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button p::after{content:"완료";color:#00A660;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button::before{background:#3182F6;color:#FFFFFF;box-shadow:0 0 0 4px #E8F3FF;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button::after{background:#3182F6;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button p{color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button p::after{content:"진행 중";color:#3182F6;font-weight:800;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_open_"] div.stButton button p{color:#4E5968 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_open_"] div.stButton button p::after{content:"눌러서 이동";color:#8B95A1;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_wait_"] div.stButton button p::after{content:"대기";color:#B0B8C1;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button:hover:not(:disabled) p{color:#3182F6 !important;}
/* 본문 버튼: 토스 스타일 테두리 · 주요(다음)만 토스 블루(#3182F6) 채움 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]),[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button{background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-bottom:1px solid #E5E8EB !important;
  box-shadow:0 1px 2px rgba(0,27,55,.03) !important;border-radius:10px !important;color:#4E5968 !important;transform:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]) p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button p{color:#4E5968 !important;font-weight:600 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]):hover:not(:disabled),[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button:hover{border-color:#D1D6DB !important;background:#F2F4F6 !important;color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"]{background:#3182F6 !important;border:1px solid #3182F6 !important;border-bottom:1px solid #3182F6 !important;border-radius:10px !important;box-shadow:0 2px 8px rgba(49,130,246,.28) !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"]:hover{background:#1B64DA !important;border-color:#1B64DA !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"] p{color:#FFFFFF !important;font-weight:700 !important;}
/* 진행 표시 버튼은 위 공통 버튼 규칙보다 우선 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button:not([kind="primary"]){background:transparent !important;border:none !important;box-shadow:none !important;}
/* 지우는 버튼: 보더리스 토스 소프트 레드 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_del_rows_"] div.stButton button:not(:disabled),
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_clear_all_files div.stButton button{background:#FFEEEE !important;border-color:transparent !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_del_rows_"] div.stButton button:not(:disabled) p,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_clear_all_files div.stButton button p{color:#F04452 !important;font-weight:700 !important;}
/* 내려받기: 파일 꼬리표 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stDownloadButton button p::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stButton button p::before{content:"PDF";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_docx div.stDownloadButton button p::before{content:"DOCX";background:#3182F6 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_xlsx div.stDownloadButton button p::before{content:"XLSX";background:#00C471 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_md div.stDownloadButton button p::before{content:"MD";background:#4E5968 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] button p::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ecx_dl_"] button p::before{display:inline-block;background:#F04452;color:#FFFFFF;font-size:10px;font-weight:800;
  letter-spacing:.3px;padding:2px 6px;border-radius:5px;margin-right:8px;vertical-align:1px;line-height:1.2;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stDownloadButton button{background:#FFF5F5 !important;border:1px solid #FFD6D6 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stDownloadButton button p{color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_xlsx div.stDownloadButton button{background:#E5F9F0 !important;border-color:#B8F0D6 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_btn_pdf_rep_bot div.stDownloadButton button{background:#E8F3FF !important;border-color:#B8D8FF !important;}
/* 카드: 내려받기 카드 · 아래 동작 바 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dlcard{background:#FFFFFF;border:1px solid #E5E8EB;border-radius:16px;padding:14px 16px;margin-top:10px;box-shadow:0 2px 10px rgba(0,27,55,.04);}
.ecx-dl-title{font-size:.96rem;font-weight:800;color:#191F28;margin:0 0 2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_actionbar{background:#FFFFFF;border:1px solid #E5E8EB;border-radius:16px;padding:10px 16px;margin-top:12px;box-shadow:0 -2px 12px rgba(0,27,55,.04);}
/* 요약 카드 (3·4단계) */
.ecx-kpi{background:#FFFFFF;border:1px solid #E5E8EB;border-radius:14px;padding:14px 18px;box-shadow:0 2px 8px rgba(0,27,55,.03);}
.ecx-kpi .l{font-size:.80rem;color:#4E5968;font-weight:600;}
.ecx-kpi .v{font-size:1.42rem;font-weight:800;margin-top:4px;letter-spacing:-.4px;color:#191F28;font-variant-numeric:tabular-nums;}
.ecx-kpi .s{font-size:.76rem;color:#8B95A1;margin-top:2px;}
.ecx-kpi.money{background:linear-gradient(135deg,#191F28 0%,#1E293B 100%);border-color:#191F28;}
.ecx-kpi.money .l{color:#B0B8C1;} .ecx-kpi.money .v{color:#FFFFFF;font-size:1.52rem;} .ecx-kpi.money .s{color:#00C471;font-weight:700;}
/* 2단계 연도 머리 · 요약 줄 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-year-header{background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-left:4px solid #3182F6 !important;border-radius:12px !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-year-title{color:#191F28 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-bar{background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-left:4px solid #3182F6 !important;border-radius:14px !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-chip{background:#F9FAFB !important;border:1px solid #F2F4F6 !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-chip .kpi-tag{background:#FFFFFF !important;color:#4E5968 !important;border:1px solid #E5E8EB !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-total-pill{background:#191F28 !important;color:#FFFFFF !important;border:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-total-pill b{color:#00C471 !important;}
/* ── 개선 6: 통합고용세액공제 1단계 서류 체크리스트 표 & 토스 파스텔 배지 ── */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs{
  border-radius:16px !important;border:1px solid #E5E8EB !important;overflow:hidden !important;box-shadow:0 2px 10px rgba(0,27,55,.03) !important;background:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-matrix-tbl th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-inc-tbl th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap th strong,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap th b{
  background:#F9FAFB !important;color:#4E5968 !important;border:none !important;border-bottom:1px solid #E5E8EB !important;padding:11px 14px !important;font-size:.83rem !important;font-weight:700 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-matrix-tbl th.active-yr{background:#E8F3FF !important;color:#3182F6 !important;box-shadow:inset 0 -3px 0 #3182F6 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs td{
  border:none !important;border-bottom:1px solid #F2F4F6 !important;padding:11px 14px !important;color:#191F28 !important;background:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs tr:last-child td{border-bottom:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs tr.on td{background:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs tr.req-wait td{background:#FFFDF9 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs td.led-cell,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs th.led-cell{width:96px !important;text-align:center !important;padding-left:10px !important;padding-right:6px !important;}
.ec-status-badge{display:inline-flex;align-items:center;justify-content:center;gap:4px;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:700;white-space:nowrap;line-height:1.3;}
.ec-status-badge.done{background:#E5F9F0;color:#00A660;}
.ec-status-badge.req-wait{background:#FFF5E5;color:#D97706;}
.ec-status-badge.empty{background:#F2F4F6;color:#8B95A1;}
.ec-req-pill{background:#FFEEEE !important;color:#F04452 !important;font-weight:700 !important;padding:2px 7px !important;border-radius:999px !important;}
.ec-opt-pill{background:#F2F4F6 !important;color:#8B95A1 !important;font-weight:600 !important;padding:2px 7px !important;border-radius:999px !important;}
.ec-extra-pill{background:#E8F3FF !important;color:#3182F6 !important;font-weight:700 !important;padding:2px 7px !important;border-radius:999px !important;}
.ec-file-pill{display:inline-flex;align-items:center;gap:5px;background:#F2F4F6;color:#191F28;padding:3px 10px;border-radius:999px;font-size:.80rem;font-weight:600;margin:2px 4px 2px 0;}
/* ── 개선 6: 하단 파일 업로더 한글 토스 스타일 드롭존 ── */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzone"]{
  background:#FFFFFF !important;border:2px dashed #90C2FF !important;border-radius:16px !important;padding:22px 24px !important;
  transition:all .16s ease !important;box-shadow:0 2px 10px rgba(49,130,246,.05) !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzone"]:hover{
  background:#F8FBFF !important;border-color:#3182F6 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzoneInstructions"] > div > span{
  font-size:0 !important;line-height:1.4 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzoneInstructions"] > div > span::after{
  content:"여기로 신고서·원천징수부 파일을 끌어다 놓거나 [파일 선택]을 클릭하세요";font-size:1.0rem !important;font-weight:800 !important;color:#191F28 !important;display:block;margin-bottom:3px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzoneInstructions"] > div > small{
  font-size:0 !important;line-height:1.3 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzoneInstructions"] > div > small::after{
  content:"파일당 최대 200MB · PDF, XLSX, XLS, CSV, CELL, HWP, HWPX, DOCX, PNG, JPG, WEBP, PAYBAK 자동 분류 및 본·지점 합산 지원";font-size:.82rem !important;color:#8B95A1 !important;font-weight:500 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzone"] button{
  background:#E8F3FF !important;border:none !important;color:#3182F6 !important;border-radius:10px !important;font-weight:700 !important;padding:6px 14px !important;font-size:0 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_drop [data-testid="stFileUploaderDropzone"] button::after{
  content:"파일 선택";font-size:.86rem !important;font-weight:700 !important;color:#3182F6 !important;}
</style>
"""


def page_header(crumbs: list, chips_html: str, title: str, sub: str) -> str:
    """토스 웹 스타일 화면 머리: 위치 표시(›) + 오른쪽 꼬리표 + 큰 제목 + 한 줄 설명."""
    crumb = " <span class='sep'>›</span> ".join(crumbs)
    return (f"<div class='ecx-top'><div class='ecx-crumb'>{crumb}</div><div class='ecx-chips'>{chips_html}</div></div>"
            f"<div class='ecx-h1'>{title}</div><div class='ecx-sub'>{sub}</div>")


def kpi_row(items: list) -> str:
    """요약 카드 한 줄: [(라벨, 값, 보조, 'money'|'money biz'|'')] — 마지막 money 카드는 토스 차콜 네이비(#191F28)."""
    n = len(items)
    cols = " ".join(["1fr"] * (n - 1) + ["1.3fr"])
    cells = "".join(
        f"<div class='ecx-kpi {cls}'><div class='l'>{l}</div><div class='v'>{v}</div>" + (f"<div class='s'>{sub}</div>" if sub else "") + "</div>"
        for (l, v, sub, cls) in items
    )
    return f"<div class='ecx-kpis' style='display:grid;grid-template-columns:{cols};gap:12px;margin:2px 0 14px;'>{cells}</div>"


def pay_main_css() -> str:
    return PAY_MAIN_CSS


PAY_MAIN_CSS = """
<style>
[data-testid="stApp"] [data-testid="stMain"],[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],[data-testid="stApp"] [data-testid="stBottom"] > div{background:#F4F6FA !important;}
.ecx-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 6px;}
.ecx-crumb{font-size:.86rem;color:#8B95A1;font-weight:600;} .ecx-crumb .sep{color:#B0B8C1;margin:0 4px;}
.ecx-chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;}
.ecx-chip{display:inline-flex;align-items:center;gap:6px;font-size:.80rem;font-weight:700;padding:5px 12px;border-radius:999px;background:#FFFFFF;border:1px solid #E5E8EB;color:#4E5968;white-space:nowrap;}
.ecx-chip .dot{width:7px;height:7px;border-radius:50%;display:inline-block;background:currentColor;}
.ecx-chip.pay,.ecx-chip.biz{background:#E8F3FF;border-color:transparent;color:#3182F6;}
.ecx-h1{font-size:1.78rem;font-weight:800;color:#191F28;letter-spacing:-.6px;line-height:1.25;margin-top:4px;}
.ecx-sub{font-size:.95rem;color:#4E5968;margin:4px 0 12px;}
.ecx-kpi{background:#FFFFFF;border:1px solid #E5E8EB;border-radius:14px;padding:14px 18px;min-width:0;box-shadow:0 2px 10px rgba(0,27,55,.03);}
.ecx-kpi .l{font-size:.80rem;color:#4E5968;font-weight:600;}
.ecx-kpi .v{font-size:1.35rem;font-weight:800;margin-top:4px;letter-spacing:-.4px;color:#191F28;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ecx-kpi .s{font-size:.76rem;color:#8B95A1;margin-top:2px;}
.ecx-kpi.money,.ecx-kpi.money.biz{background:linear-gradient(135deg,#191F28 0%,#1E293B 100%);border-color:#191F28;box-shadow:0 4px 14px rgba(25,31,40,.18);}
.ecx-kpi.money .l,.ecx-kpi.money.biz .l{color:#B0B8C1;}
.ecx-kpi.money .v,.ecx-kpi.money.biz .v{color:#FFFFFF;font-size:1.48rem;}
.ecx-kpi.money .s,.ecx-kpi.money.biz .s{color:#00C471;font-weight:700;}
.pgx-hint{font-size:.80rem;color:#8B95A1;margin:4px 2px 8px;}
.pgx-card-title{font-size:.98rem;font-weight:800;color:#191F28;margin:0 0 4px;} .pgx-card-title small{font-size:.80rem;color:#8B95A1;font-weight:600;margin-left:6px;}
/* 표 카드 · 내려받기 카드 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_table_card,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_dlcard{background:#FFFFFF;border:1px solid #E5E8EB;border-radius:16px;padding:14px 16px;box-shadow:0 2px 12px rgba(0,27,55,.04);}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_dlcard{margin-top:6px;}
/* ── 개선 2: 상단 액션 툴바 버튼 위계 (토스 웹 컬러 시스템) ── */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]),[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[data-testid="stPopover"] button{
  background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-bottom:1px solid #E5E8EB !important;
  box-shadow:none !important;border-radius:10px !important;min-height:38px !important;transform:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]) p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[data-testid="stPopover"] button p{color:#191F28 !important;font-weight:700 !important;font-size:.86rem !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]):hover:not(:disabled),[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button:hover{border-color:#D1D6DB !important;background:#F2F4F6 !important;}
/* 1순위 Primary 버튼: [+ 행 추가] = 솔리드 토스 블루(#3182F6) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_add_row div.stButton button{
  background:#3182F6 !important;border:none !important;border-bottom:none !important;color:#FFFFFF !important;
  box-shadow:0 2px 8px rgba(49,130,246,.26) !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_add_row div.stButton button:hover{background:#1B64DA !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_add_row div.stButton button p,
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_add_row div.stButton button span{color:#FFFFFF !important;font-weight:800 !important;}
/* 2순위 보조 버튼: [전월 급여/사업소득 불러오기] = 보더리스 토스 그레이(#F2F4F6) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_load_prev_month div.stButton button{
  background:#F2F4F6 !important;border:none !important;border-bottom:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_load_prev_month div.stButton button:hover{background:#E5E8EB !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_load_prev_month div.stButton button p{color:#191F28 !important;font-weight:700 !important;}
/* 3순위 삭제 버튼: [선택한 행 삭제] = 보더리스 토스 소프트 레드(#FFEEEE) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_del_row div.stButton button{
  background:#FFEEEE !important;border:none !important;border-bottom:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_del_row div.stButton button:hover{background:#FFE0E0 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_del_row div.stButton button p{color:#F04452 !important;font-weight:700 !important;}
/* 사업소득 세전/세후 캡슐 토글 스위치 예외 처리 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div.stButton button:not([kind="primary"]){background:#F2F4F6 !important;border:none !important;border-bottom:none !important;box-shadow:none !important;border-radius:999px !important;padding:3px 6px !important;}
/* 경고 상태 칩: 보더리스 토스 시맨틱 틴트 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button{background:#FFEEEE !important;border:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button span{color:#F04452 !important;font-weight:700 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button{background:#FFF5E5 !important;border:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button span{color:#D97706 !important;font-weight:700 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button{background:#E5F9F0 !important;border:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button span{color:#00A660 !important;font-weight:700 !important;}
/* 내려받기: 토스 스타일 파일 꼬리표 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_dl_"] button p::before{display:inline-block;color:#FFFFFF;font-size:10px;font-weight:800;letter-spacing:.3px;padding:2px 6px;border-radius:5px;margin-right:8px;vertical-align:1px;line-height:1.2;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payslips_zip button p::before{content:"PDF";background:#F04452;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payslips_jpg_each button p::before{content:"JPG";background:#3182F6;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payroll_ledger_pdf button p::before{content:"PDF";background:#F04452;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button p::before{content:"XLSX";background:#00C471;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_pdf_each button p::before{content:"PDF";background:#F04452;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_jpg_each button p::before{content:"JPG";background:#3182F6;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_ledger_pdf button p::before{content:"PDF";background:#F04452;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button p::before{content:"XLSX";background:#00C471;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button{background:#E5F9F0 !important;border-color:transparent !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button p{color:#00A660 !important;font-weight:700 !important;}
/* 아래 입력창: 토스 블루 포커스 링 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [data-testid="stChatInput"],
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"]{
  border-radius:14px !important;border:1.5px solid #90C2FF !important;box-shadow:0 4px 16px rgba(49,130,246,.08) !important;background:#FFFFFF !important;}
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"]:focus-within{border-color:#3182F6 !important;box-shadow:0 4px 20px rgba(49,130,246,.16) !important;}
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"] > div{border-color:transparent !important;}
/* ── 검토보고 · AI 절세 검토 창 (토스 웹 스타일) ── */
.rpx-box{color:#191F28;font-size:.95rem;}
.rpx-h{font-size:1.02rem;font-weight:800;color:#191F28;margin:16px 0 8px;padding-left:10px;border-left:4px solid var(--rpx-acc,#3182F6);line-height:1.35;}
.rpx-box > .rpx-h:first-child{margin-top:2px;}
.rpx-intro{font-size:.86rem;color:#8B95A1;margin:-2px 0 8px 14px;}
.rpx-tbl{width:100%;table-layout:fixed;border-collapse:separate;border-spacing:0;border:1px solid #E5E8EB;border-radius:12px;overflow:hidden;margin:2px 0 6px;}
.rpx-tbl th{background:#F9FAFB;color:#4E5968;font-weight:700;font-size:.80rem;padding:9px 10px;border-bottom:1px solid #E5E8EB;text-align:center;}
.rpx-tbl td{font-size:.90rem;padding:10px 10px;border-bottom:1px solid #F2F4F6;color:#4E5968;font-variant-numeric:tabular-nums;white-space:normal;word-break:keep-all;}
.rpx-tbl tr:last-child td{border-bottom:none;}
.rpx-tbl td.rpx-strong{font-weight:800;color:var(--rpx-acc,#191F28);}
.rpx-note{font-size:.80rem;color:#8B95A1;margin:4px 2px 6px;line-height:1.55;}
.rpx-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:2px 0 6px;}
.rpx-card{border:1px solid #E5E8EB;border-radius:12px;padding:10px 12px;background:#FFFFFF;}
.rpx-card .k{font-size:.78rem;color:#8B95A1;} .rpx-card .v{font-weight:700;margin-top:3px;font-size:.92rem;color:#191F28;}
.rpx-ul{margin:4px 0 6px 2px;padding-left:18px;} .rpx-ul li{font-size:.90rem;line-height:1.65;margin-bottom:2px;color:#4E5968;}
.rpx-ai-cap{font-size:.78rem;color:#8B95A1;text-align:right;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] div.stButton button:not([kind="primary"]),[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] div.stDownloadButton button{background:#FFFFFF !important;border:1px solid #E5E8EB !important;border-bottom:1px solid #E5E8EB !important;box-shadow:none !important;border-radius:10px !important;transform:none !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] div.stButton button:not([kind="primary"]) p,[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] div.stDownloadButton button p{color:#4E5968 !important;font-weight:600 !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_dl_review_pdf_"] div.stDownloadButton button p::before{content:"PDF";display:inline-block;background:#F04452;color:#FFFFFF;font-size:10px;font-weight:800;padding:2px 6px;border-radius:5px;margin-right:8px;vertical-align:1px;line-height:1.2;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_ai_saving_"] div.stButton button{background:#3182F6 !important;border:none !important;box-shadow:0 4px 12px rgba(49,130,246,.30) !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_ai_saving_"] div.stButton button p,[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_ai_saving_"] div.stButton button span{color:#FFFFFF !important;font-weight:800 !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_ai_retry_"] div.stButton button p{color:#3182F6 !important;}
/* 수당 계산기 등 창 안 입력칸 글씨 크게 */
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [data-testid="stNumberInput"] input,[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [data-testid="stTextInput"] input{font-size:17px !important;font-weight:600 !important;color:#191F28 !important;height:42px;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [data-testid="stSelectbox"] [data-baseweb="select"] div{font-size:16px !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [data-testid="stWidgetLabel"] p{font-size:14px !important;font-weight:600 !important;color:#4E5968 !important;}
</style>
"""
