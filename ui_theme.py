"""
화면 디자인 B안 — 공통 디자인 기준 (색·글자·버튼·사이드바)

- 색은 의미에만: 브랜드 네이비 1색 + 메뉴별 포인트색(에이전트 인디고 · 통합고용 에메랄드 · 급여 블루 · 사업소득 바이올렛)
- 버튼 위계: 주요(채움) 1개 · 일반(테두리) · 지우기(빨강 테두리)
- 이모티콘 대신 선 아이콘(SVG), 상태는 색 점 + 글자
이 파일은 사이드바(1단계)부터 적용하고, 본문은 단계적으로 옮깁니다.
"""
from __future__ import annotations

TOKENS = {
    "ink": "#0F172A", "body": "#334155", "muted": "#64748B", "faint": "#94A3B8",
    "line": "#E4E8F0", "line2": "#EEF1F6", "canvas": "#F4F6FA",
    "brand": "#1E3A8A", "brand2": "#2B50B8", "brandsoft": "#EEF3FF",
    "agent": "#4F46E5", "agentsoft": "#EEF0FF",
    "ec": "#0F9F6E", "ecsoft": "#E8F7F0",
    "pay": "#2563EB", "paysoft": "#EAF1FF",
    "biz": "#7C3AED", "bizsoft": "#F3EEFF",
    "ok": "#16A34A", "warn": "#C27803", "bad": "#DC2626",
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
    """사이드바 묶음 제목: 선 아이콘 + 작은 회색 제목 + (오른쪽) 상태 꼬리표."""
    ic = icon(icon_name) if icon_name else ""
    return f"<div class='sb-card-title'><span class='sb-t'>{ic}{text}</span>{pill}</div>"


def brand_html() -> str:
    return (
        "<div class='sbx-brand'><div class='sbx-logo'>" + icon("scale", 18, "#ffffff") + "</div>"
        "<div><div class='sbx-brand-t'>세무 에이전트</div><div class='sbx-brand-s'>세무사 사무실 업무 도구</div></div></div>"
    )


SIDEBAR_CSS = """
<style>
/* ═════════ B안 사이드바 ═════════ */
[data-testid="stApp"] section[data-testid="stSidebar"]{background:#FFFFFF !important;border-right:1px solid #E4E8F0 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"]{padding-top:.4rem !important;}
/* 묶음 카드 → 테두리 없는 구역 + 위쪽 얇은 구분선 */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not([class*="st-key-"]),[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] > .st-key-ec_biz{
  background:transparent !important;border:none !important;border-top:1px solid #EEF1F6 !important;border-radius:0 !important;
  box-shadow:none !important;padding:12px 2px 6px !important;margin-bottom:2px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stLayoutWrapper"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]{border-top:none !important;padding:0 !important;}
/* 묶음 제목: 작은 회색 + 선 아이콘 */
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-card-title{font-size:.80rem !important;font-weight:700 !important;color:#64748B !important;letter-spacing:.1px !important;margin-bottom:6px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-card-title .sb-t{display:inline-flex;align-items:center;gap:6px;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-green,[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-amber,[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-pro,
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-green,[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-orange{
  font-size:.70rem !important;font-weight:700 !important;padding:1px 8px !important;border-radius:999px !important;border:none !important;white-space:nowrap;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-green,[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-green{background:#EAF8EF !important;color:#15803D !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-amber,[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-badge-orange{background:#FFF6E5 !important;color:#C27803 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .sb-badge-pro{background:#EEF3FF !important;color:#1E3A8A !important;}
/* 로고 */
.sbx-brand{display:flex;align-items:center;gap:10px;padding:2px 2px 10px;}
.sbx-logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#1E3A8A,#3B6FE0);display:flex;align-items:center;justify-content:center;}
.sbx-brand-t{font-size:1.05rem;font-weight:800;color:#0F172A;letter-spacing:-.3px;line-height:1.2;}
.sbx-brand-s{font-size:.76rem;color:#64748B;font-weight:500;}
/* 메뉴 3개: 세로 목록, 선택된 메뉴만 연한 바탕 + 포인트색 */
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button{
  justify-content:flex-start !important;background:transparent !important;border:none !important;box-shadow:none !important;
  color:#334155 !important;min-height:38px !important;height:38px !important;padding:0 12px !important;border-radius:10px !important;font-weight:600 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button p{color:inherit !important;font-weight:inherit !important;font-size:.95rem !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button:hover{background:#F4F6FA !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_top_mode_calendar div.stButton button[kind="primary"]{background:#E8F3FF !important;color:#3182F6 !important;font-weight:800 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_top_mode_agent div.stButton button[kind="primary"]{background:#EEF0FF !important;color:#4F46E5 !important;font-weight:800 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_top_mode_credit div.stButton button[kind="primary"]{background:#E8F7F0 !important;color:#0B7A55 !important;font-weight:800 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_top_mode_payroll div.stButton button[kind="primary"]{background:#EAF1FF !important;color:#2563EB !important;font-weight:800 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_nav{gap:2px !important;margin-bottom:6px !important;}
/* 일반 버튼: 얇은 테두리·평평 */
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button,[data-testid="stApp"] section[data-testid="stSidebar"] div.stDownloadButton > button,[data-testid="stApp"] section[data-testid="stSidebar"] a[data-testid="stBaseLinkButton-secondary"]{
  min-height:34px !important;height:auto !important;border-radius:8px !important;border:1px solid #E4E8F0 !important;border-bottom:1px solid #E4E8F0 !important;
  background:#FFFFFF !important;box-shadow:none !important;color:#334155 !important;font-weight:600 !important;transform:none !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button p,[data-testid="stApp"] section[data-testid="stSidebar"] div.stDownloadButton > button p,[data-testid="stApp"] section[data-testid="stSidebar"] a[data-testid="stBaseLinkButton-secondary"] p{
  font-size:.86rem !important;font-weight:600 !important;color:inherit !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button:hover,[data-testid="stApp"] section[data-testid="stSidebar"] div.stDownloadButton > button:hover{background:#F7F9FC !important;border-color:#CBD5E1 !important;color:#0F172A !important;}
/* 주요 버튼(사이드바): 네이비 채움 */
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button[kind="primary"]{background:#1E3A8A !important;border-color:#1E3A8A !important;color:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] div.stButton button[kind="primary"] p{color:#FFFFFF !important;}
/* 지우는 버튼: 빨강 테두리 */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_ec_sidebar_reset_ask div.stButton button,[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_reset_ask div.stButton button,
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_clear_current_room div.stButton button{color:#DC2626 !important;border-color:#F6C9C9 !important;background:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_clear_current_room{border-bottom:none !important;padding-bottom:0 !important;margin-bottom:4px !important;}
/* 인건비: 당월 검토보고(주요) · 통합고용 연동(연한 초록) */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button{background:#1E3A8A !important;border-color:#1E3A8A !important;color:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button p{color:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_bridge_credit div.stButton button{background:#E8F7F0 !important;border-color:#BFE8D6 !important;color:#0B7A55 !important;}
/* 인건비: 업무 화면 전환(급여명세서/사업소득) = 회색 바탕 위 흰 알약 */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_pay_seg{background:#EEF1F6 !important;border-radius:9px !important;padding:3px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_pay_seg [data-testid="stHorizontalBlock"]{gap:3px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"] div.stButton button{background:transparent !important;border:none !important;box-shadow:none !important;color:#64748B !important;min-height:30px !important;height:30px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_submode_emp_active div.stButton button{background:#FFFFFF !important;color:#2563EB !important;box-shadow:0 1px 2px rgba(15,23,42,.12) !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-btn_pay_submode_free_active div.stButton button{background:#FFFFFF !important;color:#7C3AED !important;box-shadow:0 1px 2px rgba(15,23,42,.12) !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"] div.stButton button p{color:inherit !important;font-weight:700 !important;}
/* 대화방 목록: 왼쪽 정렬 목록형, 지금 방만 인디고 */
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button{justify-content:flex-start !important;border:none !important;background:transparent !important;min-height:32px !important;height:32px !important;padding:0 10px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button p{font-size:.84rem !important;font-weight:500 !important;color:#334155 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button:hover{background:#F4F6FA !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"][class*="_active"] div.stButton button{background:#EEF0FF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [class*="st-key-room_btn_"][class*="_active"] div.stButton button p{color:#4F46E5 !important;font-weight:700 !important;}
/* 입력칸·선택칸 */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="input"],[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="select"] > div{border-radius:8px !important;border-color:#E4E8F0 !important;background:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="input"] input{background:#FFFFFF !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] label p{font-size:.80rem !important;color:#64748B !important;font-weight:500 !important;}
/* 법령 상태 줄: 평평한 작은 점 */
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-status-row,[data-testid="stApp"] section[data-testid="stSidebar"] .pay-law-row{background:#FBFCFE !important;border:1px solid #EEF1F6 !important;box-shadow:none !important;border-radius:8px !important;padding:6px 10px !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-status-left{font-size:.82rem !important;font-weight:600 !important;color:#0F172A !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d{width:8px !important;height:8px !important;border:none !important;box-shadow:none !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d.green{background:#16A34A !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d.orange{background:#F59E0B !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d.yellow{background:#3B82F6 !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] .ec-law-led-3d.gray{background:#CBD5E1 !important;}
/* 탭(내려받기/불러오기) */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="tab-list"] button p{font-size:.82rem !important;}
[data-testid="stApp"] section[data-testid="stSidebar"] [data-baseweb="tab-highlight"]{background:#0F172A !important;}
/* 맨 아래 결제·API 키 */
[data-testid="stApp"] section[data-testid="stSidebar"] .st-key-sbx_footer{border-top:1px solid #EEF1F6;padding-top:10px;margin-top:4px;}
/* 스위치 색 */
[data-testid="stApp"] section[data-testid="stSidebar"] [data-testid="stToggle"] div[role="checkbox"][aria-checked="true"]{background:#2B50B8 !important;}
/* 보강: 선택된 메뉴 글자색 · 왼쪽 정렬 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button > div{justify-content:flex-start !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_top_mode_calendar div.stButton button[kind="primary"] p{color:#3182F6 !important;font-weight:800 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_top_mode_agent div.stButton button[kind="primary"] p{color:#4F46E5 !important;font-weight:800 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_top_mode_credit div.stButton button[kind="primary"] p{color:#0B7A55 !important;font-weight:800 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_top_mode_payroll div.stButton button[kind="primary"] p{color:#2563EB !important;font-weight:800 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button[kind="primary"] span{color:inherit !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button > div{justify-content:flex-start !important;}
/* 보강: 각 화면 전용 3D 버튼도 평평한 테두리 버튼으로 통일 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button:not([kind="primary"]),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stDownloadButton > button{border:1px solid #E4E8F0 !important;border-bottom:1px solid #E4E8F0 !important;box-shadow:none !important;background:#FFFFFF !important;transform:none !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] div.stButton button:disabled{background:#F7F9FC !important;color:#94A3B8 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_ec_sidebar_reset_ask div.stButton button:not(:disabled),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_reset_ask div.stButton button:not(:disabled),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_clear_current_room div.stButton button{color:#DC2626 !important;border-color:#F6C9C9 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_ec_sidebar_reset_ask div.stButton button:not(:disabled) p,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_reset_ask div.stButton button:not(:disabled) p,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_clear_current_room div.stButton button p{color:#DC2626 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button{background:#1E3A8A !important;border-color:#1E3A8A !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_monthly_report div.stButton button p{color:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_bridge_credit div.stButton button{background:#E8F7F0 !important;border-color:#BFE8D6 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_bridge_credit div.stButton button p{color:#0B7A55 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"] div.stButton button,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"] div.stButton button{border:none !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_top_mode_"] div.stButton button:not([kind="primary"]),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"]:not([class*="_active"]) div.stButton button,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-btn_pay_submode_"]:not([class*="_active"]) div.stButton button{background:transparent !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [class*="st-key-room_btn_"][class*="_active"] div.stButton button{background:#EEF0FF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_submode_emp_active div.stButton button,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] .st-key-btn_pay_submode_free_active div.stButton button{background:#FFFFFF !important;}
/* 입력칸 테두리 · 폼 상자 없애기 */
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-baseweb="input"],[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-baseweb="select"] > div,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-baseweb="base-input"]{border:1px solid #E4E8F0 !important;border-radius:8px !important;background:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-baseweb="input"] [data-baseweb="base-input"]{border:none !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stForm"]{border:none !important;padding:0 !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stExpander"] details{border:1px solid #EEF1F6 !important;border-radius:8px !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stTextInputRootElement"],[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stNumberInputContainer"],[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stSelectbox"] div:has(> input),[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stDateInput"] > div > div{border:1px solid #E4E8F0 !important;border-radius:8px !important;background:#FFFFFF !important;}
[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stTextInputRootElement"]:focus-within,[data-testid="stApp"][data-testid="stApp"] section[data-testid="stSidebar"][data-testid="stSidebar"] [data-testid="stNumberInputContainer"]:focus-within{border-color:#2B50B8 !important;}
</style>
"""


def ec_main_css() -> str:
    """통합고용세액공제 본문 B안 (머리·진행 표시·카드·버튼·동작 바). 통합고용 화면에서만 넣습니다."""
    return EC_MAIN_CSS


EC_MAIN_CSS = """
<style>
[data-testid="stApp"] [data-testid="stMain"],[data-testid="stApp"] [data-testid="stAppScrollToBottomContainer"],[data-testid="stApp"] [data-testid="stBottom"] > div{background:#F4F6FA !important;}
/* 머리: 위치 표시 + 꼬리표 + 큰 제목 */
.ecx-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 6px;}
.ecx-crumb{font-size:.86rem;color:#64748B;font-weight:500;}
.ecx-crumb .sep{color:#94A3B8;margin:0 4px;}
.ecx-chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;}
.ecx-chip{display:inline-flex;align-items:center;gap:6px;font-size:.80rem;font-weight:600;padding:4px 11px;border-radius:999px;background:#FFFFFF;border:1px solid #E4E8F0;color:#334155;white-space:nowrap;}
.ecx-chip.ec{background:#E8F7F0;border-color:#C8EBDB;color:#0B7A55;}
.ecx-chip .dot{width:7px;height:7px;border-radius:50%;background:#0F9F6E;display:inline-block;}
.ecx-h1{font-size:1.75rem;font-weight:800;color:#0F172A;letter-spacing:-.6px;line-height:1.25;margin-top:4px;}
.ecx-sub{font-size:.95rem;color:#64748B;margin:4px 0 12px;}
/* 진행 표시: 번호 원 + 이름 + 상태 글자 + 잇는 선 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_stepper{background:#FFFFFF;border:1px solid #E4E8F0;border-radius:14px;padding:10px 18px;margin-bottom:6px;box-shadow:0 1px 2px rgba(15,23,42,.04);}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button{display:flex !important;align-items:center !important;justify-content:flex-start !important;gap:12px !important;
  background:transparent !important;border:none !important;box-shadow:none !important;min-height:52px !important;height:52px !important;padding:0 2px !important;transform:none !important;opacity:1 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button > div{flex:0 1 auto !important;width:auto !important;min-width:0 !important;justify-content:flex-start !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button::before{flex:none;width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-weight:800;font-size:.9rem;border:2px solid #E4E8F0;color:#94A3B8;background:#FFFFFF;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button::after{content:"";flex:1;height:2px;background:#E4E8F0;margin-left:6px;border-radius:2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"][class*="_4"] div.stButton button::after{display:none;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button p{font-size:.95rem !important;font-weight:700 !important;color:#94A3B8 !important;text-align:left !important;line-height:1.25 !important;white-space:nowrap;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button p::after{display:block;font-size:.76rem;font-weight:600;margin-top:2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_1 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_1 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_1 div.stButton button::before{content:"1";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_2 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_2 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_2 div.stButton button::before{content:"2";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_3 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_3 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_3 div.stButton button::before{content:"3";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_now_4 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_open_4 div.stButton button::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_step_nav_wait_4 div.stButton button::before{content:"4";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button::before{content:"✓";background:#0F9F6E;border-color:#0F9F6E;color:#FFFFFF;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button::after{background:#0F9F6E;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button p{color:#0F172A !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_done_"] div.stButton button p::after{content:"완료";color:#0F9F6E;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button::before{border-color:#0F9F6E;color:#0F9F6E;box-shadow:0 0 0 4px #D5F2E5;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button p{color:#0F172A !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_now_"] div.stButton button p::after{content:"진행 중";color:#0F9F6E;font-weight:800;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_open_"] div.stButton button p{color:#334155 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_open_"] div.stButton button p::after{content:"눌러서 이동";color:#94A3B8;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_wait_"] div.stButton button p::after{content:"대기";color:#CBD5E1;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button:hover:not(:disabled) p{color:#0B7A55 !important;}
/* 본문 버튼: 평평한 테두리 · 주요(다음)만 초록 채움 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]),[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button{background:#FFFFFF !important;border:1px solid #E4E8F0 !important;border-bottom:1px solid #E4E8F0 !important;
  box-shadow:0 1px 2px rgba(15,23,42,.04) !important;border-radius:9px !important;color:#334155 !important;transform:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]) p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button p{color:#334155 !important;font-weight:600 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]):hover:not(:disabled),[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button:hover{border-color:#CBD5E1 !important;background:#F7F9FC !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"]{background:#0F9F6E !important;border:1px solid #0F9F6E !important;border-bottom:1px solid #0F9F6E !important;border-radius:9px !important;box-shadow:0 1px 2px rgba(15,159,110,.3) !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"]:hover{background:#0B7A55 !important;border-color:#0B7A55 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button[kind="primary"] p{color:#FFFFFF !important;font-weight:700 !important;}
/* 진행 표시 버튼은 위 공통 버튼 규칙보다 우선 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_step_nav_"] div.stButton button:not([kind="primary"]){background:transparent !important;border:none !important;box-shadow:none !important;}
/* 지우는 버튼: 빨강 테두리 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_del_rows_"] div.stButton button:not(:disabled){border-color:#F3C4C4 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_del_rows_"] div.stButton button:not(:disabled) p{color:#DC2626 !important;}
/* 내려받기: 색 대신 파일 꼬리표 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stDownloadButton button p::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stButton button p::before{content:"PDF";}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_docx div.stDownloadButton button p::before{content:"DOCX";background:#2D5BD3 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_xlsx div.stDownloadButton button p::before{content:"XLSX";background:#1E8E4E !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_md div.stDownloadButton button p::before{content:"MD";background:#334155 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] button p::before,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ecx_dl_"] button p::before{display:inline-block;background:#E0484A;color:#FFFFFF;font-size:10px;font-weight:800;
  letter-spacing:.3px;padding:2px 5px;border-radius:4px;margin-right:8px;vertical-align:1px;line-height:1.2;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stDownloadButton button{background:#FFFFFF !important;border:1px solid #E4E8F0 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-ec_btn_pdf"] div.stDownloadButton button p{color:#0F172A !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dl_xlsx div.stDownloadButton button{background:linear-gradient(180deg,#F5FCF8,#EAF8F0) !important;border-color:#BFE3CE !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ec_btn_pdf_rep_bot div.stDownloadButton button{background:linear-gradient(180deg,#F7FAFF,#EEF3FF) !important;border-color:#C9D7F5 !important;}
/* 카드: 내려받기 카드 · 아래 동작 바 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_dlcard{background:#FFFFFF;border:1px solid #E4E8F0;border-radius:14px;padding:12px 14px;margin-top:10px;box-shadow:0 1px 2px rgba(15,23,42,.04);}
.ecx-dl-title{font-size:.95rem;font-weight:800;color:#0F172A;margin:0 0 2px;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-ecx_actionbar{background:#FFFFFF;border:1px solid #E4E8F0;border-radius:14px;padding:10px 14px;margin-top:12px;box-shadow:0 -2px 10px rgba(15,23,42,.04);}
/* 요약 카드 (3·4단계) */
.ecx-kpi{background:#FFFFFF;border:1px solid #E4E8F0;border-radius:12px;padding:12px 16px;}
.ecx-kpi .l{font-size:.80rem;color:#64748B;font-weight:600;}
.ecx-kpi .v{font-size:1.4rem;font-weight:800;margin-top:3px;letter-spacing:-.4px;color:#0F172A;font-variant-numeric:tabular-nums;}
.ecx-kpi .s{font-size:.76rem;color:#64748B;margin-top:2px;}
.ecx-kpi.money{background:#0B1B3F;border-color:#0B1B3F;}
.ecx-kpi.money .l{color:#A9B8D8;} .ecx-kpi.money .v{color:#FFFFFF;font-size:1.5rem;} .ecx-kpi.money .s{color:#7EE2B0;}
/* 2단계 연도 머리 · 요약 줄 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-year-header{background:#FFFFFF !important;border:1px solid #E4E8F0 !important;border-left:4px solid #1E3A8A !important;border-radius:10px !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-year-title{color:#0F172A !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-bar{background:#FFFFFF !important;border:1px solid #E4E8F0 !important;border-left:4px solid #0F9F6E !important;border-radius:12px !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-chip{background:#F7F9FC !important;border:1px solid #EEF1F6 !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-chip .kpi-tag{background:#FFFFFF !important;color:#334155 !important;border:1px solid #E4E8F0 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-total-pill{background:#0B1B3F !important;color:#FFFFFF !important;border:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-kpi-total-pill b{color:#7EE2B0 !important;}
/* 표 머리: 진한 남색 → 연한 회색 (글자 진하게) */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-matrix-tbl th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-inc-tbl th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap th,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap th strong,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap th b{background:#F2F5FA !important;color:#0F172A !important;border:1px solid #E4E8F0 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-matrix-tbl th.active-yr{background:#E8F7F0 !important;color:#0B7A55 !important;box-shadow:inset 0 -3px 0 #0F9F6E !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-matrix-tbl,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-inc-tbl,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap table{border-top:1px solid #CBD5E1 !important;border-bottom:1px solid #CBD5E1 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-matrix-tbl td,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-inc-tbl td,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-docs td,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .ec-agent-report-wrap td{border-color:#E4E8F0 !important;}
</style>
"""


def page_header(crumbs: list, chips_html: str, title: str, sub: str) -> str:
    """B안 화면 머리: 위치 표시(›) + 오른쪽 꼬리표 + 큰 제목 + 한 줄 설명."""
    crumb = " <span class='sep'>›</span> ".join(crumbs)
    return (f"<div class='ecx-top'><div class='ecx-crumb'>{crumb}</div><div class='ecx-chips'>{chips_html}</div></div>"
            f"<div class='ecx-h1'>{title}</div><div class='ecx-sub'>{sub}</div>")


def kpi_row(items: list) -> str:
    """요약 카드 한 줄: [(라벨, 값, 보조, 'money'|'money biz'|'')] — 마지막 money 카드는 진한 네이비(사업소득은 진보라)."""
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
.ecx-crumb{font-size:.86rem;color:#64748B;font-weight:500;} .ecx-crumb .sep{color:#94A3B8;margin:0 4px;}
.ecx-chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;}
.ecx-chip{display:inline-flex;align-items:center;gap:6px;font-size:.80rem;font-weight:600;padding:4px 11px;border-radius:999px;background:#FFFFFF;border:1px solid #E4E8F0;color:#334155;white-space:nowrap;}
.ecx-chip .dot{width:7px;height:7px;border-radius:50%;display:inline-block;background:currentColor;}
.ecx-chip.pay{background:#EAF1FF;border-color:#D3E2FF;color:#2563EB;} .ecx-chip.biz{background:#F3EEFF;border-color:#E3D6FF;color:#7C3AED;}
.ecx-h1{font-size:1.75rem;font-weight:800;color:#0F172A;letter-spacing:-.6px;line-height:1.25;margin-top:4px;}
.ecx-sub{font-size:.95rem;color:#64748B;margin:4px 0 12px;}
.ecx-kpi{background:#FFFFFF;border:1px solid #E4E8F0;border-radius:12px;padding:12px 16px;min-width:0;}
.ecx-kpi .l{font-size:.80rem;color:#64748B;font-weight:600;}
.ecx-kpi .v{font-size:1.32rem;font-weight:800;margin-top:3px;letter-spacing:-.4px;color:#0F172A;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.ecx-kpi .s{font-size:.76rem;color:#64748B;margin-top:2px;}
.ecx-kpi.money{background:#0B1B3F;border-color:#0B1B3F;} .ecx-kpi.money .l{color:#A9B8D8;} .ecx-kpi.money .v{color:#FFFFFF;font-size:1.45rem;} .ecx-kpi.money .s{color:#7EE2B0;}
.ecx-kpi.money.biz{background:#2A1259;border-color:#2A1259;} .ecx-kpi.money.biz .l{color:#C9B8F0;} .ecx-kpi.money.biz .s{color:#C4B5FD;}
.pgx-hint{font-size:.80rem;color:#64748B;margin:2px 2px 6px;}
.pgx-card-title{font-size:.98rem;font-weight:800;color:#0F172A;margin:0 0 4px;} .pgx-card-title small{font-size:.80rem;color:#64748B;font-weight:500;margin-left:6px;}
/* 표 카드 · 내려받기 카드 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_table_card,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_dlcard{background:#FFFFFF;border:1px solid #E4E8F0;border-radius:14px;padding:12px 14px;box-shadow:0 1px 2px rgba(15,23,42,.04);}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_dlcard{margin-top:4px;}
/* 버튼: 평평한 테두리 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]),[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[data-testid="stPopover"] button{background:#FFFFFF !important;border:1px solid #E4E8F0 !important;border-bottom:1px solid #E4E8F0 !important;
  box-shadow:0 1px 2px rgba(15,23,42,.04) !important;border-radius:9px !important;transform:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]) p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[data-testid="stPopover"] button p{color:#334155 !important;font-weight:600 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stButton button:not([kind="primary"]):hover:not(:disabled),[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div.stDownloadButton button:hover{border-color:#CBD5E1 !important;background:#F7F9FC !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_del_row div.stButton button{border-color:#F3C4C4 !important;} [data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_pay_del_row div.stButton button p{color:#DC2626 !important;}
/* 사업소득 세전/세후 캡슐 토글 스위치 예외 처리 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div.stButton button:not([kind="primary"]){background:transparent !important;border:none !important;border-bottom:none !important;box-shadow:none !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] div[class*="st-key-pay_free_sw_"] div.stButton button:not([kind="primary"]) p{color:#FFFFFF !important;font-weight:800 !important;}
/* 경고 상태 칩 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button{background:#FEF1F1 !important;border-color:#F6C9C9 !important;} [data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_red div.stButton button span{color:#DC2626 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button{background:#FFF6E5 !important;border-color:#F9E1B4 !important;} [data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_yellow div.stButton button span{color:#C27803 !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button{background:#EAF8EF !important;border-color:#CDEFD9 !important;} [data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-pay_warnchip_gray div.stButton button span{color:#15803D !important;}
/* 내려받기: 파일 꼬리표 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [class*="st-key-btn_dl_"] button p::before{display:inline-block;color:#FFFFFF;font-size:10px;font-weight:800;letter-spacing:.3px;padding:2px 5px;border-radius:4px;margin-right:8px;vertical-align:1px;line-height:1.2;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payslips_zip button p::before{content:"PDF";background:#E0484A;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payslips_jpg_each button p::before{content:"JPG";background:#C2410C;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_payroll_ledger_pdf button p::before{content:"PDF";background:#E0484A;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button p::before{content:"XLSX";background:#1E8E4E;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_pdf_each button p::before{content:"PDF";background:#E0484A;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_jpg_each button p::before{content:"JPG";background:#C2410C;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_free_ledger_pdf button p::before{content:"PDF";background:#E0484A;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button p::before{content:"XLSX";background:#1E8E4E;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button{background:linear-gradient(180deg,#F5FCF8,#EAF8F0) !important;border-color:#BFE3CE !important;}
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_emp_xlsx div.stDownloadButton button p,[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] .st-key-btn_dl_wehago_free_xlsx div.stDownloadButton button p{color:#14532D !important;font-weight:700 !important;}
/* 아래 입력창 */
[data-testid="stApp"][data-testid="stApp"] [data-testid="stMainBlockContainer"] [data-testid="stChatInput"]{border-radius:14px !important;border:1px solid #E4E8F0 !important;box-shadow:0 4px 14px rgba(15,23,42,.06) !important;background:#FFFFFF !important;}
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"]{border-radius:14px !important;border:1px solid #E4E8F0 !important;box-shadow:0 4px 14px rgba(15,23,42,.06) !important;background:#FFFFFF !important;}
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"]:focus-within{border-color:#2B50B8 !important;}
[data-testid="stApp"] [data-testid="stBottom"] [data-testid="stChatInput"] > div{border-color:transparent !important;}
/* ── 검토보고 · AI 절세 검토 창 (B안) ── */
.rpx-box{color:#0F172A;font-size:.95rem;}
.rpx-h{font-size:1.02rem;font-weight:800;color:#0F172A;margin:16px 0 8px;padding-left:10px;border-left:4px solid var(--rpx-acc,#2563EB);line-height:1.35;}
.rpx-box > .rpx-h:first-child{margin-top:2px;}
.rpx-intro{font-size:.86rem;color:#64748B;margin:-2px 0 8px 14px;}
.rpx-tbl{width:100%;table-layout:fixed;border-collapse:separate;border-spacing:0;border:1px solid #E4E8F0;border-radius:10px;overflow:hidden;margin:2px 0 6px;}
.rpx-tbl th{background:#F7F9FC;color:#64748B;font-weight:700;font-size:.80rem;padding:9px 10px;border-bottom:1px solid #E4E8F0;text-align:center;}
.rpx-tbl td{font-size:.90rem;padding:10px 10px;border-bottom:1px solid #EEF1F6;color:#334155;font-variant-numeric:tabular-nums;white-space:normal;word-break:keep-all;}
.rpx-tbl tr:last-child td{border-bottom:none;}
.rpx-tbl td.rpx-strong{font-weight:800;color:var(--rpx-acc,#0B1B3F);}
.rpx-note{font-size:.80rem;color:#64748B;margin:4px 2px 6px;line-height:1.55;}
.rpx-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:2px 0 6px;}
.rpx-card{border:1px solid #E4E8F0;border-radius:10px;padding:10px 12px;background:#FFFFFF;}
.rpx-card .k{font-size:.78rem;color:#64748B;} .rpx-card .v{font-weight:700;margin-top:3px;font-size:.92rem;}
.rpx-ul{margin:4px 0 6px 2px;padding-left:18px;} .rpx-ul li{font-size:.90rem;line-height:1.65;margin-bottom:2px;color:#334155;}
.rpx-ai-cap{font-size:.78rem;color:#64748B;text-align:right;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] div.stButton button:not([kind="primary"]),[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] div.stDownloadButton button{background:#FFFFFF !important;border:1px solid #E4E8F0 !important;border-bottom:1px solid #E4E8F0 !important;box-shadow:none !important;border-radius:9px !important;transform:none !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] div.stButton button:not([kind="primary"]) p,[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] div.stDownloadButton button p{color:#334155 !important;font-weight:600 !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_dl_review_pdf_"] div.stDownloadButton button p::before{content:"PDF";display:inline-block;background:#E0484A;color:#FFFFFF;font-size:10px;font-weight:800;padding:2px 5px;border-radius:4px;margin-right:8px;vertical-align:1px;line-height:1.2;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_ai_saving_"] div.stButton button{background:linear-gradient(135deg,#4F46E5,#7C3AED) !important;border:none !important;box-shadow:0 4px 12px rgba(99,102,241,.35) !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_ai_saving_"] div.stButton button p,[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_ai_saving_"] div.stButton button span{color:#FFFFFF !important;font-weight:800 !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [class*="st-key-btn_ai_retry_"] div.stButton button p{color:#4F46E5 !important;}
/* 수당 계산기 등 창 안 입력칸 글씨 크게 */
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [data-testid="stNumberInput"] input,[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [data-testid="stTextInput"] input{font-size:17px !important;font-weight:600 !important;color:#0F172A !important;height:42px;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [data-testid="stSelectbox"] [data-baseweb="select"] div{font-size:16px !important;}
[data-testid="stDialog"][data-testid="stDialog"] [role="dialog"] [data-testid="stWidgetLabel"] p{font-size:14px !important;font-weight:600 !important;color:#334155 !important;}
</style>
"""
