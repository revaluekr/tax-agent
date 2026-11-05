import os
import re
import ast
import gzip
import zlib
import math
import time
import contextvars
import json
import threading
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

_KST_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")
HIDDEN_DATE_DIRECTIVE_MARKER = "[시스템 자동 주입 기준일·귀속연도 판단 지침"

def get_kst_today_context() -> dict:
    """대한민국 표준시(Asia/Seoul) 기준 당일 날짜·요일·당해 귀속연도 정보를 실시간으로 반환합니다."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    wd = _KST_WEEKDAYS[now.weekday()]
    return {
        "dt": now,
        "year": now.year,
        "prev_year": now.year - 1,
        "prev2_year": now.year - 2,
        "next_year": now.year + 1,
        "ymd": now.strftime("%Y%m%d"),
        "ymd_dash": now.strftime("%Y-%m-%d"),
        "weekday_kr": f"{wd}요일",
        "weekday_short": wd,
        "dot_full": f"{now.strftime('%Y.%m.%d')} ({wd}요일)",
        "kr_full": f"{now.strftime('%Y년 %m월 %d일')} ({wd}요일)",
    }

def _sort_law_candidates_for_today(cands: list[dict]) -> list[dict]:
    """
    법제처 법령 목록(cands)에서 이미 공포되었으나 시행일이 내년 이후(예: 2027.01.01)인 '미시행(시행예정) 버전'보다
    오늘(KST) 기준 실제로 시행 중인 '현행 시행 법령(시행일자 <= 오늘)'을 1순위로 정렬합니다.
    """
    if not cands:
        return []
    today_int = int(get_kst_today_context()["ymd"])
    def _sort_key(item: dict):
        enf_s = re.sub(r"\D", "", str(item.get("시행일자", "") or ""))
        prom_s = re.sub(r"\D", "", str(item.get("공포일자", "") or ""))
        enf_i = int(enf_s) if len(enf_s) == 8 and enf_s.isdigit() else 0
        prom_i = int(prom_s) if len(prom_s) == 8 and prom_s.isdigit() else 0
        is_enforced_now = 1 if (0 < enf_i <= today_int) else 0
        return (is_enforced_now, enf_i, prom_i)
    return sorted(cands, key=_sort_key, reverse=True)

def get_kst_now() -> datetime:
    """한국 표준시(KST, Asia/Seoul) 기준 현재 시각을 반환합니다."""
    return datetime.now(ZoneInfo("Asia/Seoul"))

def get_kst_today_info() -> tuple[str, str, int]:
    """(YYYY.MM.DD (X요일), YYYY년 MM월 DD일 (X요일), YYYY) 반환 (하위 호환용)"""
    ctx = get_kst_today_context()
    return ctx["dot_full"], ctx["kr_full"], ctx["year"]

def detect_query_attribution_years(user_query: str = "", full_user_input: str = "") -> dict:
    """
    현재 질문(user_query)과 직전 대화 맥락(full_user_input)에서 귀속연도를 정밀 감지합니다.
    - '20년 근무', '15년 재직', '30년 만기', '15년 영위' 등 기간 표현이 20XX년 귀속연도로 오탐되는 것을 원천 차단합니다.
    - 현재 질문에 연도가 생략되었더라도 직전 대화 맥락에 과거 귀속연도가 지정된 경우 이를 보존합니다.
    """
    kst = get_kst_today_context()
    cur_yr = kst["year"]
    q_raw = user_query or ""
    hist_raw = full_user_input or ""
    if "[현재 사용자 질문]:" in q_raw:
        parts = q_raw.rsplit("[현재 사용자 질문]:", 1)
        if not hist_raw:
            hist_raw = parts[0]
        q_raw = parts[1]
    if "========================================" in q_raw:
        q_raw = q_raw.split("========================================")[0]
    if "========================================" in hist_raw:
        hist_raw = hist_raw.split("========================================")[0]
    if HIDDEN_DATE_DIRECTIVE_MARKER in q_raw:
        q_raw = q_raw.split(HIDDEN_DATE_DIRECTIVE_MARKER)[0]
    if HIDDEN_DATE_DIRECTIVE_MARKER in hist_raw:
        hist_raw = hist_raw.split(HIDDEN_DATE_DIRECTIVE_MARKER)[0]

    past_years = set()
    cur_years = set()
    future_years = set()

    _DURATION_SUFFIX = (
        r"(?!\s*(?:간|동안|이상|미만|이하|초과|차|이내|보유|거주|근속|근무|재직|납입|만기|상환|할부|"
        r"분할|임대|영위|운영|경력|연속|유예|거치|소멸시효|제척기간|개월|세|살|령|형|징역))"
    )

    # 1) 4자리 연도 감지 (예: 2024년, 2027년, 2024.05.10, 2024귀속 등)
    for m4 in re.finditer(rf"(?<!\d)(20[123]\d)\s*(?:년|년도|귀속|기|사업연도|과세기간|\.|\-|/){_DURATION_SUFFIX}", q_raw):
        yr_val = int(m4.group(1))
        if 2010 <= yr_val < cur_yr:
            past_years.add(yr_val)
        elif yr_val == cur_yr:
            cur_years.add(yr_val)
        elif yr_val > cur_yr:
            future_years.add(yr_val)

    # 2) 2자리 연도 감지 (예: '24년, 24년 귀속, 24년도, 24년분, 24년 5월 등 — '20년 근무', '15년 재직', '30년 만기' 등 기간 표현 원천 배제)
    for m2 in re.finditer(
        rf"(?<![0-9제])(?:'([123]\d)\s*년|([123]\d)\s*(?:년도|년\s*귀속|귀속|년분|기|사업연도|과세기간|년\s*\d{{1,2}}\s*월|년도에|년도의|년분?부터)){_DURATION_SUFFIX}",
        q_raw,
    ):
        yr_2d = int(m2.group(1) or m2.group(2))
        yr_val = 2000 + yr_2d
        if 2015 <= yr_val < cur_yr:
            past_years.add(yr_val)
        elif yr_val == cur_yr:
            cur_years.add(yr_val)
        elif yr_val > cur_yr:
            future_years.add(yr_val)

    # 3) 상대적 연도 표현 감지 ('작년', '재작년', '올해', '내년')
    if re.search(r"(작년|전년도|전사업연도|직전\s*연도|직전\s*사업연도|지난\s*해)", q_raw):
        past_years.add(cur_yr - 1)
    if re.search(r"(재작년|전전년도|전전사업연도)", q_raw):
        past_years.add(cur_yr - 2)
    if re.search(r"(올해|금년|이번\s*연도|당해\s*연도|현행)", q_raw):
        cur_years.add(cur_yr)
    if re.search(r"(내년|명년|다음\s*연도|차기\s*사업연도)", q_raw):
        future_years.add(cur_yr + 1)

    # 4) 멀티턴 대화 맥락의 과거 귀속연도 감지 (4자리 '2024년' 및 2자리 "'24년", '24년 귀속' 모두 지원, 기간 수식어 배제)
    _hist_4d = {
        int(m.group(1))
        for m in re.finditer(rf"(?<!\d)(20[12]\d)\s*(?:년\s*귀속|귀속|사업연도|과세기간|년분|년도|년){_DURATION_SUFFIX}", hist_raw)
        if 2015 <= int(m.group(1)) < cur_yr
    }
    _hist_2d = {
        2000 + int(m.group(1) or m.group(2))
        for m in re.finditer(
            rf"(?<![0-9제])(?:'([12]\d)\s*년|([12]\d)\s*(?:년도|년\s*귀속|귀속|년분|기|사업연도|과세기간)){_DURATION_SUFFIX}",
            hist_raw,
        )
        if 2015 <= (2000 + int(m.group(1) or m.group(2))) < cur_yr
    }
    history_past_years = sorted(_hist_4d | _hist_2d)

    has_retro_kw = bool(re.search(r"(경정청구|기한후신고|수정신고|구법|종전\s*규정|종전규정|연혁법령|사후관리|추가공제)", q_raw))
    sorted_past = sorted(past_years)
    sorted_cur = sorted(cur_years)
    sorted_future = sorted(future_years)

    if sorted_past and not sorted_cur and not sorted_future:
        mode = "PAST_ONLY"
    elif sorted_past and (sorted_cur or sorted_future):
        mode = "MIXED_PAST_AND_CURRENT"
    elif sorted_future and not sorted_past and not sorted_cur:
        mode = "FUTURE_ONLY"
    elif history_past_years and not sorted_cur:
        mode = "MIXED_PAST_AND_CURRENT"
        sorted_past = history_past_years
    else:
        mode = "DEFAULT_CURRENT"

    return {
        "mode": mode,
        "past_years": sorted_past,
        "history_past_years": history_past_years,
        "cur_years": sorted_cur,
        "future_years": sorted_future,
        "has_retro_kw": has_retro_kw,
        "current_year": cur_yr,
        "dot_full": kst["dot_full"],
    }

def build_hidden_date_law_directive(user_query: str = "") -> str:
    """
    [통합 최종판] 사용자에게는 보이지 않지만 모든 질문(프롬프트)에 자동 부착되는
    [질문 내 연도 자동 감지 4모드 + 25년 과거착각·27년 미시행 조기적용 양방향 차단 + 신고기한 과세기간 매핑 지침]
    """
    info = detect_query_attribution_years(user_query)
    dot_full = info["dot_full"]
    cur_yr = info["current_year"]
    prev_yr = cur_yr - 1
    prev2_yr = cur_yr - 2
    next_yr = cur_yr + 1
    mode = info["mode"]
    past_yrs = info["past_years"]
    fut_yrs = info["future_years"]
    now_ymd_dot = get_kst_today_context()["dt"].strftime("%Y.%m.%d")

    common_footer = (
        f"• 📌 **[답변 형식 — '1. 결론' 첫 줄 적용 기준 명시]**: `### 1. 결론` 바로 아래 첫 줄에 반드시 "
        f"**\"적용 기준: ○○○○년 귀속(또는 ○○○○.○○.○○ 거래/폐업) · ○○○○.○○.○○ 시행 법령\"**을 한 줄로 먼저 밝힌 뒤 결론을 작성하세요.\n\n"
    )

    if mode == "PAST_ONLY":
        past_str = ", ".join(f"{y}년" for y in past_yrs)
        first_past = past_yrs[0]
        return (
            f"{HIDDEN_DATE_DIRECTIVE_MARKER} — 내부 판단 기준이므로 이 지침 블록 자체를 답변에 그대로 복붙하지 말 것]\n"
            f"• 오늘 날짜(대한민국 KST): 오늘은 {dot_full}입니다. (당해 연도는 {cur_yr}년이나, **이번 질문은 과거 귀속연도({past_str}) 지정 질의**입니다!)\n"
            f"• 🚨 **[최우선 명령 — 과거 귀속연도({past_str}) 구법 적용 및 {cur_yr}년/{next_yr}년 개정세법 소급 왜곡 절대 금지]**: "
            f"사용자가 이번 질문에서 **과거 연도({past_str} 귀속)**를 명시하여 질문했습니다. "
            f"따라서 **{cur_yr}년 또는 {next_yr}년 개정 세법을 기준으로 계산하거나 결론 내리면 심각한 법리 오류가 발생합니다!**\n"
            f"• **[필수 도구 및 판단 절차]**: 반드시 **`search_historical_law_for_gemini(law_name, target_date=\"{first_past}1231\", query_filter=...)` (구법·연혁법령 타임머신)** 및 현행 법령의 **부칙(적용례·경과조치)**을 조회하여, "
            f"**{past_str} 과세기간 당시에 실제로 시행 중이던 구법(종전 규정)의 요건·공제액·세율·한도**를 기준으로 `1. 결론`과 `2. 내용`을 작성하세요. "
            f"(현행 {cur_yr}년 개정 세법과 달라진 점이 있다면 본문 내 신·구 비교표에서 참고로만 대조해 주되, 질문 사안의 결론은 반드시 {past_str} 귀속 당시 법령으로 확정하세요.)\n"
            + common_footer
        )
    elif mode == "MIXED_PAST_AND_CURRENT":
        past_str = ", ".join(f"{y}년" for y in past_yrs)
        first_past = past_yrs[0]
        return (
            f"{HIDDEN_DATE_DIRECTIVE_MARKER} — 내부 판단 기준이므로 이 지침 블록 자체를 답변에 그대로 복붙하지 말 것]\n"
            f"• 오늘 날짜(대한민국 KST): 오늘은 {dot_full}이며, 이번 질문은 **과거 연도({past_str})와 당해 연도({cur_yr}년)가 함께 걸친 복합/사후관리/비교 질의**입니다.\n"
            f"• 🚨 **[최우선 명령 — 과거({past_str}) 구법·부칙 경과조치와 당해({cur_yr}년) 현행법의 정밀 분리 적용]**: "
            f"과거({past_str})에 최초 발생한 고용·투자·거래분에 대해서는 **`search_historical_law_for_gemini(law_name, target_date=\"{first_past}1231\", query_filter=...)`**와 **법령 부칙(적용례·경과조치)**을 조회하여 종전 규정(구법) 적용 여부를 먼저 확인하고(예: 통합고용세액공제 2024·2025년 귀속분의 2·3차년도 연속공제·사후관리 = 부칙 제34조에 따른 종전 규정), "
            f"{cur_yr}년 신규 발생분이나 신·구 비교 요청에 대해서는 {cur_yr}년 현행 개정 세법을 대조하여 두 연도의 적용 기준이 절대 섞이거나 왜곡되지 않게 구분하여 답변하세요.\n"
            + common_footer
        )
    elif mode == "FUTURE_ONLY":
        fut_str = ", ".join(f"{y}년" for y in fut_yrs)
        return (
            f"{HIDDEN_DATE_DIRECTIVE_MARKER} — 내부 판단 기준이므로 이 지침 블록 자체를 답변에 그대로 복붙하지 말 것]\n"
            f"• 오늘 날짜(대한민국 KST): 오늘은 {dot_full} (당해 {cur_yr}년)이며, 이번 질문은 사용자가 **미래 시행예정 연도({fut_str})**를 특정한 질의입니다.\n"
            f"• 조문 및 부칙에서 **{fut_str} 1월 1일 이후 시행·적용되는 개정 규정**과 현행({cur_yr}년) 규정을 비교하여 명확히 답변하되, 해당 개정 규정이 {fut_str}부터 시행 예정임을 명시하세요.\n"
            + common_footer
        )
    else:
        return (
            f"{HIDDEN_DATE_DIRECTIVE_MARKER} — 내부 판단 기준이므로 이 지침 블록 자체를 답변에 그대로 복붙하지 말 것]\n"
            f"• **오늘 날짜(대한민국 KST) 및 시점 부등식**: 오늘은 **{dot_full}**이며, **올해(현재 당해 과세연도)는 {cur_yr}년({cur_yr}년 귀속)**, 작년은 {prev_yr}년입니다!\n"
            f"  - 시점 선후 공식: `{prev2_yr}년(재작년)` < `{prev_yr}년(작년·이미 종료된 과거)` < **`{cur_yr}.01.01.(올해 초·이미 시행됨!)` <= `{dot_full}(오늘·현재)`** < **`{next_yr}.01.01.(내년·아직 미시행 미래 시행예정!)`**\n"
            f"• 🚫 **[절대 금지 시점 착각 1 — '{cur_yr}년 시행이니 현재({prev_yr}년)는 유예/상관없다' 오판 금지]**:\n"
            f"  - 법령 조문이나 부칙에서 **'{cur_yr}년 1월 1일부터 시행(적용)한다'**라는 문구를 보았을 때, 과거 학습 데이터의 관성으로 *\"이 규정은 {cur_yr}년부터 시행되므로 {prev_yr}년인 현재는 상관없다(유예 중이다)\"*라고 답하면 치명적인 오류입니다! 지금은 이미 **{cur_yr}년({dot_full})**이므로 `{cur_yr}.1.1.` 시행 규정은 **현재 전면 시행 중인 현행 규정**이며, `{prev_yr}.12.31.까지 유예` 규정은 이미 지난해 말로 종료되었습니다.\n"
            f"• 🚫 **[절대 금지 시점 착각 2 — '이미 개정·공포된 {next_yr}년(27년) 시행예정 법령'을 지금({cur_yr}년)부터 적용받는 것처럼 조기적용 오판 금지]**:\n"
            f"  - 반대로, 법령이 현재 이미 개정·공포되어 있더라도 조문 시행일자나 부칙 적용례에서 **'{next_yr}년 1월 1일 이후(또는 {next_yr}년 이후 개시·지급·양도분부터) 시행·적용한다'**고 정한 규정은 오늘({dot_full}) 기준 **아직 시행일이 도래하지 않은 미시행(내년 시행예정) 규정**입니다! (국회 미통과 정부 세법개정안 역시 법령이 아니므로 '개정 추진 중'으로만 언급할 것)\n"
            f"  - 올해({cur_yr}년 귀속) 일반 질의에 대해 **{next_yr}년부터 시행되는 개정 규정을 마치 지금({cur_yr}년)부터 당장 적용받는 것처럼 결론 내리거나 계산하면 심각한 법리 오류가 됩니다!** 반드시 **올해({cur_yr}년) 현재 시행 중인 현행 규정**을 적용해 결론을 내리고, {next_yr}년 시행예정 개정 내용은 본문 하단이나 신·구 비교표에서 *'※ 참고: {next_yr}.1.1. 시행 예정 개정사항'*으로만 명확히 분리해 안내하세요.\n"
            f"• 📅 **[연도 미기재 질문의 적용 기준시점 판별 규칙]**:\n"
            f"  - (일반 법리·요건 질의): 오늘({dot_full}) 현재 시행 중인 `{cur_yr}년 귀속` 현행 법령을 최우선 적용하세요.\n"
            f"  - (연도 없는 월·일 언급 시): 오늘({now_ymd_dot}) 기준 이미 지난 날짜의 과거 사실(예: '8월 31일 폐업')은 올해인 `{cur_yr}.08.31.`({cur_yr}년 귀속)로, 오늘 기준 아직 도래하지 않은 월·일의 과거 사실(예: '12월 15일 폐업했었다')은 직전 연도인 `{prev_yr}.12.15.`로 해석하고, 이번 달·연말 중 도래할 신고·지급 일정은 올해(`{cur_yr}년`)로 해석하세요.\n"
            f"  - (정기 신고·납부·정산 시기 질의 시): 별도 귀속연도 표시 없이 '지금 신고·납부·정산할 세금'을 묻는 경우 오늘 시점에 신고하는 대상 과세기간(예: 1~3월 연말정산·12월 결산 법인세 정기신고 = 직전 연도분, 5월 종합소득세 정기신고 = 직전 연도분, 1월·7월 부가세 확정 = 직전 과세기간, 매월 원천세 = 전월 지급분)을 함께 고려하되, 기준시점이 두 가지로 읽힐 수 있으면 임의로 하나만 단정하지 말고 당해 연도({cur_yr}년 귀속) 기준과 직전 연도 신고분 기준을 구분해 답하세요.\n"
            f"• **[부칙 경과조치 예외 보호]**: 과거({prev2_yr}~{prev_yr}년) 최초 고용증가·투자분에 대해 **법령 부칙(적용례·경과조치)에서 종전 규정(구법)을 따르도록 명시한 사안(예: 통합고용세액공제 2024·2025년 귀속분의 2·3차년도 연속공제·사후관리 = 법률 제21223호 부칙 제34조 종전 규정)**은 부칙 원문에 따라 종전 규정 적용분과 {cur_yr}년 현행 규정 적용분을 나눠 설명하세요.\n"
            + common_footer
        )

_LEAKED_GUIDELINE_PATTERNS = (
    re.compile(r"\[시스템\s*자동\s*주입\s*기준일\s*[·ㆍ]\s*귀속연도\s*판단\s*지침"),
    re.compile(r"\[기준일\s*[·ㆍ]\s*적용시점\s*판단\s*지침"),
    re.compile(r"\[시스템\s*실시간\s*기준일\s*및\s*귀속연도\s*원칙"),
    re.compile(r"내부\s*(?:판단\s*기준|지침)이므로\s*이\s*(?:지침\s*블록|문장).*답변에.*말\s*것"),
    re.compile(r"^•\s*\*\*?오늘\s*날짜\(대한민국\s*KST\)"),
    re.compile(r"^•\s*오늘\s*날짜\(대한민국\s*KST\)"),
    re.compile(r"시점\s*선후\s*공식\s*:"),
    re.compile(r"\[(?:최우선\s*명령|절대\s*금지\s*시점\s*착각|연도\s*미기재\s*질문의\s*적용\s*기준시점|부칙\s*경과조치\s*예외\s*보호|필수\s*도구\s*및\s*판단\s*절차|답변\s*형식\s*—\s*.1\.\s*결론.\s*첫\s*줄\s*적용\s*기준\s*명시)"),
    re.compile(r"^(?:1|2|3)단계\s*—\s*(?:적용\s*기준시점을\s*정한다|정해진\s*적용\s*기준시점에\s*맞는|결론\s*첫\s*줄에\s*적용\s*기준시점을)"),
)

def _strip_leaked_temporal_guideline(text: str) -> str:
    """최종 답변에서 내부 기준일 지침 블록이나 문장이 실수로 노출된 경우 자동 제거합니다."""
    if not text:
        return ""
    raw = str(text)
    if HIDDEN_DATE_DIRECTIVE_MARKER in raw and "### 1." in raw:
        idx_m = raw.find(HIDDEN_DATE_DIRECTIVE_MARKER)
        idx_h = raw.find("### 1.", idx_m)
        if idx_m != -1 and idx_h != -1:
            raw = (raw[:idx_m] + raw[idx_h:]).strip()
    out_lines = []
    for line in raw.splitlines():
        s = line.strip()
        if any(p.search(s) for p in _LEAKED_GUIDELINE_PATTERNS):
            continue
        out_lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()

def _strip_directive_and_attachment_for_verify(text: str) -> str:
    """감수 프롬프트 구성 전 숨김 날짜 지침 블록과 대용량 첨부파일 구분선 이후의 표 데이터를 걷어냅니다."""
    s = (text or "").strip()
    if not s:
        return ""
    if "========================================" in s:
        s = s.split("========================================")[0].strip()
    if HIDDEN_DATE_DIRECTIVE_MARKER in s:
        if "[현재 사용자 질문]:" in s:
            s = s.split(HIDDEN_DATE_DIRECTIVE_MARKER)[0].rstrip() + "\n[현재 사용자 질문]:" + s.rsplit("[현재 사용자 질문]:", 1)[-1]
        else:
            s = s.split(HIDDEN_DATE_DIRECTIVE_MARKER)[0].strip()
    return s.strip()

def _prepare_semantic_verify_query(
    query_or_input: str = "",
    full_user_input: str = "",
    max_chars: int = 3000,
    *,
    raw_query: str = "",
    user_query: str = "",
) -> str:
    """
    감수자(_semantic_verify)에게 전달할 질문 텍스트를 구성합니다.
    - 호출 방식 호환:
      1) `_prepare_semantic_verify_query(raw_query, full_user_input, 3000)`
      2) `_prepare_semantic_verify_query(full_in, raw_query=raw_q, max_chars=3000)`
    - 숨김 날짜 지침 블록(HIDDEN_DATE_DIRECTIVE_MARKER)과 첨부파일 구분선 이후의 표 데이터를 먼저 제거하여,
      대용량 파일이 첨부되어도 현재 질문(raw_query)이 100% 보존되도록 보장합니다.
    """
    if raw_query:
        rq_src = raw_query
        fu_src = full_user_input or user_query or query_or_input
    elif user_query:
        rq_src = query_or_input
        fu_src = user_query or full_user_input
    else:
        rq_src = query_or_input
        fu_src = full_user_input

    fu_clean = _strip_directive_and_attachment_for_verify(fu_src)
    rq_clean = _strip_directive_and_attachment_for_verify(rq_src)
    if "[현재 사용자 질문]:" in rq_clean:
        if not fu_clean:
            fu_clean = rq_clean
        rq_clean = rq_clean.rsplit("[현재 사용자 질문]:", 1)[-1].strip()
    if not rq_clean and "[현재 사용자 질문]:" in fu_clean:
        rq_clean = fu_clean.rsplit("[현재 사용자 질문]:", 1)[-1].strip()

    if not rq_clean:
        return fu_clean[-max_chars:] if len(fu_clean) > max_chars else fu_clean
    if not fu_clean or fu_clean == rq_clean:
        return rq_clean[-max_chars:] if len(rq_clean) > max_chars else rq_clean
    if len(rq_clean) >= max_chars - 120:
        return rq_clean[-max_chars:]

    hist_part = fu_clean.rsplit("[현재 사용자 질문]:", 1)[0].strip() if "[현재 사용자 질문]:" in fu_clean else (
        fu_clean[:-len(rq_clean)].strip() if fu_clean.endswith(rq_clean) else fu_clean
    )
    years = sorted(set(re.findall(r"(20[12]\d)\s*(?:년|귀속|사업연도|과세기간)", hist_part)))
    yr_tag = f"[이전 대화 언급 연도: {', '.join(y + '년' for y in years)}]\n" if years else ""
    rem = max(0, max_chars - len(rq_clean) - len(yr_tag) - 40)
    tail = hist_part[-rem:] if (rem > 0 and hist_part) else ""
    if tail:
        return f"{yr_tag}[직전 대화 맥락]\n{tail}\n\n[현재 질문]\n{rq_clean}"
    return f"{yr_tag}{rq_clean}".strip()


def _prepare_verify_query_context(
    raw_query: str = "",
    full_user_input: str = "",
    max_chars: int = 3000,
) -> str:
    """_prepare_semantic_verify_query의 표준 호환 별칭."""
    return _prepare_semantic_verify_query(raw_query, full_user_input, max_chars=max_chars)

def build_temporal_guideline() -> str:
    """하위 호환용: 기본 기준일·적용시점 지침 문자열을 반환합니다."""
    return build_hidden_date_law_directive("")

def build_invisible_temporal_prefix() -> str:
    """하위 호환용"""
    return ""

def ensure_hidden_date_directive_in_input(user_input: str, raw_query: str = "") -> str:
    txt = user_input or ""
    directive = build_hidden_date_law_directive(raw_query or txt)
    if HIDDEN_DATE_DIRECTIVE_MARKER in txt:
        return txt
    if "[현재 사용자 질문]:" in txt:
        head_part, tail_part = txt.rsplit("[현재 사용자 질문]:", 1)
        return f"{head_part}\n{directive}[현재 사용자 질문]:{tail_part}"
    return directive + txt

def _annotate_law_effective_dates_vs_today(law_text: str) -> str:
    """
    [Stage 1 방어벽] get_law_details_for_gemini가 반환하는 법령·부칙 원문 텍스트에서
    시행일·적용시기('2026.1.1', '2025.12.31', '2027.1.1' 등)를 스캔하여,
    ① 2026.1.1 시행 규정을 미시행(유예)으로 착각하는 오류와
    ② 이미 개정·공포되었으나 2027.1.1부터 시행되는 미래 규정을 지금(2026년) 당장 적용받는 것처럼 착각하는 오류를
    도구 반환값 최상단에서 동시에 원천 차단합니다.
    """
    if not law_text or law_text.startswith("❌"):
        return law_text
    kst = get_kst_today_context()
    cur_yr = kst["year"]
    prev_yr = kst["prev_year"]
    next_yr = kst["next_year"]
    next2_yr = cur_yr + 2
    dot_full = kst["dot_full"]

    notes = [
        f"⏰ [도구 실시간 시점 판정 브리핑 | 오늘 날짜(KST): {dot_full} · 현재 당해 과세연도: {cur_yr}년({cur_yr}년 귀속)]"
    ]
    compact = law_text.replace(" ", "")
    has_cur_yr_ref = any(
        pat in compact
        for pat in (f"{cur_yr}년1월1일", f"{cur_yr}.1.1", f"{cur_yr}.01.01", f"{cur_yr}년귀속", f"{cur_yr}년이후")
    )
    has_prev_yr_ref = any(
        pat in compact
        for pat in (f"{prev_yr}년12월31일", f"{prev_yr}.12.31", f"{prev_yr}년귀속", f"{prev_yr}년지급분까지", f"{prev_yr}년까지")
    )
    has_next_yr_ref = any(
        pat in compact
        for pat in (
            f"{next_yr}년1월1일", f"{next_yr}.1.1", f"{next_yr}.01.01", f"{next_yr}년이후", f"{next_yr}년부터",
            f"시행일자:{next_yr}", f"조문시행일자:{next_yr}",
            f"{next2_yr}년1월1일", f"{next2_yr}.1.1", f"{next2_yr}.01.01"
        )
    )

    if has_cur_yr_ref:
        notes.append(
            f"  ✅ [파이썬 현행 시행 확정 판정 ({cur_yr}년)]: 아래 조문·부칙의 **'{cur_yr}년 1월 1일({cur_yr}.1.1.) 시행/적용'** 규정은 "
            f"오늘({dot_full}) 기준으로 미래 유예 규정이 아니라 **이미 시행일이 경과하여 올해({cur_yr}년) 현재 전면 시행·적용 중인 현행 규정**입니다! "
            f"(절대 '{cur_yr}년부터 시행이므로 현재({prev_yr}년)는 유예 중이라 상관없다'고 오판하지 말 것!)"
        )
    if has_prev_yr_ref:
        notes.append(
            f"  ⏹️ [파이썬 유예기한 만료 판정 ({prev_yr}년)]: 아래 조문·부칙의 **'{prev_yr}년 12월 31일까지(또는 {prev_yr}년 지급분까지)'** 유예·적용 규정은 "
            f"오늘({dot_full}) 기준으로 **이미 지난해 말로 종료된 과거 규정**입니다! (질문자가 '{prev_yr}년 귀속'을 명시한 경우가 아니라면 당해 연도인 {cur_yr}년 사건에는 적용 불가)"
        )
    if has_next_yr_ref:
        notes.append(
            f"  🚨 [파이썬 미시행(미래 시행예정: {next_yr}년 이후) 조기적용 차단 경고]: 아래 조문·부칙에 포함된 **'{next_yr}년 1월 1일({next_yr}.1.1.) 이후 시행/적용'** 개정 규정은 "
            f"현재 법령에 이미 개정·공포되어 있더라도 **오늘({dot_full}) 기준 아직 시행일이 도래하지 않은 미시행(내년 이후 시행예정) 규정**입니다! "
            f"사용자가 '{next_yr}년 귀속'을 특정해 질문한 것이 아니라면, **현재({cur_yr}년 귀속) 사안에 이 {next_yr}년 시행예정 개정 규정을 지금 당장 적용받는 것처럼 답변하는 것을 절대 금지**합니다! "
            f"반드시 **현재({cur_yr}년) 시행 중인 규정**으로 결론과 계산을 확정하고, {next_yr}년 개정 내용은 '※ 참고({next_yr}.1.1. 시행예정 개정사항)'로만 별도 안내하세요!"
        )
    if len(notes) == 1:
        notes.append(
            f"  📌 [기본 시점 기준]: 오늘({dot_full}) 기준 당해 연도는 **{cur_yr}년({cur_yr}년 귀속)**이며, `{cur_yr}.1.1.` 이전 시행 법령만 현재 적용 대상이고 `{next_yr}.1.1.` 이후 시행 법령은 아직 미시행 상태입니다."
        )
    return "\n".join(notes) + "\n\n" + law_text

def _scan_timeline_hallucinations(answer_text: str, user_query: str = "", full_user_input: str = "") -> list[str]:
    """
    [Stage 4 방어벽] 생성된 답변 본문에서
    ① 오늘(2026년)을 2025년(25년)으로 착각하거나 '2026년 1월 1일 시행'을 미시행 유예로 오판한 문장,
    ② 이미 개정·공포되었으나 '2027년(27년) 1월 1일부터 시행'되는 미래 규정을 지금(2026년)부터 바로 적용받는 것처럼 서술한 조기적용 오판 문장,
    ③ 과거 연도(예: 24년) 질문에 26년 최신법만 적용한 문장을 정밀 탐지합니다.
    """
    if not answer_text:
        return []
    info = detect_query_attribution_years(user_query, full_user_input=full_user_input)
    cur_yr = info["current_year"]
    prev_yr = cur_yr - 1
    next_yr = cur_yr + 1
    cur_2d = str(cur_yr)[2:]
    prev_2d = str(prev_yr)[2:]
    next_2d = str(next_yr)[2:]
    mode = info["mode"]
    errors = []

    if mode == "DEFAULT_CURRENT":
        # 1) 현재 연도를 2025년/25년(작년)으로 부르는 명백한 착각 패턴
        pat_wrong_now = re.compile(
            rf"((?:{prev_yr}|{prev_2d})\s*년인?\s*현재|현재\s*\(\s*(?:{prev_yr}|{prev_2d})\s*년\s*\)|올해\s*\(\s*(?:{prev_yr}|{prev_2d})\s*년\s*\)|금년\s*\(\s*(?:{prev_yr}|{prev_2d})\s*년\s*\)|현재는\s*(?:{prev_yr}|{prev_2d})\s*년|올해는\s*(?:{prev_yr}|{prev_2d})\s*년)"
        )
        for m in pat_wrong_now.finditer(answer_text):
            errors.append(f"현재 연도를 {cur_yr}년이 아닌 '{m.group(0)}'으로 잘못 인식함")

        # 2) 당해 연도(2026년) 언급이 전혀 없이 '2025년 지급분까지는 ... 현재 시점'이라고 단정한 패턴만 적발 (정기신고·신구비교·직전연도 12월 사건 병기는 정상 허용)
        has_cur_yr_in_ans = bool(re.search(rf"(?:{cur_yr}|{cur_2d})\s*년", answer_text))
        pat_wrong_attr = re.compile(
            rf"((?:{prev_yr}|{prev_2d})\s*년\s*지급분까지는[^\n]*현재\s*시점)"
        )
        for m in pat_wrong_attr.finditer(answer_text):
            errors.append(f"연도 미지정 당해연도({cur_yr}년) 질문을 '{m.group(0)}'(과거 {prev_yr}년 귀속)으로 잘못 전제함")
        if not has_cur_yr_in_ans and not info.get("history_past_years"):
            q_check = (user_query or "")
            if not re.search(r"(연말정산|종합소득세|정기신고|확정신고|12\s*월\s*\d{1,2}\s*일)", q_check):
                m_only_prev = re.search(rf"적용\s*기준\s*:\s*{prev_yr}\s*년\s*귀속", answer_text)
                if m_only_prev:
                    errors.append(f"연도 미지정 당해연도({cur_yr}년) 질문의 적용 기준을 '{m_only_prev.group(0)}'으로만 단정함")

        # 3) '2026년(26년)부터 시행'을 미래 유예 규정으로 보고 현재 적용되지 않는다거나 종전 규정(반기별 제출 등)이 적용된다고 서술하는 패턴
        pat_future_illusion = re.compile(
            rf"((?:{cur_yr}|{cur_2d})\s*년(?:\s*1월\s*1일)?(?:\s*이후\s*지급분)?\s*(?:부터|이후)[^\n.]*시행[^\n.]*(?:예정|유예되어|현재는\s*적용되지|현재는\s*상관없|현재\s*상관없|아직\s*시행되지|도래하지\s*않)|아직\s*(?:{cur_yr}|{cur_2d})\s*년이\s*도래하지|(?:{prev_yr}|{prev_2d})\s*년\s*지급분까지는\s*반기별\s*제출[^\n.]*적용되므로)"
        )
        for m in pat_future_illusion.finditer(answer_text):
            errors.append(f"이미 시행 중인 {cur_yr}년 규정을 미래 미시행/유예 규정으로 오판함 ('{m.group(0)[:55]}')")

        # 4) [신규 추가] 이미 개정·공포되었으나 '2027년(27년)부터 시행/적용'되는 미시행 규정을 현재(2026년/올해/지금)부터 적용받는 것처럼 서술하는 패턴
        for sent in re.split(r"[\n.!?]+", answer_text):
            s_clean = sent.strip()
            if not s_clean:
                continue
            # 정상 안내 문구('미시행', '시행예정', '시행 예정', '적용되지 않', '현행 규정을 적용')가 있는 문장은 정상 판정이므로 통과
            if re.search(r"(미시행|시행\s*예정|적용되지\s*않|적용\s*불가|해당하지\s*않|현행\s*규정을?\s*적용|종전\s*규정을?\s*적용)", s_clean):
                continue
            has_2027 = bool(re.search(rf"(?<!\d)(?:{next_yr}|{next_2d})\s*년", s_clean))
            has_premature_claim = bool(
                re.search(
                    rf"((?:현재|지금|올해|금년|당해|{cur_yr}년|{cur_2d}년)(?:부터|에도|에|역시|은|는)?[^\n]*?(?:개정된?\s*사항|개정\s*규정|개정법)?[^\n]*?(?:바로|즉시|당장|지금부터)?\s*(?:적용|해당|공제\s*가능|산출)|현재\s*개정된\s*사항\s*기준으로\s*(?:지금부터|바로|올해부터)?\s*(?:법령을?\s*)?적용)",
                    s_clean
                )
            )
            if has_2027 and has_premature_claim:
                errors.append(f"아직 시행 전인 {next_yr}년 시행예정 개정 규정을 현재({cur_yr}년)부터 적용받는 것처럼 조기적용 오판함 ('{s_clean[:65]}')")

    elif mode == "PAST_ONLY":
        past_yrs = info["past_years"]
        if past_yrs and not any(str(py) in answer_text or f"{str(py)[2:]}년" in answer_text for py in past_yrs):
            past_str = ", ".join(f"{y}년" for y in past_yrs)
            errors.append(f"사용자가 지정한 과거 귀속연도({past_str})가 답변에서 누락되고 {cur_yr}년 기준으로만 작성됨")

    return list(dict.fromkeys(errors))

import streamlit as st
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

RUNTIME_API_KEYS_FILE = os.path.join(".workspace_storage", "runtime_api_keys.json")

_RT_KEYS_CACHE: dict = {"mtime": None, "data": {}}
_RT_KEYS_LOCK = threading.RLock()

def _read_runtime_keys_cached() -> dict:
    """runtime_api_keys.json을 파일이 바뀐 경우에만 다시 읽습니다 (멀티스레드 RLock 보호)."""
    with _RT_KEYS_LOCK:
        try:
            mt = os.path.getmtime(RUNTIME_API_KEYS_FILE)
        except OSError:
            _RT_KEYS_CACHE["mtime"], _RT_KEYS_CACHE["data"] = None, {}
            return {}
        if _RT_KEYS_CACHE["mtime"] != mt:
            try:
                with open(RUNTIME_API_KEYS_FILE, "r", encoding="utf-8") as rf:
                    data = json.load(rf)
                _RT_KEYS_CACHE["data"] = data if isinstance(data, dict) else {}
            except Exception:
                _RT_KEYS_CACHE["data"] = {}
            _RT_KEYS_CACHE["mtime"] = mt
        return dict(_RT_KEYS_CACHE["data"])

def _get_secret_or_env(key_name: str) -> str:
    """1순위: 모달에서 저장한 런타임 보안키(.workspace_storage/runtime_api_keys.json) -> 2순위: st.secrets -> 3순위: 환경변수(.env)에서 실시간으로 읽어옵니다."""
    rval = str(_read_runtime_keys_cached().get(key_name) or "").strip().strip('"').strip("'")
    if rval:
        return rval
    try:
        if hasattr(st, "secrets") and key_name in st.secrets:
            val = str(st.secrets[key_name]).strip().strip('"').strip("'")
            if val:
                return val
    except Exception:
        pass
    return os.getenv(key_name, "").strip().strip('"').strip("'")

def _safe_float(raw_val, default_val: float) -> float:
    """Secrets에 '2,000'이나 '1,400원'처럼 쉼표·단위가 포함되어 있어도 오류 없이 숫자로 변환합니다."""
    if raw_val is None or raw_val == "":
        return float(default_val)
    try:
        cleaned = re.sub(r"[^0-9.\-]", "", str(raw_val))
        return float(cleaned) if cleaned else float(default_val)
    except Exception:
        return float(default_val)

# ---------------------------------------------------------
# Gemini 연결 방식: AI Studio API 키(기본) / Vertex AI 서비스 계정(Google Cloud 크레딧 차감)
# - Secrets에 GEMINI_USE_VERTEX = "on" 이면 Vertex AI로 호출합니다.
#   필요 항목: GCP_PROJECT_ID, GCP_LOCATION(기본 global), GCP_SERVICE_ACCOUNT_JSON(서비스 계정 JSON 전체)
#   또는 [gcp_service_account] 표 형식
# - GEMINI_VERTEX_FALLBACK = "on" 일 때만 Vertex 실패 시 AI Studio 키(유료 결제)로 넘어갑니다.
# ---------------------------------------------------------
VERTEX_KEY_SENTINEL = "__VERTEX_AI__"
# 429(처리량 초과)·503(일시 불가)은 같은 요청만 2~8초 간격으로 최대 2번 다시 보냅니다.
# (대화 전체를 다음 모델로 처음부터 다시 하지 않도록 함. 504·시간 초과는 재시도해도 오래 걸리므로 제외)
_REQUEST_RETRY_OPTIONS = {"attempts": 3, "initial_delay": 2.0, "max_delay": 8.0, "http_status_codes": [429, 503]}
_VERTEX_CREDS = None
_VERTEX_CREDS_LOCK = threading.Lock()

def _secret_on(key_name: str) -> bool:
    return _get_secret_or_env(key_name).lower() in ("on", "true", "1", "yes")

def is_vertex_enabled() -> bool:
    """GEMINI_USE_VERTEX=on 이거나 GCP_SERVICE_ACCOUNT_JSON/[gcp_service_account]가 등록되어 있으면(명시적 off가 아닌 한) Vertex AI 크레딧을 자동 활성화합니다."""
    raw_flag = _get_secret_or_env("GEMINI_USE_VERTEX").lower().strip()
    if raw_flag in ("off", "false", "0", "no"):
        return False
    if raw_flag in ("on", "true", "1", "yes"):
        return True
    return _load_vertex_sa_info() is not None

def is_vertex_fallback_enabled() -> bool:
    """Vertex AI 호출 실패 시 유료키(GEMINI_PAID_KEY)가 있으면 중단 없이 자동 폴백합니다(명시적 off가 아닌 한 기본 활성화)."""
    raw_fb = _get_secret_or_env("GEMINI_VERTEX_FALLBACK").lower().strip()
    if raw_fb in ("off", "false", "0", "no"):
        return False
    return True

def _load_vertex_sa_info() -> dict | None:
    try:
        if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
    except Exception:
        pass
    raw = _get_secret_or_env("GCP_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except Exception:
        return None
    return info if isinstance(info, dict) and info.get("private_key") and info.get("client_email") else None

def _vertex_credentials():
    global _VERTEX_CREDS
    with _VERTEX_CREDS_LOCK:
        if _VERTEX_CREDS is None:
            info = _load_vertex_sa_info()
            if not info:
                return None
            from google.oauth2 import service_account
            _VERTEX_CREDS = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        return _VERTEX_CREDS

def vertex_project_id() -> str:
    creds = _vertex_credentials()
    return _get_secret_or_env("GCP_PROJECT_ID") or str(getattr(creds, "project_id", "") or "")

def vertex_location() -> str:
    return _get_secret_or_env("GCP_LOCATION") or "global"

def make_genai_client(api_key: str, timeout_ms: int | None = None):
    """api_key가 VERTEX_KEY_SENTINEL이면 Vertex AI(서비스 계정) 클라이언트, 아니면 AI Studio 클라이언트를 만듭니다."""
    if api_key == VERTEX_KEY_SENTINEL:
        creds = _vertex_credentials()
        if creds is None:
            raise RuntimeError(
                "Vertex AI 설정 오류: Secrets의 GCP_SERVICE_ACCOUNT_JSON(서비스 계정 JSON)을 읽지 못했습니다. "
                "JSON 전체를 작은따옴표 3개(''') 사이에 붙여넣었는지 확인하세요."
            )
        kw = {"vertexai": True, "project": vertex_project_id(), "location": vertex_location(), "credentials": creds}
    else:
        kw = {"api_key": api_key}
    http_opts: dict = {"retry_options": dict(_REQUEST_RETRY_OPTIONS)}
    if timeout_ms:
        http_opts["timeout"] = int(timeout_ms)
    try:
        return genai.Client(**kw, http_options=http_opts)
    except Exception:
        pass
    if timeout_ms:
        try:
            return genai.Client(**kw, http_options={"timeout": int(timeout_ms)})
        except Exception:
            pass
    return genai.Client(**kw)

def get_live_gemini_key_pool() -> list[tuple[str, str]]:
    """
    유료키만 사용합니다.
    - GEMINI_USE_VERTEX = "on" 이면 Vertex AI(서비스 계정)만 사용합니다(GEMINI_VERTEX_FALLBACK = "on"이면 아래 키를 예비로 추가).
    - GEMINI_PAID_KEY(기본) → GEMINI_API_KEY(예비, 다른 값일 때만) 순서로 사용합니다.
    """
    pool = []
    seen = set()
    if is_vertex_enabled():
        pool.append(("☁️ Vertex AI(크레딧)", VERTEX_KEY_SENTINEL))
        seen.add(VERTEX_KEY_SENTINEL)
        if not is_vertex_fallback_enabled():
            return pool
    for env_name, lbl in [("GEMINI_PAID_KEY", "💳 유료키"), ("GEMINI_API_KEY", "💳 유료키(예비)"), ("GOOGLE_API_KEY", "💳 유료키(GOOGLE)")]:
        k = _get_secret_or_env(env_name)
        if k and k not in seen:
            pool.append((lbl if pool or env_name == "GEMINI_PAID_KEY" else "💳 유료키", k))
            seen.add(k)
    return pool

def _ai_studio_key_pool() -> list[tuple[str, str]]:
    """Vertex 설정과 관계없이 AI Studio 유료 키만 모읍니다."""
    pool, seen = [], set()
    for env_name, lbl in [("GEMINI_PAID_KEY", "💳 유료키"), ("GEMINI_API_KEY", "💳 유료키(예비)"), ("GOOGLE_API_KEY", "💳 유료키(GOOGLE)")]:
        k = _get_secret_or_env(env_name)
        if k and k not in seen:
            pool.append((lbl if pool or env_name == "GEMINI_PAID_KEY" else "💳 유료키", k))
            seen.add(k)
    return pool

def get_pro_key_pool() -> list[tuple[str, str]]:
    """
    Pro 심층 모드용 키 풀.
    - Secrets에 PRO_USE_PAID_KEY = "on" 이면 Vertex 모드여도 Pro는 AI Studio 유료 키(카드 결제)로 호출합니다.
      (Vertex에서 응답 지연·미제공인 Argon 등 Pro 모델을 쓰기 위함. Flash는 계속 Vertex 크레딧 사용)
    - 유료 키가 없으면 기존 키 풀을 그대로 씁니다.
    """
    if is_vertex_enabled() and _secret_on("PRO_USE_PAID_KEY"):
        paid = _ai_studio_key_pool()
        if paid:
            return paid
    return get_live_gemini_key_pool()

import law_api

def get_law_oc_auto() -> str:
    """st.secrets, 환경변수, config.py, law_api 모듈 속성 및 파일 내부에서 법제처 OC 키(LAW_OPEN_API_KEY 최우선)를 자동 추출합니다."""
    for k in ["LAW_OPEN_API_KEY", "LAW_API_OC", "OC", "LAW_OC", "LAW_API_KEY", "MOLEG_OC", "DRF_OC"]:
        val = _get_secret_or_env(k)
        if val:
            return val
    for attr in ["LAW_OPEN_API_KEY", "OC", "LAW_API_OC", "LAW_OC", "LAW_API_KEY", "API_KEY", "USER_OC", "oc"]:
        val = getattr(law_api, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    try:
        import config
        for attr in ["LAW_OPEN_API_KEY", "OC", "LAW_API_OC", "LAW_OC", "LAW_API_KEY"]:
            val = getattr(config, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass
    for fname in ["law_api.py", "config.py"]:
        if os.path.exists(fname):
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    src = f.read()
                m = re.search(r'(?:LAW_OPEN_API_KEY|OC|LAW_API_OC|LAW_OC|LAW_API_KEY)\s*=\s*["\']([^"\']+)["\']', src)
                if m and m.group(1).strip():
                    return m.group(1).strip()
                m2 = re.search(r'OC=([A-Za-z0-9_.\-]+)', src)
                if m2 and m2.group(1).strip() and not m2.group(1).startswith("{"):
                    return m2.group(1).strip()
            except Exception:
                pass
    return ""

# ---------------------------------------------------------
# ⚡ [속도 개선 ① & ③] 당일 메모리 캐싱 (12시간 TTL) + 18대 주요 세법 ID 프리워밍 + Gzip 고속 HTTP 수신기
# ---------------------------------------------------------
_LAW_MEMORY_CACHE = {}
_LAW_CACHE_LOCK = threading.Lock()
_LAW_CACHE_TTL_SEC = 43200  # 12시간

def _cache_get(key: tuple):
    now = time.time()
    with _LAW_CACHE_LOCK:
        entry = _LAW_MEMORY_CACHE.get(key)
        if entry and (now - entry[0]) < _LAW_CACHE_TTL_SEC:
            return entry[1]
    return None

def _cache_set(key: tuple, val) -> None:
    if val is None:
        return
    now = time.time()
    with _LAW_CACHE_LOCK:
        if len(_LAW_MEMORY_CACHE) > 800:
            expired = [k for k, (ts, _) in _LAW_MEMORY_CACHE.items() if (now - ts) >= _LAW_CACHE_TTL_SEC]
            for k in expired:
                _LAW_MEMORY_CACHE.pop(k, None)
            if len(_LAW_MEMORY_CACHE) > 800:
                oldest = sorted(_LAW_MEMORY_CACHE.items(), key=lambda x: x[1][0])[:200]
                for k, _ in oldest:
                    _LAW_MEMORY_CACHE.pop(k, None)
        _LAW_MEMORY_CACHE[key] = (now, val)

def register_prewarmed_law_ids(law_prom_map: dict) -> None:
    """
    [속도 개선 ①] app.py 구동 시 병렬 조회된 18개 주요 세법·시행령의 최신 법령일련번호(mst_id/law_id)를
    에이전트 메모리 캐시에 즉시 등록하여, AI가 search_law_for_gemini 없이 법령명만으로
    1턴 만에 get_law_details_for_gemini를 직행 호출할 수 있도록 지원합니다.
    """
    if not isinstance(law_prom_map, dict):
        return
    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    for clean_name, info in law_prom_map.items():
        if not isinstance(info, dict):
            continue
        lid = str(info.get("mst_id") or info.get("law_id") or "").strip()
        cname_norm = clean_name.replace(" ", "")
        if cname_norm and lid:
            enf_raw = str(info.get("enf_raw") or info.get("enf_date") or "").replace("-", "").strip()
            prom_no = str(info.get("prom_no") or "").strip()
            _cache_set(("law_name_to_id", today_ymd, cname_norm), lid)
            _cache_set(("law_name_meta", cname_norm), {
                "doc_id": lid,
                "enf_raw": enf_raw,
                "prom_no": prom_no,
                "prom_date": str(info.get("prom_date") or ""),
                "enf_date": str(info.get("enf_date") or ""),
            })

_HTTP_FETCH_MAX_BYTES = 64 * 1024 * 1024   # 법제처 최대 법령 XML(수 MB)의 10배 이상 여유


def _http_get_bytes_fast(url: str, timeout: int = 15) -> bytes:
    """
    [속도 개선 ③] Gzip 압축 수신(Accept-Encoding: gzip) 및 Keep-Alive 헤더를 적용해
    대용량 법제처 XML(조특법·법인세법 등 수 MB) 다운로드 시간을 원문 손실 없이 2~3배 단축합니다.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        },
    )
    max_bytes = _HTTP_FETCH_MAX_BYTES
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read(max_bytes + 1)
        if len(raw_bytes) > max_bytes:
            raise ValueError(f"응답이 너무 큽니다(>{max_bytes // (1024 * 1024)}MB).")
        enc = (resp.info().get("Content-Encoding") or "").lower()
        if "gzip" in enc or raw_bytes[:2] == b"\x1f\x8b":
            try:
                # 압축 해제도 상한 적용 (gzip 폭탄 방어)
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                out = d.decompress(raw_bytes, max_bytes)
                if d.unconsumed_tail:
                    raise ValueError("압축 해제 결과가 너무 큽니다.")
                return out + d.flush()
            except ValueError:
                raise
            except Exception:
                return raw_bytes
        return raw_bytes

# ---------------------------------------------------------
# 📡 [속도 개선 ⑥] 실시간 백그라운드 진행 단계 브로드캐스트 콜백
# ---------------------------------------------------------
_LIVE_STATUS_CB = contextvars.ContextVar("live_status_cb", default=None)

def set_live_status_callback(cb):
    return _LIVE_STATUS_CB.set(cb)

def _emit_live_status(step_msg: str) -> None:
    cb = _LIVE_STATUS_CB.get()
    if callable(cb):
        try:
            cb(step_msg)
        except Exception:
            pass

# ---------------------------------------------------------
# 💰 대화방 1개당 2,000원(ROOM_LIMIT_KRW) 정밀 요금 계량기 및 Pro 차단기
#    (아르곤 프로모션 단가 ~2026.11.30 / 12.01 이후 정상가 및 20만 토큰 장문 구간 자동 반영)
# ---------------------------------------------------------
USAGE_STORAGE_DIR = ".workspace_storage"
os.makedirs(USAGE_STORAGE_DIR, exist_ok=True)
USAGE_FILE_PATH = os.path.join(USAGE_STORAGE_DIR, "api_usage_stats.json")
_USAGE_LOCK = threading.Lock()

ROOM_LIMIT_KRW = _safe_float(_get_secret_or_env("ROOM_LIMIT_KRW"), 2000.0)
MONTHLY_PRO_LIMIT_KRW = ROOM_LIMIT_KRW  # 하위 호환용 별칭
USD_TO_KRW_RATE = _safe_float(_get_secret_or_env("USD_TO_KRW_RATE"), 1400.0)

_MODEL_PRICING_USD_PER_1M = {
    "PRO":   {"in": 2.00, "out": 12.00},   # gemini-3.1-pro-preview 기본 기준
    "FLASH": {"in": 0.75, "out": 3.75},    # gemini-3.8-flash / 3.6-flash 기본 기준
}

def _get_dynamic_model_price_usd_per_1m(model_id: str, in_tokens: int = 0) -> dict:
    """
    [정밀 과금 계량] 공식 Gemini Developer API 요금표 기준:
    - gemini-4-argon: 2026-11-30까지 $2.00 / $10.00 (장문 할증 없음), 2026-12-01부터 $4.00 / $20.00
    - gemini-3.1-pro-preview / gemini-2.5-pro: 20만 토큰 이하 $2.00 / $12.00, 20만 토큰 초과 $4.00 / $18.00
    - gemini-3.5-flash-lite: $0.30 / $2.50
    - gemini-3.8-flash / gemini-3.6-flash: 2026-12-31까지 $0.75 / $3.75, 2027-01-01부터 $1.50 / $7.50
    """
    m_low = (model_id or "").lower()
    today_ymd = int(datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d"))

    if "argon" in m_low:
        if today_ymd <= 20261130:
            return {"in": 2.00, "out": 10.00}
        return {"in": 4.00, "out": 20.00}

    if "pro" in m_low:
        if in_tokens > 200_000:
            return {"in": 4.00, "out": 18.00}
        return {"in": 2.00, "out": 12.00}

    if "flash-lite" in m_low:
        return {"in": 0.30, "out": 2.50}

    if today_ymd >= 20270101 and ("3.8-flash" in m_low or "3.6-flash" in m_low):
        return {"in": 1.50, "out": 7.50}
    return {"in": 0.75, "out": 3.75}

_ACTIVE_ROOM_KEY = contextvars.ContextVar("active_room_key", default="default_public::대화방 1")

def set_active_room_key(room_key: str):
    return _ACTIVE_ROOM_KEY.set(room_key or "default_public::대화방 1")

def _default_bucket() -> dict:
    return {
        "total_krw": 0.0,
        "total_usd": 0.0,
        "pro_calls": 0,
        "flash_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "limit_krw": ROOM_LIMIT_KRW,
        "updated_at": "-"
    }

def _load_all_usage_store() -> dict:
    if os.path.exists(USAGE_FILE_PATH):
        try:
            with open(USAGE_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "rooms" in data:
                return data
        except Exception:
            pass
    return {"rooms": {}}

def _save_all_usage_store(store: dict) -> None:
    try:
        os.makedirs(os.path.dirname(USAGE_FILE_PATH), exist_ok=True)
        tmp_path = f"{USAGE_FILE_PATH}.tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, USAGE_FILE_PATH)
    except Exception as e:
        print(f"⚠️ 사용량 기록 저장 오류: {e}")

def get_room_usage(room_key: str = "") -> dict:
    """특정 대화방(room_key)의 누적 토큰 및 원화/달러 환산 요금 데이터를 반환합니다."""
    r_key = room_key or _ACTIVE_ROOM_KEY.get()
    with _USAGE_LOCK:
        store = _load_all_usage_store()
        bucket = store.get("rooms", {}).get(r_key, {})
        res = _default_bucket()
        for k in res:
            if k in bucket:
                res[k] = bucket[k]
        res["limit_krw"] = ROOM_LIMIT_KRW
        return res

def set_room_usage_from_backup(room_key: str, usage_data: dict) -> None:
    """대화방 백업 복원 또는 디스크 로드 시 해당 방의 요금 데이터를 동기화합니다."""
    if not room_key or not isinstance(usage_data, dict):
        return
    with _USAGE_LOCK:
        store = _load_all_usage_store()
        b = _default_bucket()
        for k in b:
            if k in usage_data:
                b[k] = usage_data[k]
        b["limit_krw"] = ROOM_LIMIT_KRW
        store.setdefault("rooms", {})[room_key] = b
        _save_all_usage_store(store)

def reset_room_usage(room_key: str) -> None:
    """[현재 방 비우기] 시 해당 대화방의 요금·토큰 계량기를 즉시 0원으로 초기화합니다."""
    if not room_key:
        return
    with _USAGE_LOCK:
        store = _load_all_usage_store()
        store.setdefault("rooms", {})[room_key] = _default_bucket()
        _save_all_usage_store(store)

def get_monthly_usage(room_key: str = "") -> dict:
    return get_room_usage(room_key)

_USAGE_ANON_TTL_SEC = 3 * 86400
_USAGE_MAX_ROOMS = 5000


def _prune_usage_rooms_locked(rooms: dict) -> None:
    """
    [메모리·디스크 누수 차단] 브라우저마다 새로 생기는 익명 작업공간 방 기록이 사용량 파일에 무한히 쌓여
    LLM 호출마다 파일 전체를 읽고 쓰는 비용이 계속 커지던 문제를 막습니다.
    - 익명(__anon_session__) 방: 마지막 기록 후 3일 경과 시 삭제
    - 전체 방 수 상한(5,000): 초과 시 오래된 익명 방 → 오래된 일반 방 순으로 정리
    """
    now = time.time()
    for k in [k for k, v in rooms.items()
              if "__anon_session__" in str(k) and now - float((v or {}).get("updated_ts", 0) or 0) > _USAGE_ANON_TTL_SEC
              and float((v or {}).get("updated_ts", 0) or 0) > 0]:
        rooms.pop(k, None)
    if len(rooms) > _USAGE_MAX_ROOMS:
        order = sorted(rooms.items(), key=lambda kv: ("__anon_session__" not in str(kv[0]), float((kv[1] or {}).get("updated_ts", 0) or 0)))
        for k, _ in order[: len(rooms) - _USAGE_MAX_ROOMS]:
            rooms.pop(k, None)


def _record_token_usage(model_id: str, in_tokens: int, out_tokens: int, count_call: bool = True, room_key: str = "") -> None:
    if in_tokens <= 0 and out_tokens <= 0:
        return
    r_key = room_key or _ACTIVE_ROOM_KEY.get()
    is_pro_model = ("pro" in model_id.lower()) or ("argon" in model_id.lower())
    price_info = _get_dynamic_model_price_usd_per_1m(model_id, in_tokens=in_tokens)

    cost_usd = (in_tokens / 1_000_000.0) * price_info["in"] + (out_tokens / 1_000_000.0) * price_info["out"]
    cost_krw = cost_usd * USD_TO_KRW_RATE

    with _USAGE_LOCK:
        store = _load_all_usage_store()
        rooms = store.setdefault("rooms", {})
        stats = rooms.get(r_key, _default_bucket())

        stats["total_usd"] = round(float(stats.get("total_usd", 0.0)) + cost_usd, 6)
        stats["total_krw"] = round(float(stats.get("total_krw", 0.0)) + cost_krw, 2)
        stats["input_tokens"] = int(stats.get("input_tokens", 0)) + int(in_tokens)
        stats["output_tokens"] = int(stats.get("output_tokens", 0)) + int(out_tokens)
        if count_call:
            if is_pro_model:
                stats["pro_calls"] = int(stats.get("pro_calls", 0)) + 1
            else:
                stats["flash_calls"] = int(stats.get("flash_calls", 0)) + 1
        stats["limit_krw"] = ROOM_LIMIT_KRW
        stats["updated_at"] = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M:%S")
        stats["updated_ts"] = time.time()
        rooms[r_key] = stats
        _prune_usage_rooms_locked(rooms)
        _save_all_usage_store(store)

def _extract_and_log_response_usage(
    response,
    model_id: str,
    count_call: bool = True,
    est_in_chars: int = 0,
    est_out_chars: int = 0,
    tool_calls_count: int = 0,
    tool_result_chars: int = 0
) -> None:
    in_tok, out_tok = 0, 0
    try:
        um = getattr(response, "usage_metadata", None)
        if um:
            in_tok = int(getattr(um, "prompt_token_count", 0) or 0)
            out_tok = (
                int(getattr(um, "candidates_token_count", 0) or 0)
                + int(getattr(um, "thoughts_token_count", 0) or 0)
            )
    except Exception:
        pass
    if in_tok == 0 and est_in_chars > 0:
        in_tok = int(est_in_chars * 0.7)
    if out_tok == 0 and est_out_chars > 0:
        out_tok = int(est_out_chars * 0.7)

    if tool_calls_count > 0:
        base_prompt_tok = int(est_in_chars * 0.7)
        avg_tool_tok = int((tool_result_chars * 0.7) / max(1, tool_calls_count))
        intermediate_in_tok = sum(base_prompt_tok + (avg_tool_tok * step) for step in range(tool_calls_count))
        intermediate_out_tok = tool_calls_count * 250
        in_tok += intermediate_in_tok
        out_tok += intermediate_out_tok

    _record_token_usage(model_id, in_tok, out_tok, count_call=count_call)

def is_pro_budget_exceeded(room_key: str = "") -> tuple[bool, float, float]:
    stats = get_room_usage(room_key)
    cur_krw = float(stats.get("total_krw", 0.0))
    limit_krw = float(stats.get("limit_krw", ROOM_LIMIT_KRW))
    return (cur_krw >= limit_krw), cur_krw, limit_krw


# ---------------------------------------------------------
# 🔎 근거 추적·검증 및 VERIFY_MODE ('strict' 기본 설정) 제어
# ---------------------------------------------------------
_TOOL_TRACE = contextvars.ContextVar("tool_trace", default=None)

def _verify_mode() -> str:
    """세 에이전트(범준·두리·가진) 모두 동일하게 3중 검증('strict')으로 작동하도록 통일합니다.
    (과거 Secrets에 VERIFY_MODE="loose"가 남아 있어도 무시하며, FORCE_VERIFY_MODE가 지정된 경우에만 예외 허용)"""
    m = (_get_secret_or_env("FORCE_VERIFY_MODE") or "strict").lower().strip()
    return m if m in ("balanced", "strict", "loose") else "strict"

def _new_trace(unleash: bool = False) -> dict:
    return {
        "list": [],
        "detail": [],
        "articles": set(),
        "fetched_laws": set(),
        "fetched_addenda": set(),
        "mentioned_articles": set(),
        "article_texts": {},
        "addenda_texts": {},
        "law_meta": {},
        "counts": {},
        "id_map": {},
        "meta_map": {},
        "unleash": unleash
    }

def _is_unleashed() -> bool:
    trace = _TOOL_TRACE.get()
    return bool(trace and trace.get("unleash"))

_SEARCH_LIMIT = {"law": 7, "prec": 3, "decc": 3, "detc": 3, "expc": 2, "admrul": 2, "ordin": 2, "licbyl": 2}
_DETAIL_LIMIT = {"law": 12, "eflaw": 6, "prec": 3, "decc": 3, "detc": 3, "expc": 2, "admrul": 2, "ordin": 2, "licbyl": 2}

def _over_limit(kind: str, target: str) -> bool:
    trace = _TOOL_TRACE.get()
    if trace is None:
        return False
    mult = 3 if trace.get("unleash") else 1
    table = _SEARCH_LIMIT if kind == "search" else _DETAIL_LIMIT
    key = f"{kind}:{target}"
    used = trace["counts"].get(key, 0)
    limit_val = table.get(target, 2) * mult
    if used >= limit_val:
        return True
    trace["counts"][key] = used + 1
    return False

_NORM_RE = re.compile(r"[\s「」『』\"'“”‘’]")

def _norm(text: str) -> str:
    return _NORM_RE.sub("", text) if text else ""

def _record(kind: str, text: str) -> str:
    trace = _TOOL_TRACE.get()
    if trace is not None:
        s_txt = text or ""
        trace[kind].append(s_txt)
        trace.setdefault(f"_norm_{kind}_list", []).append(_norm(s_txt))
        trace.pop(f"_norm_{kind}_blob", None)
        if kind == "detail":
            trace.setdefault("_letters_detail_list", []).append(re.sub(r"[^0-9A-Za-z가-힣]", "", s_txt))
    return text

def _record_law_articles(text: str) -> None:
    """
    [본칙(articles)과 부칙(fetched_addenda) 완전 분리 기록 + API 공포번호·시행일자 메타데이터 보존]
    1) 본칙 조문(`제N조`)은 `trace["articles"]` 및 `trace["article_texts"]`에 기록합니다.
    2) 부칙 블록(`부칙 <...>` 또는 `📌 [...부칙...]`) 내부의 부칙 조문(`제N조`)은 `trace["fetched_addenda"]` 및
       `trace["addenda_texts"]`에만 분리 기록하여, 부칙 제34조·제2조·제11조를 조회했을 때 본칙 제34조·제2조·제11조가
       허용되는 키 충돌 문제를 원천 차단합니다.
    3) 본칙 원문 본문 안에서 직접 인용·언급하고 있는 타 법령 본칙 조문은 `mentioned_articles`에, 부칙 조문은 `fetched_addenda`에 각각 분리 기록합니다.
    """
    trace = _TOOL_TRACE.get()
    if trace is None or not text:
        return
    m = re.search(r"📘 \[(.+?)\]", text)
    if not m:
        return
    header_full = m.group(1)
    raw_header = header_full.split("|")[0].strip()
    title = _norm(raw_header)
    if title:
        trace.setdefault("fetched_laws", set()).add(title)
        m_pno = re.search(r"공포번호:\s*([^|\]]+)", header_full)
        m_pdt = re.search(r"공포일자?:\s*([^|\]]+)", header_full)
        m_edt = re.search(r"시행일자?:\s*([^|\]]+)", header_full)
        if m_pno or m_pdt or m_edt:
            trace.setdefault("law_meta", {})[title] = {
                "prom_no": m_pno.group(1).strip() if m_pno else "",
                "prom_date": m_pdt.group(1).strip() if m_pdt else "",
                "enf_date": m_edt.group(1).strip() if m_edt else "",
            }

    # 본칙 영역과 부칙 영역 분리
    add_split = re.search(r"(?m)^(?:\s*📌\s*\[[^\n]*부칙|\s*\[?부칙\s*<)", text)
    if add_split:
        main_part = text[:add_split.start()]
        addenda_part = text[add_split.start():]
    else:
        main_part = text
        addenda_part = ""

    starts = list(re.finditer(r"(?m)^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*\(|\s+)", main_part))
    for n, am in enumerate(starts):
        key = (title, int(am.group(1)), int(am.group(2) or 0))
        trace["articles"].add(key)
        end = starts[n + 1].start() if n + 1 < len(starts) else len(main_part)
        trace["article_texts"][key] = main_part[am.start():end].strip()

    if addenda_part and title:
        fetched_add = trace.setdefault("fetched_addenda", set())
        add_texts = trace.setdefault("addenda_texts", {})
        add_starts = list(re.finditer(r"(?m)^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*\(|\s+)", addenda_part))
        for n, am in enumerate(add_starts):
            akey = (title, int(am.group(1)), int(am.group(2) or 0))
            fetched_add.add(akey)
            end = add_starts[n + 1].start() if n + 1 < len(add_starts) else len(addenda_part)
            chunk_txt = addenda_part[am.start():end].strip()
            if akey not in add_texts or len(chunk_txt) > len(add_texts[akey]):
                add_texts[akey] = chunk_txt

    mentioned = trace.setdefault("mentioned_articles", set())
    fetched_add = trace.setdefault("fetched_addenda", set())
    for law_nm, jo, gaji, is_add in _find_article_refs_with_kind(main_part, trace):
        if is_add:
            fetched_add.add((law_nm, jo, gaji))
        else:
            mentioned.add((law_nm, jo, gaji))

_CASE_NO_PATTERNS = [
    re.compile(r"(?<!\d)((?:19|20)?\d{2})\s?(재두|재다|가합|가단|구합|구단|헌바|헌마|헌가|헌나|헌라|헌사|헌아|두|누|다|도|나|후|허|므|구|부|노|고단|고합)\s?(\d{1,6})(?!\d)"),
    re.compile(r"(?:조심|국심)\s?((?:19|20)\d{2})\s?(서|중|부|광|전|구|인|경|지|관|조)\s?(\d{1,6})(?!\d)"),
]

_ARTICLE_NO = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
_COMMON_LAWS = [
    "상속세및증여세법", "조세특례제한법", "국세기본법", "국세징수법", "법인세법", "소득세법", "부가가치세법",
    "지방세법", "지방세기본법", "지방세특례제한법", "종합부동산세법", "개별소비세법", "교육세법", "농어촌특별세법",
    "인지세법", "증권거래세법", "국제조세조정에관한법률", "조세범처벌법", "중소기업기본법", "근로기준법", "근로자퇴직급여보장법",
    "국민연금법", "국민건강보험법", "노인장기요양보험법", "고용보험법", "산업재해보상보험법",
    "고용보험및산업재해보상보험의보험료징수등에관한법률", "관세법",
    "수출용원재료에대한관세등환급에관한특례법", "자유무역협정의이행을위한관세법의특례에관한법률",
    "주식회사등의외부감사에관한법률", "상법", "민법", "부동산등기법", "건축법",
    "주택임대차보호법", "상가건물임대차보호법", "공익법인의설립ㆍ운영에관한법률",
]
_LAW_ALIASES = {"상증법": "상속세및증여세법", "조특법": "조세특례제한법", "국기법": "국세기본법",
                "국징법": "국세징수법", "부가세법": "부가가치세법", "지특법": "지방세특례제한법",
                "국조법": "국제조세조정에관한법률", "종부세법": "종합부동산세법", "외감법": "주식회사등의외부감사에관한법률",
                "고용산재보험료징수법": "고용보험및산업재해보상보험의보험료징수등에관한법률",
                "산재보험법": "산업재해보상보험법", "환급특례법": "수출용원재료에대한관세등환급에관한특례법",
                "FTA관세특례법": "자유무역협정의이행을위한관세법의특례에관한법률",
                "주임법": "주택임대차보호법", "상임법": "상가건물임대차보호법"}
_REF_SKIP_SUFFIX = ("동법", "같은법", "이법", "본법", "당해법", "해당법", "동법시행령", "같은법시행령", "동법시행규칙")

_BASE_KNOWN_LAW_TITLES: tuple[str, ...] = tuple(
    sorted(
        {t for base in _COMMON_LAWS for t in (base, base + "시행령", base + "시행규칙")},
        key=len,
        reverse=True,
    )
)
_SAME_LAW_RE = re.compile(r"([가-힣ㆍ·]{2,35}?법률?)(?:및|과|와|,|또는)(?:동법|같은법)(시행령|시행규칙)$")
_PARTIAL_LAW_RE = re.compile(r"([가-힣ㆍ·]{2,35}?법률?(?:시행령|시행규칙)?)$")
_HANGUL_END_RE = re.compile(r"[가-힣]$")
_ALIAS_RESOLVED_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (alias_key, full + ext)
    for alias, full in _LAW_ALIASES.items()
    for ext in ("시행규칙", "시행령", "")
    for alias_key in (
        (alias + ext, alias.replace("법", "령")) if (ext == "시행령" and "법" in alias) else (alias + ext,)
    )
)
_PROMULGATION_TRAIL_RE = re.compile(
    r"(?:\s*(?:\([^)]*(?:법률|대통령령|총리령|부령|기획재정부령|행정안전부령|고용노동부령|제\s*\d+\s*호|\d{4}\.\s*\d{1,2})[^)]*\)|"
    r"<[^>]+>|"
    r"(?:법률|대통령령|총리령|기획재정부령|행정안전부령|고용노동부령|부령)\s*제\s*\d+\s*호(?:\s*\([^)]*\))?|\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?))+$"
)
_RESOLVE_LAW_CACHE: dict[str, str | None] = {}
_RESOLVE_LAW_LOCK = threading.RLock()
_RESOLVE_LAW_CACHE_MAX = 4096   # LLM이 만든 임의 문자열이 키가 되므로 상한 없으면 장기 실행 시 메모리 누수


def _bound_resolve_cache() -> None:
    if len(_RESOLVE_LAW_CACHE) > _RESOLVE_LAW_CACHE_MAX:
        with _RESOLVE_LAW_LOCK:
            for k in list(_RESOLVE_LAW_CACHE.keys())[: len(_RESOLVE_LAW_CACHE) // 2]:
                _RESOLVE_LAW_CACHE.pop(k, None)
_ARTICLE_REFS_LINE_CACHE: dict[tuple[str, int], list[tuple]] = {}

def _known_law_titles(trace: dict = None) -> list[str]:
    if not trace:
        return list(_BASE_KNOWN_LAW_TITLES)
    extra = {t for (t, _, _) in trace.get("articles", set())} | set(trace.get("fetched_laws", set()))
    if not extra or extra.issubset(_BASE_KNOWN_LAW_TITLES):
        return list(_BASE_KNOWN_LAW_TITLES)
    return sorted(set(_BASE_KNOWN_LAW_TITLES) | extra, key=len, reverse=True)

def _resolve_law_name(prefix: str, titles: list[str] | tuple[str, ...]):
    _bound_resolve_cache()
    p_str = (prefix or "").strip()
    if not p_str:
        return None
    use_cache = len(titles) == len(_BASE_KNOWN_LAW_TITLES)
    if use_cache and p_str in _RESOLVE_LAW_CACHE:
        return _RESOLVE_LAW_CACHE[p_str]
    if any(ch in p_str for ch in "()<>0123456789"):
        cleaned_prefix = _PROMULGATION_TRAIL_RE.sub("", p_str).strip()
    else:
        cleaned_prefix = p_str
    tail = _norm(cleaned_prefix)[-45:]
    if not tail:
        return None
    if use_cache and tail in _RESOLVE_LAW_CACHE:
        return _RESOLVE_LAW_CACHE[tail]
    m_same = _SAME_LAW_RE.search(tail)
    if m_same:
        res = _resolve_law_name(m_same.group(1) + m_same.group(2), titles)
        if use_cache:
            with _RESOLVE_LAW_LOCK:
                if len(_RESOLVE_LAW_CACHE) < 8192:
                    _RESOLVE_LAW_CACHE[tail] = res
                    _RESOLVE_LAW_CACHE[p_str] = res
        return res
    for suf in _REF_SKIP_SUFFIX:
        if tail == suf or (tail.endswith(suf) and not _HANGUL_END_RE.search(tail[:-len(suf)])):
            if use_cache:
                with _RESOLVE_LAW_LOCK:
                    if len(_RESOLVE_LAW_CACHE) < 8192:
                        _RESOLVE_LAW_CACHE[tail] = None
            return None
    for alias_key, resolved_full in _ALIAS_RESOLVED_PAIRS:
        if tail.endswith(alias_key):
            if use_cache:
                with _RESOLVE_LAW_LOCK:
                    if len(_RESOLVE_LAW_CACHE) < 8192:
                        _RESOLVE_LAW_CACHE[tail] = resolved_full
                        _RESOLVE_LAW_CACHE[p_str] = resolved_full
            return resolved_full
    for t in titles:
        if tail.endswith(t):
            if use_cache:
                with _RESOLVE_LAW_LOCK:
                    if len(_RESOLVE_LAW_CACHE) < 8192:
                        _RESOLVE_LAW_CACHE[tail] = t
                        _RESOLVE_LAW_CACHE[p_str] = t
            return t
    m = _PARTIAL_LAW_RE.search(tail)
    if not m:
        if use_cache:
            with _RESOLVE_LAW_LOCK:
                if len(_RESOLVE_LAW_CACHE) < 8192:
                    _RESOLVE_LAW_CACHE[tail] = None
        return None
    partial = m.group(1)
    if partial in _REF_SKIP_SUFFIX:
        if use_cache:
            with _RESOLVE_LAW_LOCK:
                if len(_RESOLVE_LAW_CACHE) < 8192:
                    _RESOLVE_LAW_CACHE[tail] = None
        return None
    res = partial
    if len(partial) >= 3:
        for t in titles:
            if t.endswith(partial):
                res = t
                break
    if use_cache:
        with _RESOLVE_LAW_LOCK:
            if len(_RESOLVE_LAW_CACHE) < 8192:
                _RESOLVE_LAW_CACHE[tail] = res
                _RESOLVE_LAW_CACHE[p_str] = res
    return res

_EXEC_STD = re.compile(r"(?<![\d의])(\d{1,3}(?:의\d{1,2})?-\d{1,3}(?:의\d{1,2})?-\d{1,3})(?![\d])")

# [보강 ③] 마크다운 표 등에서 콜론(:)이 빠진 [조문 조세특례제한법 제29조의8] 또는 [조문조세특례제한법...] 형태까지 모두 인식
_TAG = re.compile(
    r"\[(판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])([^\]]+)\]"
)
_BACKTICK_LINKED_TAG_RE = re.compile(
    r"`+(\[\[?(?:판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표|행정해석)[^\]`]+\]\]?\(https?://[^)\s`]+\))`+"
)
_BACKTICK_PLAIN_TAG_RE = re.compile(
    r"`+(\[(?:판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표|행정해석)[^\]`]+\])`+"
)
_NORM_TAG_SPACE_RE = re.compile(
    r"\[(판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?:\s*[:：]\s*|\s+)(?=[가-힣A-Za-z0-9「])([^\]]+)\]"
)
_NORM_TAG_NOSPACE_RE = re.compile(
    r"\[(판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?=[가-힣A-Za-z0-9「])([^\]:：\n]+)\]"
)

def _normalize_citation_tags(text: str) -> str:
    """
    [보강 ③ + Feature A]
    1) 백틱(`)으로 감싸진 법령 태그(`` `[조문:...]` ``)나 이미 링크가 걸린 법령 태그(`` `[[조문:...]](https://...)` ``)의
       백틱을 제거하여 모니터 화면에서 초록색 인라인 코드로 깨지지 않고 정상 링크로 렌더링되게 합니다.
    2) 콜론(:)을 누락하여 작성한 `[조문 조세특례제한법 제29조의8]` 형태를 표준 `[조문: ...]` 형식으로 정규화합니다.
    """
    if not text:
        return ""
    s = str(text)
    if "`" in s:
        s = _BACKTICK_LINKED_TAG_RE.sub(r"\1", s)
        s = _BACKTICK_PLAIN_TAG_RE.sub(r"\1", s)
    if "[" in s:
        s = _NORM_TAG_SPACE_RE.sub(r"[\1: \2]", s)
        s = _NORM_TAG_NOSPACE_RE.sub(r"[\1: \2]", s)
    return s

_AUTHORITY = re.compile(r"대법원|판시|판례|심판원|조세심판|심판례|결정례|헌법재판소|헌재|예규|집행기준|유권해석|해석례|질의회신")
_NEGATION = re.compile(r"없음|없습니다|없으며|없고|없어|확인되지|확인하지 못|찾지 못|미조회|조회되지|조회하지 못")
_TEMPLATE_LABELS = ("상세 법리 및 기준 검토", "상세법리 및 기준검토", "실무 적용 및 리스크 주의사항", "실무적용 및 리스크 주의사항", "근거자료 및 검색방법", "근거 자료 및 검색 방법", "관련법령")
_QUOTE = re.compile(r"[“\"]([^”\"]{12,})[”\"]")
_LETTERS_RE = re.compile(r"[^0-9A-Za-z가-힣]")
_QUOTE_SPLIT_RE = re.compile(r"…|\.\.\.|⋯|중략")

def _letters(text: str) -> str:
    return _LETTERS_RE.sub("", text or "")

def _quote_mismatches(line: str, case_nos: list, details: list, trace: dict = None) -> list[str]:
    bad = []
    if trace is not None and len(trace.get("_letters_detail_list") or []) == len(details) and len(trace.get("_norm_detail_list") or []) == len(details):
        norm_details = trace["_norm_detail_list"]
        let_details = trace["_letters_detail_list"]
        if case_nos:
            pool_letters = [let_details[idx] for idx, nd in enumerate(norm_details) if any(n in nd for n in case_nos)]
        else:
            pool_letters = let_details
    else:
        pool = [d for d in details if any(n in _norm(d) for n in case_nos)] if case_nos else details
        pool_letters = [_letters(d) for d in pool]
    for q in _QUOTE.findall(line):
        segments = [seg for seg in _QUOTE_SPLIT_RE.split(q) if len(_letters(seg)) >= 10]
        for seg in segments:
            seg_let = _letters(seg)
            if not any(seg_let in t for t in pool_letters):
                bad.append("판례 인용문이 조회한 원문과 다름: \"" + q[:25] + "…\"")
                break
    return bad

_CASE_FAST_HINT_RE = re.compile(r"\d{2}\s*(?:재두|재다|가합|가단|구합|구단|헌바|헌마|헌가|헌나|헌라|헌사|헌아|두|누|다|도|나|후|허|므|구|부|노|고단|고합|서|중|광|전|인|경|지|관|조)")

def _find_case_numbers(text: str) -> list[str]:
    if not text or not _CASE_FAST_HINT_RE.search(text):
        return []
    cited = []
    for pat in _CASE_NO_PATTERNS:
        for m in pat.finditer(text):
            no = "".join(m.groups())
            if no not in cited:
                cited.append(no)
    return cited

_ADDENDUM_SUFFIX_RE = re.compile(
    r"(?:\s*부칙(?:\s*<[^>]*>|\s*\([^)]*\)|\s*(?:법률|대통령령|총리령|부령)?\s*제\s*\d+\s*호|\s*\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.?)?)+[\s「」『』\[\]:(),·ㆍ]*$"
)
_LAW_END_NORM_RE = re.compile(r"(법률?|령|규칙)$")
_STRIP_TRAIL_PUNCT_RE = re.compile(r"[\s「」『』\[\]:(),·ㆍ]+$")

def _find_article_refs_with_kind(text: str, trace: dict = None, titles: list[str] | None = None) -> list[tuple]:
    if not text or "제" not in text or "조" not in text:
        return []
    if titles is None:
        titles = _known_law_titles(trace)
    cache_key = (text, len(titles)) if len(text) <= 240 else None
    if cache_key is not None and cache_key in _ARTICLE_REFS_LINE_CACHE:
        return list(_ARTICLE_REFS_LINE_CACHE[cache_key])
    refs = []
    last_end = 0
    for m in _ARTICLE_NO.finditer(text):
        prefix = text[max(last_end, m.start() - 75):m.start()]
        last_end = m.end()
        raw_r = prefix.rstrip()
        has_buchik = "부칙" in raw_r[-35:]
        is_addendum = has_buchik and bool(_ADDENDUM_SUFFIX_RE.search(raw_r) or has_buchik)
        stripped = _ADDENDUM_SUFFIX_RE.sub("", raw_r) if has_buchik else raw_r
        if any(ch in stripped for ch in "()<>0123456789"):
            stripped = _PROMULGATION_TRAIL_RE.sub("", stripped)
        stripped = _STRIP_TRAIL_PUNCT_RE.sub("", stripped)
        if has_buchik and "부칙" in stripped:
            stripped = _ADDENDUM_SUFFIX_RE.sub("", stripped)
            if any(ch in stripped for ch in "()<>0123456789"):
                stripped = _PROMULGATION_TRAIL_RE.sub("", stripped)
            stripped = _STRIP_TRAIL_PUNCT_RE.sub("", stripped)
        if not stripped or not _LAW_END_NORM_RE.search(_norm(stripped)):
            continue
        name = _resolve_law_name(stripped, titles)
        if not name:
            continue
        ref = (name, int(m.group(1)), int(m.group(2) or 0), is_addendum)
        if ref not in refs:
            refs.append(ref)
    if cache_key is not None:
        with _RESOLVE_LAW_LOCK:
            if len(_ARTICLE_REFS_LINE_CACHE) < 8192:
                _ARTICLE_REFS_LINE_CACHE[cache_key] = list(refs)
    return refs

def _find_article_refs(text: str, trace: dict = None) -> list[tuple]:
    """하위 호환용 3-튜플 (law_name, jo, gaji) 리스트 반환."""
    out = []
    for name, jo, gaji, _ in _find_article_refs_with_kind(text, trace):
        r3 = (name, jo, gaji)
        if r3 not in out:
            out.append(r3)
    return out

def _article_label(ref: tuple, is_addendum: bool = False) -> str:
    name, jo, gaji = ref[:3]
    buchik_str = " 부칙" if (is_addendum or (len(ref) >= 4 and ref[3])) else ""
    return f"{name}{buchik_str} 제{jo}조" + (f"의{gaji}" if gaji else "")

def _scan_violations(answer: str, trace: dict) -> list[tuple]:
    """
    답변을 줄 단위로 검사해 [(줄번호, [위반 설명...], in_refs_section), ...]을 돌려줍니다.
    - 본칙 조문(is_addendum=False)은 오직 `trace["articles"]`(또는 본문 내 `mentioned_articles`)에 있을 때만 통과시킵니다.
    - 부칙 조문(is_addendum=True)은 `trace["fetched_addenda"]`에 있을 때만 통과시켜,
      부칙 제34조·제2조·제11조 허용이 본칙 제34조·제2조·제11조 허용으로 번지는 현상을 100% 차단합니다.
    """
    if trace.get("_norm_detail_blob") is not None and len(trace.get("_norm_detail_list") or []) == len(trace["detail"]):
        detail_blob = trace["_norm_detail_blob"]
    else:
        detail_blob = _norm(" ".join(trace["detail"]))
        trace["_norm_detail_blob"] = detail_blob
    if trace.get("_norm_list_blob") is not None and len(trace.get("_norm_list_list") or []) == len(trace["list"]):
        list_blob = trace["_norm_list_blob"]
    else:
        list_blob = _norm(" ".join(trace["list"]))
        trace["_norm_list_blob"] = list_blob
    fetched = trace["articles"]
    fetched_addenda = trace.get("fetched_addenda", set())
    fetched_laws = trace.get("fetched_laws", set()) | {t for (t, _, _) in fetched}
    mentioned = trace.get("mentioned_articles", set())
    known_titles = _known_law_titles(trace)

    violations = []
    in_refs_section = False
    parent_stack = []

    for i, line in enumerate(answer.split("\n")):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            in_refs_section = ("근거 자료" in s) or ("근거자료" in s) or ("관련법령" in s) or ("관련 법령" in s)
            parent_stack = []
            continue
        line_cases = []

        indent = len(line) - len(line.lstrip(" "))
        while parent_stack and parent_stack[-1][0] >= indent:
            parent_stack.pop()
        inherited_ok = any(ok for _, ok, _ in parent_stack)
        parent_cases = [n for _, _, nos in parent_stack for n in nos]

        compact = _norm(line)
        problems = []
        verified_source = False

        for no in _find_case_numbers(line):
            if no in detail_blob:
                verified_source = True
            elif no in list_blob and "요지미조회" in compact:
                verified_source = True
            elif no in list_blob:
                problems.append(f"판례·심판례 {no} (목록만 조회, 원문 미조회)")
            else:
                problems.append(f"판례·심판례 {no} (조회 기록 없음)")

        for law_nm, jo, gaji, is_add in _find_article_refs_with_kind(line, trace, titles=known_titles):
            ref3 = (law_nm, jo, gaji)
            if is_add:
                if ref3 in fetched_addenda:
                    verified_source = True
                else:
                    problems.append(f"{_article_label(ref3, is_addendum=True)} (부칙 조문 원문 미조회)")
            else:
                if ref3 in fetched or (not in_refs_section and ref3 in mentioned):
                    verified_source = True
                else:
                    problems.append(f"{_article_label(ref3, is_addendum=False)} (본칙 조문 원문 미조회)")

        for no in _EXEC_STD.findall(line):
            if _norm(no) in detail_blob:
                verified_source = True
            else:
                problems.append(f"집행기준 {no} (원문 미조회)")

        for kind, val in _TAG.findall(line):
            if kind in ("조문", "부칙"):
                refs_kind = _find_article_refs_with_kind(val, trace, titles=known_titles)
                if refs_kind:
                    all_ok = True
                    for r_ln, r_jo, r_gaji, r_is_add in refs_kind:
                        r3 = (r_ln, r_jo, r_gaji)
                        eff_add = r_is_add or (kind == "부칙") or ("부칙" in val)
                        if eff_add:
                            if r3 in fetched_addenda:
                                verified_source = True
                            else:
                                all_ok = False
                                lbl_p = f"{_article_label(r3, is_addendum=True)} (부칙 조문 원문 미조회)"
                                if lbl_p not in problems:
                                    problems.append(lbl_p)
                        else:
                            if r3 in fetched or (not in_refs_section and r3 in mentioned):
                                verified_source = True
                            else:
                                all_ok = False
                                lbl_p = f"{_article_label(r3, is_addendum=False)} (본칙 조문 원문 미조회)"
                                if lbl_p not in problems:
                                    problems.append(lbl_p)
                    if all_ok:
                        verified_source = True
                elif "부칙" in val or kind == "부칙":
                    law_prefix = re.sub(r"부칙.*", "", val).strip()
                    resolved_ln = _resolve_law_name(law_prefix, known_titles) if law_prefix else None
                    if resolved_ln and (resolved_ln in fetched_laws or resolved_ln in detail_blob):
                        verified_source = True
                    elif _norm(val) in detail_blob:
                        verified_source = True
                    else:
                        problems.append(f"[{kind}:{val}] (법령명이 빠져 검증 불가)")
                else:
                    problems.append(f"[조문:{val}] (법령명이 빠져 검증 불가)")
            elif kind == "별표":
                law_prefix = re.sub(r"별표.*", "", val).strip()
                resolved_ln = _resolve_law_name(law_prefix, known_titles) if law_prefix else None
                if _norm(val) in detail_blob or (resolved_ln and (resolved_ln in fetched_laws or resolved_ln in detail_blob)):
                    verified_source = True
                else:
                    problems.append(f"[별표:{val}] (원문 미조회)")
            else:
                nos = _find_case_numbers(val)
                if nos:
                    ok = all(n in detail_blob or (n in list_blob and "요지미조회" in compact) for n in nos)
                else:
                    ok = _norm(val) in detail_blob
                if ok:
                    verified_source = True
                elif not nos:
                    problems.append(f"[{kind}:{val}] (원문 미조회)")

        line_cases = _find_case_numbers(line) + [n for k, v in _TAG.findall(line) if k != "조문" for n in _find_case_numbers(v)]
        if (line_cases or inherited_ok or _TAG.search(line)) and _QUOTE.search(line):
            problems.extend(_quote_mismatches(line, line_cases or parent_cases, trace["detail"], trace=trace))

        if not in_refs_section and not problems:
            body = line
            for lbl in _TEMPLATE_LABELS:
                body = body.replace(lbl, "")
            if (_AUTHORITY.search(body) and not _TAG.search(line) and not verified_source
                    and not inherited_ok and not _NEGATION.search(body)):
                problems.append("출처 표시 없는 판례·예규 서술: \"" + s[:40] + "…\"")

        parent_stack.append((indent, verified_source and not problems, line_cases))
        if problems:
            violations.append((i, problems, in_refs_section))
    return violations

def _violation_labels(violations: list[tuple]) -> list[str]:
    labels = []
    for item in violations:
        probs = item[1]
        for p in probs:
            if p not in labels:
                labels.append(p)
    return labels

def _show_diag() -> bool:
    return _get_secret_or_env("SHOW_DIAGNOSTICS").lower() in ("on", "true", "1")

def _patch_violation_lines(chat, answer: str, violations: list[tuple], trace: dict, model_id: str) -> tuple[str, bool]:
    """
    미검증 근거가 있는 '본문 줄'만 AI에게 보내 해당 줄의 수정본만 받아 끼워 넣습니다(답변 전체 재작성보다 빠름).
    - AI는 필요하면 도구로 원문을 조회한 뒤 근거 표시를 붙이거나, 조회할 수 없으면 그 근거·서술을 빼고 줄을 다시 씁니다.
    - 응답 형식이 깨졌거나 수정본에 여전히 미검증 근거가 남으면 (원문, False)를 돌려 전체 재작성으로 넘어갑니다.
    """
    lines = answer.split("\n")
    targets = [(ln, labels) for ln, labels, in_refs in violations if not in_refs and 0 <= ln < len(lines)]
    if not targets:
        return answer, False
    items = []
    for k, (ln, labels) in enumerate(targets, 1):
        items.append(f"[{k}] 원래 줄: {lines[ln].strip()}\n    문제: {'; '.join(labels)}")
    patch_msg = (
        "방금 답변의 아래 줄들에 도구 조회 기록으로 확인되지 않는 근거가 있습니다.\n\n" + "\n".join(items) + "\n\n"
        "각 줄에 대해 ① 필요하면 get_law_details_for_gemini 등으로 원문을 조회해 확인한 뒤 근거 표시"
        "([조문:정식법령명 제N조], [판례:사건번호] 등)를 붙여 다시 쓰거나, ② 조회할 수 없으면 그 근거와 관련 서술을 빼고 다시 쓰세요"
        "(줄 전체를 지워야 하면 빈 문자열). 다른 줄은 고치지 마세요. 줄 앞의 목록 기호(-, 1), 숫자 등)와 문체는 그대로 유지하세요.\n"
        "출력은 JSON 배열만: [{\"id\": 1, \"text\": \"수정된 한 줄 전체\"}]"
    )
    # 줄 수정은 간단한 작업이므로 이 요청에만 생각량 상한(1024)을 겁니다.
    # (send_message의 config는 대화 설정 전체를 대체하므로 기존 설정(도구·시스템 지시 등)을 복사해 생각량만 추가)
    limited_cfg = None
    try:
        base_cfg = getattr(chat, "_config", None)
        if base_cfg is not None:
            limited_cfg = base_cfg.model_copy(update={"thinking_config": types.ThinkingConfig(thinking_budget=1024)})
    except Exception:
        limited_cfg = None
    trace_token = _TOOL_TRACE.set(trace)
    try:
        try:
            resp = chat.send_message(patch_msg, config=limited_cfg) if limited_cfg is not None else chat.send_message(patch_msg)
        except Exception as e_lim:
            if limited_cfg is None or _is_slow_error(e_lim):
                raise
            print(f"[시스템]    ↳ 부분 수정 생각량 제한 거부({str(e_lim)[:60]}) → 제한 없이 재요청")
            resp = chat.send_message(patch_msg)
        raw = extract_safe_text(resp)
        _extract_and_log_response_usage(resp, model_id, count_call=False, est_in_chars=len(patch_msg), est_out_chars=len(raw))
    except Exception as e:
        print(f"[시스템]    ↳ 부분 수정 요청 실패: {e}")
        return answer, False
    finally:
        _TOOL_TRACE.reset(trace_token)
    m = re.search(r"\[\s*\{.*\}\s*\]", raw or "", flags=re.DOTALL)
    try:
        fixes = json.loads(m.group(0)) if m else None
    except Exception:
        fixes = None
    if not isinstance(fixes, list):
        print("[시스템]    ↳ 부분 수정 응답 형식 오류 → 전체 재작성으로 전환")
        return answer, False
    by_id = {}
    for f in fixes:
        if isinstance(f, dict) and str(f.get("id", "")).isdigit() and isinstance(f.get("text"), str):
            by_id[int(f["id"])] = f["text"].replace("\n", " ").strip()
    if any(k not in by_id for k in range(1, len(targets) + 1)):
        print("[시스템]    ↳ 부분 수정 응답에 빠진 줄이 있음 → 전체 재작성으로 전환")
        return answer, False
    new_lines = list(lines)
    drop = set()
    for k, (ln, _) in enumerate(targets, 1):
        txt = by_id[k]
        if not txt:
            drop.add(ln)
            continue
        lead = lines[ln][: len(lines[ln]) - len(lines[ln].lstrip(" "))]
        new_lines[ln] = lead + txt.lstrip(" ")
    patched = "\n".join(l for i, l in enumerate(new_lines) if i not in drop)
    patched = _clean_latex_for_export(re.sub(r"\s*<br\s*/?>\s*", " / ", patched))
    if any(not in_refs for _, _, in_refs in _scan_violations(patched, trace)):
        print("[시스템]    ↳ 부분 수정 후에도 미검증 근거 남음 → 전체 재작성으로 전환")
        return answer, False
    return patched, True

def _redact_lines(answer: str, violations: list[tuple]) -> str:
    """
    - 지어낸 사건번호('조회 기록 없음')는 어느 모드에서나 즉시 삭제합니다.
    - VERIFY_MODE == 'strict' (기본): 재작성 후에도 남은 모든 미검증 근거 줄을 조용히 삭제합니다.
    - VERIFY_MODE == 'balanced': 지어낸 사건번호 외의 미확인 근거에는 '⚠️(원문 확인 필요)'를 붙입니다.
    - VERIFY_MODE == 'loose': 지어낸 사건번호만 지우고 나머지는 그대로 둡니다.
    """
    vmode = _verify_mode()
    bad = {item[0]: item[1] for item in violations}
    lines = answer.split("\n")
    out = []
    skip_children_indent = None

    for i, line in enumerate(lines):
        s = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if skip_children_indent is not None:
            if s and indent > skip_children_indent:
                continue
            elif s:
                skip_children_indent = None

        if i in bad:
            probs = bad[i]
            has_fake_case = any("판례·심판례" in p and "조회 기록 없음" in p for p in probs)
            should_delete = has_fake_case or (vmode == "strict")

            if should_delete:
                if has_fake_case and len(s) < 65 and (s.endswith(":") or s.endswith(")") or s.endswith("]**")):
                    skip_children_indent = indent
                reasons = [r.split(":")[0] for r in probs]
                reason_txt = "; ".join(dict.fromkeys(reasons))[:120]
                if not _show_diag():
                    print(f"[시스템] 🚫 미검증 근거 삭제: {reason_txt} | {s[:60]}")
                    continue
                out.append(" " * indent + f"- 🚫 *(미검증 근거 삭제: {reason_txt})*")
                continue
            elif vmode == "balanced":
                if "⚠️" not in line:
                    out.append(line + " ⚠️*(원문 확인 필요)*")
                else:
                    out.append(line)
                continue
        out.append(line)
    return "\n".join(out)

def _is_kakao_request(user_query: str) -> bool:
    q = (user_query or "").strip()
    return any(k in q for k in ("카톡", "카카오톡", "문자 초안", "문자 안내", "문자로 보낼"))

def _enforce_pure_kakao_text(text: str) -> str:
    """
    [카톡 안내문 전용 100% 순수 텍스트 & 조문번호 완전 제거 후처리기]
    AI가 습관적으로 별표(**), 마크다운 표(| --- |), 샵(###), 조문번호(제29조의8 등)를 넣더라도
    카톡 붙여넣기 시 기호나 법조문이 절대 노출되지 않도록 순수 텍스트로 자동 정제합니다.
    """
    if not text:
        return ""
    s = text
    # 1) 대괄호 출처 태그 및 마크다운 링크 제거
    s = re.sub(r"\[(?:\[)?(?:판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)[^\]]*\](?:\([^)]*\))?", "", s)
    s = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", s)
    # 2) 괄호로 묶인 법령·조문 표기 제거 (예: (조세특례제한법 제29조의8), (제29조의8 제1항))
    s = re.sub(r"\([^)\n]*제\s*\d+\s*조[^)\n]*\)", "", s)
    # 3) 문장 내 법령명+조문번호 또는 단독 조문번호(제N조의M 제N항 제N호) 깔끔하게 제거 (줄바꿈 보존)
    s = re.sub(
        r"[「『]?[가-힣ㆍ· ]{2,25}(?:법률?|시행령|시행규칙)[」』]?[ ]*제[ ]*\d+[ ]*조(?:[ ]*의[ ]*\d+)?(?:[ ]*제[ ]*\d+[ ]*[항호목])*(?:[ ]*(?:에[ ]*따르면|에[ ]*따른|에[ ]*따라|에[ ]*의하면|에[ ]*의한|규정에[ ]*따르면|규정에[ ]*따라|상))?[ ]*",
        "",
        s
    )
    s = re.sub(r"제[ ]*\d+[ ]*조(?:[ ]*의[ ]*\d+)?(?:[ ]*제[ ]*\d+[ ]*[항호목])*[ ]*", "", s)
    # 4) 마크다운 굵게(**), 기울임(*), 취소선(~~), 인라인 코드(`) 기호 완전 제거
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = re.sub(r"__(.*?)__", r"\1", s)
    s = re.sub(r"~~(.*?)~~", r"\1", s)
    s = s.replace("`", "").replace("「", "").replace("」", "").replace("『", "").replace("』", "")
    # 5) 마크다운 표(| --- |)가 있다면 카톡용 단순 줄바꿈 텍스트로 자동 변환
    lines = s.split("\n")
    out_lines = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and line.endswith("|"):
            t_rows = []
            while i < len(lines):
                r_line = lines[i].strip()
                if not (r_line.startswith("|") and r_line.endswith("|")):
                    break
                if not re.match(r"^\|[\s\-:|]+\|$", r_line):
                    cells = [c.strip() for c in r_line.strip("|").split("|") if c.strip()]
                    if cells:
                        t_rows.append(cells)
                i += 1
            if len(t_rows) >= 2:
                headers = t_rows[0]
                for row in t_rows[1:]:
                    if len(row) == 2:
                        out_lines.append(f"- {row[0]} : {row[1]}")
                    else:
                        pairs = [f"{headers[idx]} {val}" if idx < len(headers) else val for idx, val in enumerate(row)]
                        out_lines.append("- " + " / ".join(pairs))
            continue
        # 6) 마크다운 헤더(### 등) 제거 후 깔끔한 대괄호 소제목으로 변환
        m_hdr = re.match(r"^#{1,6}\s*(.+)$", line)
        if m_hdr:
            hdr_txt = re.sub(r"^\d+\.\s*", "", m_hdr.group(1).strip())
            if not (hdr_txt.startswith("[") and hdr_txt.endswith("]")):
                hdr_txt = f"[{hdr_txt}]"
            out_lines.append(hdr_txt)
        elif re.match(r"^-{3,}$", line):
            pass
        else:
            # 글머리 기호(* )를 깔끔한 하이픈(- )으로 통일
            cleaned_line = re.sub(r"^(\s*)\*\s+", r"\1- ", lines[i])
            cleaned_line = re.sub(r"  +", " ", cleaned_line).rstrip()
            out_lines.append(cleaned_line)
        i += 1
    res = "\n".join(out_lines)
    res = re.sub(r"\n{3,}", "\n\n", res).strip()
    return res

def _strip_fake_cases_in_track2(answer: str, trace: dict, user_query: str = "") -> str:
    """트랙 2(카톡·이메일 초안 등 자유 양식)에서 미조회 사건번호를 제거하고, 카톡 요청 시 100% 순수 텍스트·조문번호 제거를 강제합니다."""
    if not answer:
        return answer
    out_text = answer
    if trace is not None:
        detail_blob = _norm(" ".join(trace["detail"]))
        list_blob = _norm(" ".join(trace["list"]))
        out_lines = []
        for line in out_text.split("\n"):
            fake_nos = [
                no for no in _find_case_numbers(line)
                if (no not in detail_blob and no not in list_blob)
            ]
            if fake_nos:
                print(f"[시스템] 🚫 트랙 2 미조회 사건번호 제거: {fake_nos}")
                continue
            out_lines.append(line)
        out_text = "\n".join(out_lines)
    if _is_kakao_request(user_query):
        out_text = _enforce_pure_kakao_text(out_text)
    return out_text

# ---------------------------------------------------------
# 🧪 의미 검증 (검증 모델 — 감수기 원문 글자 수 12,000자 무손실 유지 + 정밀 계산 결과 최우선 포함 + 경량 사고 버짓)
# ---------------------------------------------------------
def _strip_md(text: str) -> str:
    return re.sub(r"[*_`>#]", "", text or "").strip(" -")

def _extract_claims(answer: str, trace: dict, max_claims: int = 20) -> tuple[list, dict]:
    mult = 3 if trace.get("unleash") else 1
    effective_max_claims = max_claims * mult
    src_char_cap = 12000 * mult
    total_char_cap = 60000 * mult

    details = trace["detail"]
    art_texts = trace.get("article_texts", {})
    sources, src_index = {}, {}

    def _src_id(label: str, text: str) -> str:
        if label not in src_index:
            sid = f"S{len(src_index) + 1}"
            src_index[label] = sid
            if len(text) > src_char_cap:
                clipped = (
                    text[:src_char_cap]
                    + f"\n...[※ 원문 총 {len(text):,}자 중 앞 {src_char_cap:,}자만 표시됨. 생략된 뒷부분에 있을 수 있는 내용은 unsupported로 단정하지 말 것]"
                )
            else:
                clipped = text
            sources[sid] = (label, clipped)
        return src_index[label]

    claims = []
    in_refs = False
    stack = []
    for i, line in enumerate(answer.split("\n")):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            in_refs = ("근거 자료" in s) or ("근거자료" in s) or ("관련법령" in s) or ("관련 법령" in s)
            stack = []
            continue
        if in_refs:
            continue
        indent = len(line) - len(line.lstrip(" "))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent_cases = [n for _, nos in stack for n in nos]

        tags = _TAG.findall(line)
        line_cases = [n for n in _find_case_numbers(line) if any(n in _norm(d) for d in details)]
        stack.append((indent, line_cases))

        src_ids = []
        add_texts = trace.get("addenda_texts", {})
        for kind, val in tags:
            if kind in ("조문", "부칙"):
                for r_ln, r_jo, r_gaji, r_is_add in _find_article_refs_with_kind(val, trace):
                    ref = (r_ln, r_jo, r_gaji)
                    if (r_is_add or kind == "부칙" or "부칙" in val) and ref in add_texts:
                        src_ids.append(_src_id(_article_label(ref, is_addendum=True), add_texts[ref]))
                    elif ref in art_texts:
                        src_ids.append(_src_id(_article_label(ref, is_addendum=False), art_texts[ref]))
                if "부칙" in val or kind == "부칙":
                    for d in details:
                        if "부칙" in d:
                            src_ids.append(_src_id(f"부칙 {val}", d))
            else:
                nos = _find_case_numbers(val)
                for d in details:
                    nd = _norm(d)
                    if (nos and any(n in nd for n in nos)) or (not nos and _norm(val) in nd):
                        src_ids.append(_src_id(f"{kind} {val}", d))
        body = _strip_md(_TAG.sub("", line))
        if not tags:
            cases = line_cases if (line_cases and len(body) >= 40) else (parent_cases if len(body) >= 15 else [])
            for n in cases:
                for d in details:
                    if n in _norm(d):
                        src_ids.append(_src_id(f"판례 {n}", d))
        src_ids = list(dict.fromkeys(src_ids))
        if src_ids and len(body) >= 15:
            claims.append({"line": i, "text": body[:400], "sources": src_ids})
        if len(claims) >= effective_max_claims:
            break

    # 파이썬 정밀 계산기 산출 내역(`🧮 [정밀 계산 완료...`)을 최우선 포함하고,
    # 이어서 조회한 모든 조문 및 판례 원문을 원문 글자 수 축소 없이(12,000자 * mult) 그대로 전달합니다.
    total = sum(len(t) for _, t in sources.values())
    for idx, d in enumerate(details):
        if d.startswith("🧮"):
            head = d.split("\n", 1)[0][:55]
            if head not in src_index and total < total_char_cap:
                _src_id(head, d)
                total += min(len(d), src_char_cap)
    for key, txt in art_texts.items():
        label = _article_label(key)
        if label not in src_index and total < total_char_cap:
            _src_id(label, txt)
            total += min(len(txt), src_char_cap)
    for idx, d in enumerate(details):
        head = d.split("\n", 1)[0][:55]
        if head in src_index:
            head = f"{head} (#{idx + 1})"
        if total < total_char_cap:
            _src_id(head, d)
            total += min(len(d), src_char_cap)
    return claims, sources

_VERIFY_INFO = threading.local()

def get_last_verify_info() -> dict:
    """현재 스레드에서 마지막으로 실행된 의미 검증의 모델·설정·소요 시간."""
    return dict(getattr(_VERIFY_INFO, "data", {}) or {})

def _semantic_verify(api_key: str, claims: list, sources: dict, user_query: str = "", full_user_input: str = "") -> dict:
    _emit_live_status("🛡️ 3단계: 듀얼 AI 감수(_semantic_verify) 정밀 판정 중...")
    src_block = "\n\n".join(f"[{sid}] {label}\n{text}" for sid, (label, text) in sources.items())
    claim_block = "\n".join(f"{n + 1}. (근거: {', '.join(c['sources'])}) {c['text']}" for n, c in enumerate(claims))
    _kst_v = get_kst_today_context()
    prompt = (
        f"당신은 세무 답변의 근거를 검증하는 감수자입니다. (현재 기준일: {_kst_v['dot_full']}, 당해 과세연도: {_kst_v['year']}년 귀속 — 질문에 연도 지정이 없으면 {_kst_v['year']}년 귀속·현행법 적용이 정상이며, 반대로 질문에서 '24년' 등 과거 연도를 지정했거나 부칙 경과조치 대상이면 해당 과거 연도 구법·종전규정을 적용한 것이 정상입니다.) 아래 [사용자 질문(사례 전제)]와 [원문(법령·판례·계산 결과)] 전체를 기준으로 각 [주장]의 '핵심 법적 명제'가 뒷받침되는지 판정하세요.\n"
        "- supported: 핵심 법리가 [원문]에 부합하고, 사례 금액·계산값이 [사용자 질문] 또는 [정밀 계산 완료] 내역과 일치함. 특히 법령 원문의 천분율·만분율(예: 1천분의 70.9, 1천분의 90, 1만분의 91.82)을 백분율(%)로 환산한 수치나 노사 절반(50%, 1/2) 부담분으로 나눈 수치(예: 3.545%, 4.5%, 0.4591%, 건보료 대비 12.95% 등), 같은 뜻의 요약·의역, 원문들을 결합해 도출되는 당연한 세무조정·소득처분 결론은 모두 supported로 판정할 것\n"
        "- partial: 법령상의 고정 기준 수치(예: 세율, 법정한도율, 기준금액)를 [원문]의 환산값과도 다르게 잘못 적은 경우에만 부여할 것. (사용자 질문의 사례 금액이나 단위 환산·절반 분담 계산값이 법조문 글자와 표기 형태만 다르다는 이유로 partial을 주지 말 것!)\n"
        "- unsupported: 핵심 법리 자체가 [원문]과 정면으로 모순되는 경우 (원문이 일부 생략된 표시가 있을 때는 생략된 부분에 있을 수 있으므로 함부로 unsupported를 주지 말 것)\n"
        "원문 밖의 지식으로 판단하지 마세요. 사소한 표현 차이로 partial/unsupported를 주지 말 것. "
        "reason은 한국어 30자 이내로, 'S1' 같은 번호 대신 법령·판례 이름으로 쓰세요.\n"
        '출력은 JSON 배열만: [{"id": 1, "verdict": "supported", "reason": "..."}]\n\n'
        f"[사용자 질문(사례 전제)]\n{_prepare_semantic_verify_query(user_query, full_user_input, 3000)}\n\n[원문]\n{src_block}\n\n[주장]\n{claim_block}"
    )
    client = make_genai_client(api_key, 50000)

    verifier_candidates = _get_verifier_candidates()
    _VERIFY_INFO.data = {}
    _t_verify = time.time()
    used_cfg = ""
    fast_err = ""
    failed_models: list[str] = []
    resp = None
    used_v_model = VERIFIER_MODEL_ID
    last_v_err = None
    for vm_id in verifier_candidates:
        _t_vm = time.time()
        try:
            # [속도 개선 ④] 감수기가 단위 환산(천분율→백분율 등)과 복합 조문 논리는 정확히 계산하되
            # 과도한 장문 추론으로 지연되지 않도록 thinking_budget=1024(핵심 추론 보장)를 부여하여 지능 저하 없이 속도만 단축합니다.
            try:
                fast_cfg = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    thinking_config=types.ThinkingConfig(thinking_budget=1024),
                )
                resp = client.models.generate_content(model=vm_id, contents=prompt, config=fast_cfg)
                used_cfg = "생각 제한 1024"
            except Exception as e_fast:
                if _is_slow_error(e_fast) or _is_model_not_found(e_fast):
                    raise
                m_fc = re.search(r"\b(4\d\d|5\d\d)\b", str(e_fast))
                fast_err = m_fc.group(1) if m_fc else str(e_fast).splitlines()[0][:40]
                std_cfg = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
                resp = client.models.generate_content(model=vm_id, contents=prompt, config=std_cfg)
                used_cfg = f"생각 제한 없음(제한 설정 거부: {fast_err})"
            used_v_model = vm_id
            break
        except Exception as e:
            last_v_err = e
            m_vc = re.search(r"\b(4\d\d|5\d\d)\b", str(e))
            v_code = m_vc.group(1) if m_vc else ("시간 초과" if _is_slow_error(e) else str(e).splitlines()[0][:30])
            failed_models.append(f"{vm_id}: {v_code} · {time.time() - _t_vm:.0f}초")
            if _is_slow_error(e):
                _mark_slow_model(vm_id)
            continue
    _VERIFY_INFO.data = {"model": used_v_model if resp is not None else "", "cfg": used_cfg,
                         "secs": time.time() - _t_verify, "failed": failed_models}
    if resp is None:
        raise last_v_err or RuntimeError("감수 모델 호출 실패")

    raw = extract_safe_text(resp)
    _extract_and_log_response_usage(resp, used_v_model, count_call=False, est_in_chars=len(prompt), est_out_chars=len(raw))
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
    data = json.loads(raw)
    result = {}
    for item in data if isinstance(data, list) else []:
        try:
            cid = int(item.get("id"))
            verdict = str(item.get("verdict", "")).strip().lower()
            if verdict in ("supported", "partial", "unsupported"):
                reason = str(item.get("reason", ""))[:60]
                for sid, (label, _) in sources.items():
                    reason = re.sub(rf"\b{sid}\b", label[:30], reason)
                result[cid] = (verdict, reason)
        except Exception:
            continue
    return result

def _apply_semantic_results(answer: str, claims: list, verdicts: dict, sources: dict = None) -> tuple[str, dict]:
    vmode = _verify_mode()
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "unknown": 0}
    line_actions = {}
    for n, c in enumerate(claims):
        verdict, reason = verdicts.get(n + 1, ("unknown", ""))
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict in ("partial", "unsupported"):
            line_actions[c["line"]] = (verdict, reason)
            print(f"[시스템] 🧪 의미 검증 감지({verdict}): {reason} | {c['text'][:60]}")

    if not line_actions or vmode == "loose":
        return answer, counts

    out_lines = []
    for idx, line in enumerate(answer.split("\n")):
        if idx in line_actions:
            v_type, r_txt = line_actions[idx]
            if v_type == "unsupported" and vmode == "strict":
                if _show_diag():
                    indent = len(line) - len(line.lstrip(" "))
                    out_lines.append(" " * indent + f"- 🚫 *(의미 검증 불일치 삭제: {r_txt})*")
                continue
            else:
                if "⚠️" not in line:
                    note_str = f" ⚠️*(원문 확인 필요: {r_txt})*" if r_txt else " ⚠️*(원문 확인 필요)*"
                    out_lines.append(line + note_str)
                else:
                    out_lines.append(line)
                continue
        out_lines.append(line)
    return "\n".join(out_lines), counts


# ---------------------------------------------------------
# ✨ 스마트 법령 텍스트 압축기 (복합 조문 균등 추출 + 조문당 20,000자 확대) & 법령 전체 XML 통합 캐시
# ---------------------------------------------------------
def _fetch_full_law_xml_direct(doc_id: str, query_filter: str = "") -> str:
    """
    [속도 개선 ② & ③ + 부칙 무손실 파싱 캐시(`full_law_parsed`)]
    1) 법령 전체 XML을 하루 1회만 다운로드하여 조문 전체와 부칙 전체(개수 제한 없음)를
       구조화된 형태(`full_law_parsed`)로 메모리에 저장합니다.
    2) 조회 순서(조문 필터 없음 → 조문 필터 있음, 또는 서로 다른 조문 연속 조회)와 무관하게
       네트워크 재다운로드 없이 메모리에서 0.001초 만에 본칙 관련 부칙 전체(`[본칙관련]`)를 선별·조립합니다.
    """
    clean_id = str(doc_id).strip()
    if not clean_id.isdigit():
        return ""
    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    full_cache_key = ("full_law_xml", today_ymd, clean_id)
    parsed_cache_key = ("full_law_parsed", today_ymd, clean_id)

    qf_no_buchik = re.sub(r"부칙\s*제\s*\d+\s*조(?:\s*의\s*\d+)?", "", query_filter or "")
    req_main_tuples = [
        (int(m[0]), int(m[1]) if m[1] else 0)
        for m in re.findall(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?", qf_no_buchik)
    ]
    req_main_prefixes = list(dict.fromkeys(
        f"제{jo}조" + (f"의{gaji}" if gaji else "") for jo, gaji in req_main_tuples
    ))

    parsed_data = _cache_get(parsed_cache_key)
    if parsed_data is None:
        # 하위호환: 외부에서 full_law_xml 문자열만 직접 넣어둔 경우이고 조문 필터가 없으면 그대로 반환
        if not req_main_prefixes:
            cached_full = _cache_get(full_cache_key)
            if cached_full is not None:
                return cached_full

        oc = get_law_oc_auto()
        if not oc:
            return ""
        id_param_order = ("ID", "MST") if clean_id.startswith("0") else ("MST", "ID")
        for id_param in id_param_order:
            url = f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&{id_param}={clean_id}&type=XML"
            try:
                xml_bytes = _http_get_bytes_fast(url, timeout=15)
                root = ET.fromstring(xml_bytes)
                lname = (root.findtext(".//법령명_한글") or root.findtext(".//법령명한글") or "").strip()
                if not lname:
                    continue
                law_prom_no = (root.findtext(".//공포번호") or "").strip()
                law_prom_dt = re.sub(r"\D", "", root.findtext(".//공포일자") or "")
                law_eff_dt = re.sub(r"\D", "", root.findtext(".//시행일자") or "")
                prom_no_str = f" | 공포번호: 제{law_prom_no}호" if law_prom_no else ""
                prom_dt_str = f" | 공포일자: {law_prom_dt[:4]}.{law_prom_dt[4:6]}.{law_prom_dt[6:]}" if len(law_prom_dt) == 8 else ""
                eff_dt_str = f" | 시행일자: {law_eff_dt[:4]}.{law_eff_dt[4:6]}.{law_eff_dt[6:]}" if len(law_eff_dt) == 8 else ""
                header_meta_suffix = f"{prom_no_str}{prom_dt_str}{eff_dt_str}"

                parsed_articles = []
                for unit in root.findall(".//조문단위"):
                    jo_content = (unit.findtext("조문내용") or "").strip()
                    if not jo_content:
                        continue
                    u_jo = int(re.sub(r"\D", "", unit.findtext("조문번호") or "") or 0)
                    u_gaji = int(re.sub(r"\D", "", unit.findtext("조문가지번호") or "") or 0)
                    lines = [jo_content]
                    for hang in unit.findall(".//항"):
                        h_txt = (hang.findtext("항내용") or "").strip()
                        if h_txt:
                            lines.append(h_txt)
                        for ho in hang.findall(".//호"):
                            ho_txt = (ho.findtext("호내용") or "").strip()
                            if ho_txt:
                                lines.append("  " + ho_txt)
                            for mok in ho.findall(".//목"):
                                mok_txt = (mok.findtext("목내용") or "").strip()
                                if mok_txt:
                                    lines.append("    " + mok_txt)
                    u_eff = re.sub(r"\D", "", unit.findtext("조문시행일자") or "")
                    if len(u_eff) == 8 and u_eff.isdigit():
                        _today_i = int(get_kst_today_context()["ymd"])
                        if int(u_eff) > _today_i:
                            lines.append(
                                f"[조문시행일자: {u_eff[:4]}.{u_eff[4:6]}.{u_eff[6:]} — "
                                f"🚨 미시행(미래 시행예정) 조문 경고: 이미 개정·공포되었으나 오늘({get_kst_today_context()['dot_full']}) 기준 아직 시행일이 도래하지 않았으므로 당해 연도({get_kst_today_context()['year']}년 귀속)에 지금부터 적용 금지!]"
                            )
                        else:
                            lines.append(f"[조문시행일자: {u_eff[:4]}.{u_eff[4:6]}.{u_eff[6:]} — ✅ 현재 시행 중]")
                    full_unit_txt = "\n".join(lines)
                    parsed_articles.append((u_jo, u_gaji, full_unit_txt))

                if not parsed_articles:
                    continue

                parsed_addenda = []
                for a_unit in root.findall(".//부칙단위"):
                    anc_dt = re.sub(r"\D", "", a_unit.findtext("부칙공포일자") or "")
                    anc_no = (a_unit.findtext("부칙공포번호") or "").strip()
                    a_body = (a_unit.findtext("부칙내용") or "").strip()
                    if not a_body:
                        a_body = "\n".join(t.strip() for t in a_unit.itertext() if t and t.strip())
                    if not a_body:
                        continue
                    dt_fmt = f"{anc_dt[:4]}.{anc_dt[4:6]}.{anc_dt[6:]}." if len(anc_dt) == 8 else anc_dt
                    no_fmt = f"제{anc_no}호, " if anc_no else ""
                    dt_int = int(anc_dt) if anc_dt.isdigit() else 0
                    parsed_addenda.append((dt_int, anc_dt, no_fmt, dt_fmt, a_body))

                parsed_addenda.sort(key=lambda x: x[0], reverse=True)
                header_line = f"📘 [{lname}{header_meta_suffix}]"
                parsed_data = {
                    "header": header_line,
                    "lname": lname,
                    "eff_dt": law_eff_dt,
                    "prom_no": law_prom_no,
                    "articles": parsed_articles,
                    "addenda": parsed_addenda,
                }
                _cache_set(parsed_cache_key, parsed_data)

                # 기본(필터 없는) 25개 부칙 버전도 함께 캐싱하여 하위호환 보장
                default_blocks = [txt for _, _, txt in parsed_articles] + [
                    f"부칙 <{no_fmt}{dt_fmt}>\n{a_body}"
                    for _, _, no_fmt, dt_fmt, a_body in parsed_addenda[:25]
                ]
                default_full_text = header_line + "\n\n" + "\n\n".join(default_blocks)
                _cache_set(full_cache_key, default_full_text)
                if law_eff_dt or law_prom_no:
                    _cache_set(("full_law_xml_ver", lname.replace(" ", ""), law_eff_dt, law_prom_no), default_full_text)
                break
            except Exception:
                continue

    if parsed_data is None:
        return ""

    if not req_main_prefixes:
        cached_default = _cache_get(full_cache_key)
        if cached_default is not None:
            return cached_default
        default_blocks = [txt for _, _, txt in parsed_data["articles"]] + [
            f"부칙 <{no_fmt}{dt_fmt}>\n{a_body}"
            for _, _, no_fmt, dt_fmt, a_body in parsed_data["addenda"][:25]
        ]
        return parsed_data["header"] + "\n\n" + "\n\n".join(default_blocks)

    matched_art_rev_dates: set[str] = set()
    related_main_prefixes: list[str] = list(req_main_prefixes)
    article_blocks: list[str] = []

    for u_jo, u_gaji, full_unit_txt in parsed_data["articles"]:
        article_blocks.append(full_unit_txt)
        is_req_unit = (u_jo, u_gaji) in req_main_tuples or any(
            full_unit_txt.replace(" ", "").startswith(tp + "(")
            or re.match(rf"^{re.escape(tp)}(?![0-9의])", full_unit_txt.replace(" ", ""))
            for tp in req_main_prefixes
        )
        if is_req_unit:
            for m_dt in re.findall(r"((?:19|20)\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})", full_unit_txt):
                matched_art_rev_dates.add(f"{int(m_dt[0]):04d}{int(m_dt[1]):02d}{int(m_dt[2]):02d}")
            u_no_other = re.sub(
                r"[「『][^」』]+[」』](?:\s*시행령|\s*시행규칙)?(?:\s*제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*제\s*\d+\s*항)?(?:\s*제\s*\d+\s*호)?)+",
                "",
                full_unit_txt,
            )
            for m_rel in re.findall(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?", u_no_other):
                rp = f"제{m_rel[0]}조" + (f"의{m_rel[1]}" if m_rel[1] else "")
                if rp not in related_main_prefixes:
                    related_main_prefixes.append(rp)

    related_addenda_units = []
    other_addenda_units = []
    for dt_int, anc_dt, no_fmt, dt_fmt, a_body in parsed_data["addenda"]:
        non_tabeop_body = _strip_tabeop_articles_from_addendum_body(a_body)
        body_no_own_hdr = re.sub(r"(?m)^\s*제\s*\d+\s*조(?:\s*의\s*\d+)?\s*\([^)]*\)", "", non_tabeop_body)
        body_clean = body_no_own_hdr.replace(" ", "")
        has_art_ref = bool(
            body_clean and any(
                re.search(rf"{re.escape(tp)}(?![0-9의])", body_clean)
                for tp in related_main_prefixes
            )
        )
        has_date_ref = bool(anc_dt and anc_dt in matched_art_rev_dates and non_tabeop_body.strip())
        if has_art_ref or has_date_ref:
            related_addenda_units.append((dt_int, f"부칙 <{no_fmt}{dt_fmt}> [본칙관련]\n{a_body}"))
        else:
            other_addenda_units.append((dt_int, f"부칙 <{no_fmt}{dt_fmt}>\n{a_body}"))

    for _, a_blk in related_addenda_units:
        article_blocks.append(a_blk)
    for _, a_blk in other_addenda_units[:10]:
        article_blocks.append(a_blk)

    return parsed_data["header"] + "\n\n" + "\n\n".join(article_blocks)

def _resolve_law_id_if_name(doc_id: str) -> str:
    """
    [속도 개선 ①] AI가 search_law_for_gemini를 거치지 않고 doc_id 자리에
    '조세특례제한법', '법인세법 시행령' 등 법령명을 직접 넣었을 때
    프리워밍된 메모리 캐시(0.001초) 또는 즉시 검색을 통해 자동으로 법령일련번호(ID)로 변환합니다.
    """
    s_id = str(doc_id or "").strip()
    if not s_id or s_id.isdigit():
        return s_id

    clean_q = re.sub(r"[「」『』\[\]\"']", "", s_id).strip()
    clean_norm = clean_q.replace(" ", "")
    for alias, full in _LAW_ALIASES.items():
        if clean_norm == alias:
            clean_q = full
            clean_norm = full
            break
        elif clean_norm == alias + "시행령" or clean_norm == alias[:-1] + "령":
            clean_q = full + " 시행령"
            clean_norm = full + "시행령"
            break
        elif clean_norm == alias + "시행규칙" or clean_norm == alias[:-1] + "규칙":
            clean_q = full + " 시행규칙"
            clean_norm = full + "시행규칙"
            break

    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    map_key = ("law_name_to_id", today_ymd, clean_norm)
    cached_id = _cache_get(map_key)
    if cached_id:
        return cached_id

    try:
        res = law_api.search_law_data(clean_q, "law")
        if res:
            if isinstance(res, dict):
                res = [res]
            exact = [it for it in res if str(it.get("법령명한글", "")).replace(" ", "") == clean_norm]
            cands = _sort_law_candidates_for_today(exact if exact else res[:1])
            found_id = str(cands[0].get("법령일련번호") or cands[0].get("법령ID") or "").strip()
            if found_id:
                _cache_set(map_key, found_id)
                print(f"[시스템] 🔄 법령명 자동 ID 변환 완료: '{doc_id}' -> ID '{found_id}'")
                return found_id
    except Exception:
        pass
    return s_id


def _is_tabeop_addendum_article(art_chunk: str) -> bool:
    """
    [문제 3 해결] 부칙 내부의 개별 조문('제n조(제목) ...')이 '다른 법령의 개정(타법개정)' 조문인지 판별합니다.
    - 제목이 '다른 법령의 개정'/'다른 법령의 폐지'이거나,
    - 본문이 '○○법(시행령·시행규칙) 일부를 다음과 같이 개정한다' 형태인 경우 True를 반환하여
      조문번호·날짜·폴백 매칭 대상에서 모두 제외합니다.
    """
    if not art_chunk:
        return False
    c_ns = re.sub(r"\s+", "", art_chunk)
    m_title = re.match(r"^제\d+조(?:의\d+)?\(([^)]*)\)", c_ns)
    if m_title and ("다른법령의개정" in m_title.group(1) or "다른법령의폐지" in m_title.group(1)):
        return True
    if "다른법령의개정)" in c_ns[:40]:
        return True
    if "일부를다음과같이개정한다" in c_ns:
        return True
    return False


def _strip_tabeop_articles_from_addendum_body(add_body: str) -> str:
    """부칙 본문을 자체 조문(제n조) 단위로 나누어 타법개정 조문을 제거한 순수 부칙 본문을 반환합니다."""
    if not add_body:
        return ""
    starts = list(re.finditer(r"(?m)^\s*제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*\(|\s+)", add_body))
    if not starts:
        return "" if _is_tabeop_addendum_article(add_body) else add_body
    kept = []
    prefix_before = add_body[:starts[0].start()].strip()
    if prefix_before and not _is_tabeop_addendum_article(prefix_before):
        kept.append(prefix_before)
    for idx, m in enumerate(starts):
        end_p = starts[idx + 1].start() if idx + 1 < len(starts) else len(add_body)
        chunk = add_body[m.start():end_p].strip()
        if not _is_tabeop_addendum_article(chunk):
            kept.append(chunk)
    return "\n".join(kept)


def _split_main_and_addenda_blocks(text: str) -> tuple[str, list[str], list[tuple[str, str]]]:
    """
    [문제 4 해결] 단순 '\n\n' 분할 시 부칙 내부의 빈 줄 때문에 부칙 조문(예: 제2조)이 쪼개져
    본칙 후보로 잘못 분류되는 현상을 원천 방지합니다.
    - 첫 '부칙 <' (또는 '📌 [...부칙...]') 이전 영역만 본칙 영역으로 삼아 '\n\n' 단위로 나누고,
    - 첫 '부칙 <' 이후 영역은 다음 '부칙 <' 줄이 나올 때까지 내부 빈 줄과 무관하게 하나의 부칙 블록으로 묶습니다.
    """
    if not text:
        return "", [], []
    lines = text.splitlines()
    header = lines[0].strip() if lines else ""
    body_text = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

    first_add_m = re.search(r"(?m)^\s*(?:📌\s*\[[^\n]*부칙|\[?부칙(?:\([^)]*\))?\s*<)", body_text)
    if first_add_m:
        main_part = body_text[:first_add_m.start()].strip()
        add_part = body_text[first_add_m.start():].strip()
    else:
        main_part = body_text
        add_part = ""

    main_blocks = [b.strip() for b in re.split(r"\n\s*\n", main_part) if b.strip()]

    raw_addenda_blocks: list[tuple[str, str]] = []
    if add_part:
        # '📌 [...]' 안내 줄은 제거하고 '부칙 <...' 시작 줄 기준으로 블록을 묶음
        add_lines = [ln for ln in add_part.splitlines() if not ln.strip().startswith("📌")]
        add_joined = "\n".join(add_lines).strip()
        add_starts = list(re.finditer(r"(?m)^\s*\[?부칙(?:\([^)]*\))?\s*<", add_joined))
        if add_starts:
            for idx, am in enumerate(add_starts):
                end_p = add_starts[idx + 1].start() if idx + 1 < len(add_starts) else len(add_joined)
                blk_s = add_joined[am.start():end_p].strip()
                if blk_s:
                    raw_addenda_blocks.append((blk_s, re.sub(r"\s+", "", blk_s)))
        elif add_joined:
            raw_addenda_blocks.append((add_joined, re.sub(r"\s+", "", add_joined)))

    return header, main_blocks, raw_addenda_blocks


def _waterfill_allocate_quotas(lengths: list[int], total_budget: int) -> list[int]:
    """
    [문제 2 해결] 균등 분할(avail // N) 대신 짧은 조문이 남긴 여유 분량을 긴 조문에 재배분(water-filling)하고,
    질문에서 가장 먼저 지정된 핵심 조문(index 0)이 마지막까지 최대한 원문 그대로 보존되도록 가중치를 부여합니다.
    """
    n = len(lengths)
    if n == 0:
        return []
    if sum(lengths) <= total_budget:
        return list(lengths)

    quotas = [0] * n
    remaining_budget = max(0, int(total_budget))
    active = set(range(n))
    # 첫 번째 핵심 본칙 조문(index 0)에 가중치 2.5를 부여하여 5개 조문 동시 조회 시에도 핵심 조문이 중략되지 않도록 보호
    weights = [2.5 if i == 0 else 1.0 for i in range(n)]

    while active and remaining_budget > 0:
        total_w = sum(weights[i] for i in active)
        shares = {
            i: int(remaining_budget * (weights[i] / total_w))
            for i in active
        }
        shorter = [i for i in active if lengths[i] <= shares[i]]
        if not shorter:
            for i in active:
                quotas[i] = max(1200, shares[i])
            # 반올림 오차 보정
            diff = remaining_budget - sum(quotas[i] for i in active)
            first_act = min(active)
            quotas[first_act] = max(1200, quotas[first_act] + diff)
            break
        for i in shorter:
            quotas[i] = lengths[i]
            remaining_budget -= lengths[i]
            active.remove(i)

    return quotas


def compress_legal_text(raw_text: str, query_filter: str = "") -> str:
    if not raw_text:
        return ""

    # [문제 1 해결] 날짜 태그를 지우기 전 원문(raw_text)에서 본칙 조문별 모든 <개정/신설/전문개정 YYYY.M.D.> 날짜(2024년 이전 포함)를 먼저 추출 가능하도록 보존
    def _keep_recent_rev_tag(match: re.Match) -> str:
        full_tag = match.group(0)
        years = re.findall(r"(?:19|20)\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.?", full_tag)
        if years:
            kind = match.group(1)
            return f" <최근{kind}: {', '.join(years[-4:])}>"
        return ""

    cleaned = re.sub(r"<(개정|신설|타법개정|일부개정|전문개정)[^>]*>", _keep_recent_rev_tag, raw_text)
    cleaned = re.sub(r"\[(전문개정|본조신설|제목개정|제\d+조에서 이동)[^\]]*\]", _keep_recent_rev_tag, cleaned)

    mult = 3 if _is_unleashed() else 1
    wants_add = "부칙" in (query_filter or "")
    qf_without_buchik_arts = re.sub(r"부칙\s*제\s*\d+\s*조(?:\s*의\s*\d+)?", "", query_filter or "")
    main_art_matches = re.findall(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?", qf_without_buchik_arts)
    all_art_matches = re.findall(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?", query_filter or "")
    art_matches = main_art_matches if main_art_matches else all_art_matches
    base_limit = 20000 if (all_art_matches or wants_add) else 5000
    limit = base_limit * mult

    header, main_blocks, raw_addenda_blocks = _split_main_and_addenda_blocks(cleaned)
    _, raw_main_blocks_uncleaned, _ = _split_main_and_addenda_blocks(raw_text)

    if all_art_matches or wants_add:
        target_prefixes = list(dict.fromkeys(
            f"제{m[0]}조" + (f"의{m[1]}" if m[1] else "")
            for m in art_matches
        ))
        # '부칙'만 단독 조회한 경우, 같은 질문(trace)에서 이미 조회한 해당 법령의 본칙 조문번호들을 자동으로 target_prefixes에 보강
        if not main_art_matches and wants_add:
            tr_cur = _TOOL_TRACE.get()
            if isinstance(tr_cur, dict):
                m_hdr = re.search(r"📘\s*\[([^\]|\(]+)", header)
                cur_law_norm = re.sub(r"\s+", "", m_hdr.group(1)) if m_hdr else ""
                for (t_law, t_jo, t_gaji) in (tr_cur.get("articles") or set()):
                    if not cur_law_norm or re.sub(r"\s+", "", str(t_law)) == cur_law_norm:
                        p_str = f"제{t_jo}조" + (f"의{t_gaji}" if t_gaji else "")
                        if p_str not in target_prefixes:
                            target_prefixes.append(p_str)

        exact_articles = []
        raw_exact_articles = []
        other_mentions = []

        exact_by_tp: dict[str, list[str]] = {tp: [] for tp in target_prefixes}
        raw_exact_by_tp: dict[str, list[str]] = {tp: [] for tp in target_prefixes}
        for idx_b, blk_s in enumerate(main_blocks):
            blk_clean = blk_s.replace(" ", "")
            matched_tp = None
            for tp in target_prefixes:
                if (
                    blk_clean.startswith(tp + "(") or blk_clean.startswith(tp + " ") or blk_clean == tp
                    or re.match(rf"^{re.escape(tp)}(?![0-9의])", blk_clean)
                ):
                    matched_tp = tp
                    break
            if matched_tp is not None:
                exact_by_tp[matched_tp].append(blk_s)
                if idx_b < len(raw_main_blocks_uncleaned):
                    raw_exact_by_tp[matched_tp].append(raw_main_blocks_uncleaned[idx_b])
            elif target_prefixes and any(re.search(rf"{re.escape(tp)}(?![0-9의])", blk_clean) for tp in target_prefixes):
                other_mentions.append(blk_s)

        for tp in target_prefixes:
            exact_articles.extend(exact_by_tp.get(tp) or [])
            raw_exact_articles.extend(raw_exact_by_tp.get(tp) or [])

        # [본칙 기반 부칙 범위 확정]
        # 1) 날짜 삭제 전 원문(raw_exact_articles)과 정제 본문(exact_articles)에서 모든 개정·신설일(2024년 이전 포함) 수집
        # 2) 타법 인용(「근로기준법」 제2조 등)을 제거한 뒤 같은 법/모법 준용 조문번호만 추출
        related_prefixes = list(target_prefixes)
        main_rev_dates: set[str] = set()
        for ea_txt in (raw_exact_articles + exact_articles):
            for m_dt in re.findall(r"((?:19|20)\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})", ea_txt):
                main_rev_dates.add(f"{int(m_dt[0]):04d}{int(m_dt[1]):02d}{int(m_dt[2]):02d}")
            ea_no_other_law = re.sub(
                r"[「『][^」』]+[」』](?:\s*시행령|\s*시행규칙)?(?:\s*제\s*\d+\s*조(?:\s*의\s*\d+)?(?:\s*제\s*\d+\s*항)?(?:\s*제\s*\d+\s*호)?)+",
                "",
                ea_txt,
            )
            for m_rel in re.findall(r"(?:법\s*|이\s*영\s*|같은\s*법\s*|같은\s*영\s*|제\d+항에\s*따른\s*|에\s*관하여는\s*)?제\s*(\d+)\s*조(?:\s*의\s*(\d+))?", ea_no_other_law):
                rp = f"제{m_rel[0]}조" + (f"의{m_rel[1]}" if m_rel[1] else "")
                if rp not in related_prefixes:
                    related_prefixes.append(rp)

        eff_qf_for_slim = " ".join(related_prefixes) if related_prefixes else (query_filter or "")

        addenda_matched_strict = []
        addenda_fallback = []
        addenda_all = []
        for blk_s, _ in raw_addenda_blocks:
            blk_lines = blk_s.splitlines()
            blk_hdr = blk_lines[0].strip() if blk_lines else "부칙"
            blk_body_raw = "\n".join(blk_lines[1:]).strip() if len(blk_lines) > 1 else ""
            is_pre_tagged_related = "[본칙관련]" in blk_hdr

            # [문제 3 해결] 부칙 본문에서 타법개정 조문('제n조(다른 법령의 개정)' 또는 '일부를 다음과 같이 개정한다')을 먼저 제거
            non_tabeop_body = _strip_tabeop_articles_from_addendum_body(blk_body_raw)
            if not non_tabeop_body.strip():
                continue

            clean_blk_for_slim = blk_hdr + "\n" + non_tabeop_body
            slim_blk = law_api._slim_large_addendum_block(clean_blk_for_slim, eff_qf_for_slim) if hasattr(law_api, "_slim_large_addendum_block") else clean_blk_for_slim
            addenda_all.append(slim_blk)

            # 부칙 자체의 조문 제목('제1조(시행일)', '제2조(경과조치)' 등)을 제거한 순수 본문에서만 본칙 조문번호 경계 매칭
            blk_body_without_own_jo = re.sub(r"(?m)^\s*제\s*\d+\s*조(?:\s*의\s*\d+)?\s*\([^)]*\)", "", non_tabeop_body)
            blk_body_clean = blk_body_without_own_jo.replace(" ", "")
            non_tabeop_clean = non_tabeop_body.replace(" ", "")

            has_exact_prefix = bool(
                related_prefixes and any(
                    re.search(rf"{re.escape(tp)}(?![0-9의])", blk_body_clean)
                    for tp in related_prefixes
                )
            )
            m_anc = re.search(r"부칙[^\n]*?((?:19|20)\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})", blk_hdr)
            anc_ymd = f"{int(m_anc.group(1)):04d}{int(m_anc.group(2)):02d}{int(m_anc.group(3)):02d}" if m_anc else ""
            has_rev_date_match = bool(anc_ymd and anc_ymd in main_rev_dates)

            if is_pre_tagged_related or has_exact_prefix or has_rev_date_match:
                if "[본칙관련]" not in slim_blk.splitlines()[0]:
                    s_lines = slim_blk.splitlines()
                    slim_blk = s_lines[0] + " [본칙관련]\n" + "\n".join(s_lines[1:])
                addenda_matched_strict.append(slim_blk)
            elif not related_prefixes and any(kw in non_tabeop_clean for kw in ("적용례", "경과조치")):
                addenda_fallback.append(slim_blk)

        addenda_matches = addenda_matched_strict if addenda_matched_strict else addenda_fallback

        if wants_add and not exact_articles and addenda_all:
            picked_add = addenda_matches if addenda_matches else addenda_all[:5 * mult]
            cleaned = header + "\n\n📌 [법령 부칙 (본칙 한정 시행일·적용례·경과조치)]\n\n" + "\n\n".join(picked_add)
        elif exact_articles:
            add_section = ""
            if addenda_matches:
                # 본칙(80~85% 이상 보장)이 절대 소외되지 않도록 부칙 섹션은 최대 2,800 * mult 이내로 제한
                add_Cap = 2800 * mult if wants_add else 2400 * mult
                max_add_cnt = max(8, len(addenda_matched_strict))
                add_txt = "\n\n".join(addenda_matches[:max_add_cnt])[:add_Cap]
                add_section = "\n\n📌 [관련 최근 개정 부칙(본칙 한정 시행일·적용례·경과조치) 발췌]\n" + add_txt
            elif wants_add and addenda_all:
                add_txt = "\n\n".join(addenda_all[:3 * mult])[:2400 * mult]
                add_section = "\n\n📌 [최근 개정 부칙(시행일·적용례·경과조치)]\n" + add_txt

            # [문제 2 해결] 줄바꿈 구분자("\n\n")와 부칙(add_section) 길이를 정확히 차감한 뒤
            # Water-filling(남는 분량 재배분 + 1순위 핵심 조문 가중치 보호)으로 본칙 예산을 배분하여
            # 짧은 조문이 남긴 여백을 버리지 않고 limit의 95~99%를 활용하면서 하단 부칙 절삭을 0건으로 방지
            cleaned_arts = [re.sub(r"[ \t]+", " ", ea).strip() for ea in exact_articles]
            sep_len = 2 * len(cleaned_arts)
            avail_for_articles = max(4000, limit - len(header) - len(add_section) - sep_len - 16)
            art_lengths = [len(ea) for ea in cleaned_arts]
            if sum(art_lengths) > avail_for_articles:
                quotas = _waterfill_allocate_quotas(art_lengths, avail_for_articles)
                balanced_articles = []
                for ea, q_lim in zip(cleaned_arts, quotas):
                    if len(ea) > q_lim:
                        notice_str = f"\n...[※ 중략 (원문 {len(ea):,}자 중 앞·뒤 핵심 항 표시)]...\n"
                        body_budget = max(400, q_lim - len(notice_str))
                        head_q = int(body_budget * 0.68)
                        tail_q = body_budget - head_q
                        balanced_articles.append(ea[:head_q] + notice_str + ea[-tail_q:])
                    else:
                        balanced_articles.append(ea)
                cleaned = header + "\n\n" + "\n\n".join(balanced_articles) + add_section
            else:
                cleaned = header + "\n\n" + "\n\n".join(cleaned_arts) + add_section
        elif other_mentions:
            cleaned = header + "\n\n" + "\n\n".join(other_mentions[:3 * mult])
    elif query_filter and query_filter.strip():
        kw_clean = query_filter.strip().replace(" ", "")
        all_blks = list(main_blocks) + [b_s for b_s, _ in raw_addenda_blocks]
        matched_blks = [b.strip() for b in all_blks if kw_clean in b.replace(" ", "")]
        if matched_blks:
            cleaned = header + "\n\n" + "\n\n".join(matched_blks[:5 * mult])

    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if len(cleaned) > limit:
        return (cleaned[:limit]
                + f"\n\n[※ 원문 {len(cleaned):,}자 중 {limit:,}자까지만 표시됨. 필요한 조문이 더 있으면 "
                  "query_filter에 해당 조문번호를 지정해 다시 조회할 것]")
    return cleaned


# ---------------------------------------------------------
# 1. 모델 설정 (1번 아르곤 직결 방식 + 2026.10 공식 Gemini API 라인업) & 대화방당 2,000원 Pro 차단기
# ---------------------------------------------------------
_DEPRECATED_FLASH_MODELS = {
    "gemini-2.5-flash", "gemini-2.5-flash-preview", "gemini-2.0-flash",
    "gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-1.5-pro",
}

def _model_id(env_key: str, default: str) -> str:
    """Secrets에 과거 구버전 모델명(예: gemini-2.5-flash)이 남아 있어도 404 지연(1~2초)이 발생하지 않도록 최신 기본 모델로 자동 치환합니다."""
    raw = (_get_secret_or_env(env_key) or "").strip()
    if not raw or raw.lower() in _DEPRECATED_FLASH_MODELS:
        return default
    return raw

# ⚡ Flash 고속 모드 라인업 (범준·두리·가진 모두 첫 시도 0초 직결되는 gemini-3.6-flash 1순위 + 3.8-flash 백업)
FLASH_MODEL_ID     = _model_id("GEMINI_FLASH_MODEL", "gemini-3.6-flash")
FLASH_BACKUP_ID    = _model_id("GEMINI_FLASH_BACKUP_MODEL", "gemini-3.8-flash")
FLASH_LITE_ID      = _model_id("GEMINI_FLASH_LITE_MODEL", "gemini-3.5-flash-lite")
FLASH_FALLBACK_ID  = "gemini-2.5-flash"

VERIFIER_MODEL_ID  = _model_id("GEMINI_VERIFIER_MODEL", "gemini-3.6-flash")
# 🧪 3차 의미 검증(🧪 의미 검증 배지) 상시 활성화 (과거 Secrets에 VERIFY_MODE=loose나 SEMANTIC_VERIFY=off가 남아 있어도 강제 작동)
SEMANTIC_VERIFY_ON = (_get_secret_or_env("FORCE_DISABLE_SEMANTIC_VERIFY").lower() not in ("on", "true", "1"))

def _get_flash_candidates() -> list[str]:
    f_main = _model_id("GEMINI_FLASH_MODEL", "gemini-3.6-flash")
    f_back = _model_id("GEMINI_FLASH_BACKUP_MODEL", "gemini-3.8-flash")
    f_lite = _model_id("GEMINI_FLASH_LITE_MODEL", "gemini-3.5-flash-lite")
    return _skip_slow_models(list(dict.fromkeys([f_main, f_back, f_lite, FLASH_FALLBACK_ID])))

def _get_verifier_candidates() -> list[str]:
    v_main = _model_id("GEMINI_VERIFIER_MODEL", "gemini-3.6-flash")
    f_back = _model_id("GEMINI_FLASH_BACKUP_MODEL", "gemini-3.8-flash")
    f_lite = _model_id("GEMINI_FLASH_LITE_MODEL", "gemini-3.5-flash-lite")
    return _skip_slow_models(list(dict.fromkeys([v_main, f_back, f_lite, FLASH_FALLBACK_ID])))

# 👑 Pro 심층 모드: [1번 아르곤 직결 방식] gemini-4-argon (Stable GA) 1순위 기본 활성화!
# (만약 추후 Argon을 잠그고 싶을 때만 Secrets/환경변수에 USE_ARGON_MODEL="off" 설정)
USE_ARGON_MODEL = _get_secret_or_env("USE_ARGON_MODEL").lower() not in ("off", "false", "0")
ARGON_MODEL_ID  = _model_id("GEMINI_ARGON_MODEL", "gemini-4-argon")

PAID_PRO_MODEL_IDS = (
    ([ARGON_MODEL_ID] if USE_ARGON_MODEL else [])
    + [
        _model_id("GEMINI_PAID_PRO_CUSTOMTOOLS_MODEL", "gemini-3.1-pro-preview-customtools"),  # 2순위: 도구 호출 특화 Pro
        _model_id("GEMINI_PAID_PRO_MODEL", "gemini-3.1-pro-preview"),                          # 3순위: 표준 3.1 Pro
        "gemini-2.5-pro",                                                                      # 4순위: 안정형 2.5 Pro 백업
    ]
)

# 504(서버 시간 초과)·응답 지연이 난 모델은 일정 시간 건너뛰어, 질문마다 같은 모델에서 수십 초씩 허비하지 않게 합니다.
_SLOW_MODEL_UNTIL: dict[str, float] = {}
_SLOW_MODEL_LOCK = threading.RLock()
_SLOW_MODEL_TTL_SEC = 900

def _is_slow_error(e: Exception) -> bool:
    s = str(e)
    return bool(re.search(r"\b504\b|DEADLINE_EXCEEDED|timed? ?out|ReadTimeout", s, flags=re.IGNORECASE))

def _mark_slow_model(model_id: str) -> None:
    with _SLOW_MODEL_LOCK:
        _SLOW_MODEL_UNTIL[model_id] = time.time() + _SLOW_MODEL_TTL_SEC

def _skip_slow_models(model_ids: list[str]) -> list[str]:
    """최근 응답 지연 모델을 뒤로 미룹니다(모두 지연 상태면 원래 순서 유지)."""
    now = time.time()
    with _SLOW_MODEL_LOCK:
        fast = [m for m in model_ids if _SLOW_MODEL_UNTIL.get(m, 0) <= now]
        slow = [m for m in model_ids if _SLOW_MODEL_UNTIL.get(m, 0) > now]
    return fast + slow if fast else list(model_ids)

def _is_model_not_found(e: Exception) -> bool:
    s = str(e)
    return ("404" in s or "NOT_FOUND" in s) and "model" in s.lower()

LARGE_FILE_AUTO_PRO_CHARS = 15000
LONG_SIMUL_QUERY_CHARS    = 600

SIMUL_KEYWORDS = [
    "시뮬레이션", "시나리오", "비교", "플랜", "부담부증여", "분할증여",
    "일괄증여", "법인전환", "절세전략", "유불리", "실효세율"
]

def select_optimal_model(user_query: str, has_file: bool = False, full_input_len: int = 0) -> tuple[str, str, str]:
    q_clean = (user_query or "").strip()
    budget_exceeded, cur_krw, limit_krw = is_pro_budget_exceeded()

    wants_manual_pro = q_clean.startswith("[프로]")
    wants_file_pro   = has_file and full_input_len >= LARGE_FILE_AUTO_PRO_CHARS

    if (wants_manual_pro or wants_file_pro) and budget_exceeded:
        block_notice = (
            f"> ⛔ **[이 대화방 한도({limit_krw:,.0f}원) 도달 — Pro/Argon 모드 자동 차단됨]** "
            f"현재 대화방의 누적 예상 요금(**{cur_krw:,.0f}원**)이 방 한도({limit_krw:,.0f}원)를 초과하여 "
            "과금 보호를 위해 **Flash 표준 모드**로 자동 전환되었습니다. (새 대화방을 이용하거나 현재 방을 비우시면 Pro/Argon이 다시 활성화됩니다.)\n"
        )
        return "FLASH", "⚡ **[Flash 표준 모드 (대화방 한도 보호 작동)]** 실무 표준 검토", block_notice

    if wants_manual_pro:
        return (
            "PRO",
            "👑 **[Pro 심층 모드 — Argon 직결 (데이터·도구 한도 3배 개방)]** 사용자 지정 초정밀 검토 (`[프로]`)",
            ""
        )

    if wants_file_pro:
        return (
            "PRO",
            f"👑 **[Pro 심층 모드 자동 전환 — Argon 직결 (데이터·도구 한도 3배 개방)]** 대용량 첨부문서({full_input_len:,}자) 초정밀 분석",
            ""
        )

    matched_simul = [kw for kw in SIMUL_KEYWORDS if kw in q_clean]
    if len(q_clean) >= LONG_SIMUL_QUERY_CHARS and len(matched_simul) >= 1 and not budget_exceeded:
        kw_str = ", ".join(matched_simul[:3])
        notice = (
            f"> 💡 **[Pro/Argon 정밀검토 전환 안내]** 초장문({len(q_clean):,}자) 시뮬레이션 질의(감지 키워드: `{kw_str}`)가 확인되었습니다. "
            "현재 답변은 표준 한도(Flash)로 빠르게 작성되었으며, **판례·예규 전문 독해 및 데이터·도구 한도 3배 개방(Argon 직결)**을 통한 "
            "심층 재검토가 필요하시면 좌측 **Pro 토글을 켜거나** 답변 하단의 **`👑 [프로/Argon] 3배 개방 재검토`** 버튼을 눌러주세요.\n"
        )
        return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토", notice

    return "FLASH", "⚡ **[Flash 빠른 검토 모드]** 실무 표준 검토", ""

# ---------------------------------------------------------
# 2. Gemini 도구 정의 (12개 도구 전체 docstring + 복수 법령 병렬 조회 및 1턴 직행 지원)
# ---------------------------------------------------------
def search_law_for_gemini(keyword: str, target: str = "law") -> str:
    """
    국가법령정보센터에서 법령, 대법원 판례, 헌법재판소 결정례, 조세심판원 결정례, 행정규칙, 법령해석례, 지자체 조례, 별표·서식 목록과 일련번호(ID)를 검색합니다.
    - target: 'law'(법령), 'prec'(대법원 판례), 'detc'(헌법재판소 위헌·헌법불합치 결정례), 'decc'(조세심판원 결정례), 'admrul'(훈령·예규·고시·기본통칙), 'expc'(법령해석례), 'ordin'(지자체 조례), 'licbyl'(법령 별표·서식)
    - target='law'일 때 keyword에는 '법령명만' 넣을 것 (예: '소득세법', '소득세법 시행령'). 주제어는 넣지 말 것. (정식 법령명을 아는 경우 get_law_details_for_gemini의 doc_id에 법령명을 바로 넣으면 1턴에 직행 조회됨)
    - target='prec'/'detc'/'decc'/'expc'는 핵심 주제어(예: '업무무관 가지급금')나 사건번호(예: '2005두9415', '2021헌바123')로 검색할 것.
    """
    if _over_limit("search", target):
        print(f"\n[시스템] ⛔ 검색 한도 도달 → 차단: '{keyword}' (대상: {target})")
        return (f"[검색 한도 도달] 이번 질문에서 '{target}' 검색은 더 할 수 없습니다. "
                "지금까지 조회한 원문만으로 답변을 작성하고, 찾지 못한 근거는 '관련 원문을 확인하지 못했다'고 쓰세요.")

    _emit_live_status(f"🔎 1단계: 법제처 DB 목록 탐색 중 ('{keyword}' · {target})...")
    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    cache_key = ("search", today_ymd, keyword.strip(), target)
    cached_pack = _cache_get(cache_key)
    if cached_pack is not None:
        results, used_keyword = cached_pack
        print(f"\n[시스템] ⚡ [메모리 캐시 즉시 히트(0.001초)] 목록 검색: '{keyword}' (대상: {target})")
    else:
        print(f"\n[시스템] 💡 목록 검색 도구 가동: '{keyword}' (대상: {target})")
        try:
            results = law_api.search_law_data(keyword, target)
        except Exception as e:
            print(f"[시스템] ⚠️ 법제처 검색 오류: {e}")
            results = None
        used_keyword = keyword

        if not results and target in ("prec", "decc", "detc", "expc", "admrul"):
            print("[시스템]    ↳ 제목 검색 결과 없음 → 본문 검색으로 재시도")
            try:
                results = law_api.search_law_data(keyword, target, search_mode=2)
            except Exception:
                results = None
            if results:
                used_keyword = keyword + " (본문검색)"

        words = keyword.split()
        while not results and len(words) > 1:
            words = words[:-1]
            used_keyword = " ".join(words)
            print(f"[시스템]    ↳ 결과 없음 → '{used_keyword}'로 자동 재검색")
            try:
                results = law_api.search_law_data(used_keyword, target)
                if not results and target in ("prec", "decc", "detc", "expc", "admrul"):
                    results = law_api.search_law_data(used_keyword, target, search_mode=2)
            except Exception:
                results = None

        if results:
            _cache_set(cache_key, (results, used_keyword))

    if not results:
        return _record("list", f"'{keyword}' (대상: {target}) 검색 결과가 없습니다. 법령은 법령명만, 판례는 핵심 주제어 1~2개로 다시 검색하세요.")

    if isinstance(results, dict):
        results = [results]

    _today_int_s = int(get_kst_today_context()["ymd"])
    if target == "law":
        results = _sort_law_candidates_for_today(results)
        _seen_lnm = set()
        for item in results[:5]:
            lnm = str(item.get("법령명한글", "")).replace(" ", "").strip()
            lid = str(item.get("법령일련번호") or item.get("법령ID") or "").strip()
            if lnm and lid and lnm not in _seen_lnm:
                _seen_lnm.add(lnm)
                _cache_set(("law_name_to_id", today_ymd, lnm), lid)

    top_n = 10 if _is_unleashed() else 5
    summary = ""
    if used_keyword != keyword:
        summary += f"※ '{keyword}' 검색 결과가 없어 '{used_keyword}'(으)로 재검색한 결과입니다.\n"
    summary += f"총 {len(results)}건 검색됨 (상위 {min(len(results), top_n)}건 요약):\n"
    for i, item in enumerate(results[:top_n]):
        if target == "law":
            _enf_s = re.sub(r"\D", "", str(item.get("시행일자") or ""))
            _enf_i = int(_enf_s) if len(_enf_s) == 8 and _enf_s.isdigit() else 0
            _enf_badge = (
                f" 🚨[미시행(미래 시행예정: {item.get('시행일자')}) — 이미 공포되었으나 오늘({get_kst_today_context()['dot_full']}) 기준 아직 시행 전이므로 당해 {get_kst_today_context()['year']}년 귀속에 즉시 적용 금지!]"
                if _enf_i > _today_int_s else
                f" ✅[현행 시행중 — 당해 {get_kst_today_context()['year']}년 귀속 적용 대상]"
            )
            summary += f"{i+1}. [법령] {item.get('법령명한글')} | 공포번호: {item.get('공포번호')} | 공포일: {item.get('공포일자')} | 시행일: {item.get('시행일자')}{_enf_badge} | 구분: {item.get('제개정구분명')} | ID: {item.get('법령일련번호')}\n"
        elif target == "prec":
            summary += f"{i+1}. [판례] 사건명: {item.get('사건명')} | 사건번호: {item.get('사건번호')} | 선고일자: {item.get('선고일자')} | ID: {item.get('판례일련번호')}\n"
        elif target == "detc":
            summary += f"{i+1}. [헌재결정례] 사건명: {item.get('사건명')} | 사건번호: {item.get('사건번호')} | 종국일자: {item.get('종국일자')} | ID: {item.get('헌재결정례일련번호')}\n"
        elif target == "licbyl":
            summary += f"{i+1}. [별표/서식] {item.get('별표명')} | 관련법령: {item.get('관련법령명')} | 구분: {item.get('별표구분')} | ID: {item.get('별표일련번호')}\n"
        elif target == "decc":
            case_no = item.get('사건번호') or item.get('청구번호') or '-'
            dec_id = item.get('특별행정심판재결례일련번호') or item.get('행정심판재결례일련번호') or item.get('id') or '-'
            summary += f"{i+1}. [조세심판/특별행정심판] 사건명: {item.get('사건명')} | 청구(사건)번호: {case_no} | 의결일자: {item.get('의결일자') or item.get('처분일자')} | ID: {dec_id}\n"
        elif target == "admrul":
            summary += f"{i+1}. [행정규칙/예규/고시] {item.get('행정규칙명')} | 소관부처: {item.get('소관부처명')} | 발령번호: {item.get('발령번호')} | 발령일: {item.get('발령일자')} | ID: {item.get('행정규칙일련번호')}\n"
        elif target == "expc":
            summary += f"{i+1}. [법령해석례/질의회신] 안건명: {item.get('안건명')} | 안건번호: {item.get('안건번호')} | 회신기관: {item.get('회신기관명')} | ID: {item.get('법령해석례일련번호')}\n"
        elif target == "ordin":
            summary += f"{i+1}. [지자체 조례/자치법규] {item.get('자치법규명', item.get('법령명한글'))} | 지자체: {item.get('지자체기관명')} | 시행일: {item.get('시행일자')} | ID: {item.get('자치법규일련번호', item.get('법령일련번호'))}\n"
        else:
            summary += f"{i+1}. {item.get('법령명한글', item.get('행정규칙명', '제목 없음'))}\n"

    trace = _TOOL_TRACE.get()
    if trace is not None:
        meta = trace.setdefault("meta_map", {})
        for item in results[:15]:
            if target in ("prec", "decc", "detc"):
                rid = item.get("판례일련번호") or item.get("헌재결정례일련번호") or item.get("특별행정심판재결례일련번호") or item.get("행정심판재결례일련번호")
                rno = item.get("사건번호") or item.get("청구번호")
                if rid and rno:
                    trace["id_map"][str(rid).strip()] = rno.strip()
                    meta[(target, _norm(rno))] = str(rid).strip()
            elif target == "expc":
                rid = item.get("법령해석례일련번호")
                rno = item.get("안건번호")
                if rid and rno:
                    meta[("expc", _norm(rno))] = str(rid).strip()
            elif target == "admrul":
                rid = item.get("행정규칙일련번호")
                rnm = item.get("행정규칙명")
                rno = item.get("발령번호")
                if rid and rnm:
                    meta[("admrul", _norm(rnm))] = str(rid).strip()
                if rid and rno:
                    meta[("admrul", _norm(rno))] = str(rid).strip()
            elif target == "licbyl":
                rid = item.get("별표일련번호")
                rnm = item.get("별표명")
                if rid and rnm:
                    meta[("licbyl", _norm(rnm))] = str(rid).strip()
    return _record("list", summary)

def get_law_details_for_gemini(doc_id: str, target: str = "law", query_filter: str = "") -> str:
    """
    검색된 일련번호(ID) 또는 정식 법령명(예: '조세특례제한법', '조세특례제한법 시행령')으로 조문·부칙·판례·헌재결정례·심판례 원문을 조회합니다.
    - 법령('law') 조회 시 query_filter에 조문번호(예: '제29조의8', '제29조의8, 부칙') 또는 '부칙'(시행일·적용례·경과조치 확인용)을 넣어 호출하세요.
    - target: 'law'(법령·부칙), 'prec'(대법원 판례), 'detc'(헌법재판소 결정례), 'decc'(조세심판원 결정례), 'admrul'(행정규칙·예규), 'expc'(법령해석례), 'ordin'(조례), 'licbyl'(별표·서식)
    - doc_id에 정식 법령명을 바로 넣으면 search_law_for_gemini 없이 1턴에 즉시 원문 및 관련 개정 부칙이 조회됩니다.
    """
    _emit_live_status(f"📖 2단계: 법령·판례 원문 정밀 파싱 중 ('{doc_id}' · {query_filter or target})...")

    # [속도 개선 ②] doc_id에 쉼표(,)로 복수 법령/ID가 들어온 경우 ThreadPoolExecutor로 병렬 XML 프리페치 후 순차 결합
    if "," in str(doc_id or "") and len(str(doc_id).split(",")) <= 4:
        sub_ids = [s.strip() for s in str(doc_id).split(",") if s.strip()]
        if len(sub_ids) > 1:
            if target == "law":
                resolved_pairs = [(sid, _resolve_law_id_if_name(sid)) for sid in sub_ids]
                with ThreadPoolExecutor(max_workers=min(4, len(resolved_pairs))) as ex:
                    for _, rid in resolved_pairs:
                        if rid.isdigit():
                            ex.submit(_fetch_full_law_xml_direct, rid, query_filter)
            combined_parts = [get_law_details_for_gemini(sid, target=target, query_filter=query_filter) for sid in sub_ids]
            return "\n\n====================\n\n".join(combined_parts)

    if target == "law":
        doc_id = _resolve_law_id_if_name(doc_id)

    trace = _TOOL_TRACE.get()
    if trace is not None and target != "law":
        seen = trace.setdefault("seen_docs", set())
        if (target, str(doc_id)) in seen:
            print(f"\n[시스템] ♻️ 이미 조회한 원문 → 재조회 생략: ID '{doc_id}' (대상: {target})")
            return "[이미 조회한 원문] 이 문서는 이번 질문에서 이미 전체 원문을 조회했습니다. 앞의 조회 결과를 그대로 참고하세요."
    if _over_limit("detail", target):
        print(f"\n[시스템] ⛔ 원문 조회 한도 도달 → 차단: ID '{doc_id}' (대상: {target})")
        return (f"[원문 조회 한도 도달] 이번 질문에서 '{target}' 원문 조회는 더 할 수 없습니다. "
                "이미 조회한 원문만으로 답변을 작성하세요.")

    today_ymd = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    clean_id = str(doc_id).strip()
    cache_key = ("detail_raw", today_ymd, clean_id, target, query_filter.strip())

    # 1) 동일 (법령ID, 필터) 조합 캐시 우선 확인, 2) 없으면 구조화 XML 캐시(full_law_parsed)를 통해 0.001초 만에 조문별 부칙 선별
    raw_text = _cache_get(cache_key)
    if raw_text is None and target == "law" and not query_filter.strip():
        raw_text = _cache_get(("full_law_xml", today_ymd, clean_id))

    if raw_text is not None:
        print(f"\n[시스템] ⚡ [메모리 캐시 즉시 히트(0.001초)] 원문 조회: ID '{clean_id}' (대상: {target}, 필터: '{query_filter}')")
    else:
        has_parsed_cache = (target == "law" and clean_id.isdigit() and _cache_get(("full_law_parsed", today_ymd, clean_id)) is not None)
        if has_parsed_cache:
            print(f"\n[시스템] ⚡ [구조화 XML 캐시 즉시 조합(0.001초)] 원문 조회: ID '{clean_id}' (대상: {target}, 필터: '{query_filter}')")
        else:
            print(f"\n[시스템] 📖 원문 정밀 조회 가동: ID '{clean_id}' (대상: {target}, 필터: '{query_filter}')")
        if target == "law" and clean_id.isdigit():
            raw_text = _fetch_full_law_xml_direct(clean_id, query_filter)
            if not raw_text:
                try:
                    raw_text = law_api.get_law_content(clean_id, target, query_filter)
                except Exception as e:
                    raw_text = f"❌ 원문 조회 오류: {e}"
        else:
            try:
                raw_text = law_api.get_law_content(clean_id, target, query_filter)
            except Exception as e:
                raw_text = f"❌ 원문 조회 오류: {e}"

        if raw_text and not str(raw_text).startswith("❌"):
            _cache_set(cache_key, raw_text)

    result = compress_legal_text(raw_text, query_filter)
    body_ok = bool(result and not result.startswith("❌") and len(result) >= 80)

    if trace is not None and target != "law" and body_ok:
        trace.setdefault("seen_docs", set()).add((target, clean_id))

    preview = result[:150].replace("\n", " ")
    print(f"[시스템]    ↳ 원문 {len(raw_text or ''):,}자 → 전달 {len(result):,}자 | 앞부분: {preview}")
    if target == "law" and body_ok:
        _record_law_articles(result)
        result = _annotate_law_effective_dates_vs_today(result)
    if trace is not None and target in ("prec", "decc", "detc"):
        rno = trace["id_map"].get(clean_id)
        if rno and body_ok and _norm(rno) not in _norm(result):
            result = f"[사건(청구)번호: {rno}]\n" + result
        if not body_ok:
            print(f"[시스템]    ↳ ⚠️ 원문이 비었거나 오류: {result[:120]}")
    return _record("detail", result)

def search_historical_law_for_gemini(law_name: str, target_date: str, query_filter: str = "") -> str:
    """
    과거 귀속연도(예: '2022', '2023-06-30', '20211231') 세무조사·경정청구·기한후신고 검토 시
    국가법령정보센터 연혁·시행일법령(target='eflaw') DB에서 해당 과거 시점에 실제로 시행 중이던 구법 조문 원문을 조회합니다.
    - law_name: 정식 법령명만 입력 (예: '조세특례제한법', '법인세법 시행령')
    - target_date: 과거 기준연도 또는 일자 (예: '2022', '20221231')
    - query_filter: 조회할 조문번호 (예: '제29조의7', '제10조')
    """
    if _over_limit("detail", "eflaw"):
        return "[구법 조회 한도 도달] 이번 질문에서 추가 연혁법령 조회는 더 할 수 없습니다."

    _emit_live_status(f"🕰️ 2단계: 구법(연혁법령) 타임머신 조회 중 ('{law_name}' · {target_date})...")
    digits = re.sub(r"[^0-9]", "", str(target_date or ""))
    if len(digits) == 4:
        ymd_int = int(digits + "1231")
    elif len(digits) == 6:
        ymd_int = int(digits + "28")
    elif len(digits) >= 8:
        ymd_int = int(digits[:8])
    else:
        ymd_int = int(datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d"))

    oc = get_law_oc_auto()
    if not oc:
        return "❌ 법제처 API 인증키(OC)를 확인할 수 없어 연혁법령 조회가 불가능합니다."

    cache_key = ("hist_law", law_name.strip(), ymd_int, query_filter.strip())
    cached_res = _cache_get(cache_key)
    if cached_res is not None:
        print(f"\n[시스템] ⚡ [메모리 캐시 히트] 구법 타임머신: '{law_name}' (기준일: {ymd_int}, 필터: '{query_filter}')")
        _record_law_articles(cached_res)
        return _record("detail", cached_res)

    print(f"\n[시스템] 🕰️ 구법(연혁법령) 타임머신 가동: '{law_name}' (과거 기준일: {ymd_int}, 조문필터: '{query_filter}')")
    encoded_q = urllib.parse.quote(law_name.strip())

    try:
        candidates = []
        target_clean = law_name.replace(" ", "").strip()
        for s_target in ("eflaw", "law"):
            search_url = f"http://www.law.go.kr/DRF/lawSearch.do?OC={oc}&target={s_target}&type=XML&query={encoded_q}&display=50"
            xml_data = _http_get_bytes_fast(search_url, timeout=15)
            root = ET.fromstring(xml_data)
            for law_node in root.findall(".//law"):
                lname = (law_node.findtext("법령명한글") or "").strip()
                if lname.replace(" ", "") != target_clean:
                    continue
                ef_yd = re.sub(r"[^0-9]", "", law_node.findtext("시행일자") or "")
                anc_yd = re.sub(r"[^0-9]", "", law_node.findtext("공포일자") or "")
                mst = (law_node.findtext("법령일련번호") or law_node.findtext("MST") or "").strip()
                anc_no = (law_node.findtext("공포번호") or "").strip()
                rev_nm = (law_node.findtext("제개정구분명") or "").strip()
                if ef_yd.isdigit() and int(ef_yd) <= ymd_int and mst:
                    candidates.append({
                        "lname": lname,
                        "ef_yd": int(ef_yd),
                        "anc_yd": int(anc_yd) if anc_yd.isdigit() else 0,
                        "mst": mst,
                        "anc_no": anc_no,
                        "rev_nm": rev_nm
                    })
            if candidates:
                break

        if not candidates:
            return f"'{law_name}'의 {ymd_int} 기준 연혁법령 목록을 찾지 못했습니다. 일반 get_law_details_for_gemini 도구로 현행 조문 및 부칙을 확인하세요."

        candidates.sort(key=lambda x: (x["ef_yd"], x["anc_yd"]), reverse=True)
        chosen = candidates[0]
        mst_id = chosen["mst"]
        ef_yd_str = str(chosen["ef_yd"])

        full_hist_key = ("hist_law_full", mst_id, ef_yd_str)
        full_raw = _cache_get(full_hist_key)

        if not full_raw:
            detail_urls = [
                f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=eflaw&MST={mst_id}&efYd={ef_yd_str}&type=XML",
                f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&MST={mst_id}&type=XML",
                f"http://www.law.go.kr/DRF/lawService.do?OC={oc}&target=law&ID={mst_id}&type=XML",
            ]
            article_blocks = []
            for d_url in detail_urls:
                try:
                    detail_xml = _http_get_bytes_fast(d_url, timeout=20)
                    d_root = ET.fromstring(detail_xml)
                    for unit in d_root.findall(".//조문단위"):
                        jo_content = (unit.findtext("조문내용") or "").strip()
                        if not jo_content:
                            continue
                        lines = [jo_content]
                        for hang in unit.findall(".//항"):
                            h_txt = (hang.findtext("항내용") or "").strip()
                            if h_txt:
                                lines.append(h_txt)
                            for ho in hang.findall(".//호"):
                                ho_txt = (ho.findtext("호내용") or "").strip()
                                if ho_txt:
                                    lines.append("  " + ho_txt)
                                for mok in ho.findall(".//목"):
                                    mok_txt = (mok.findtext("목내용") or "").strip()
                                    if mok_txt:
                                        lines.append("    " + mok_txt)
                        article_blocks.append("\n".join(lines))
                    for a_unit in d_root.findall(".//부칙단위"):
                        anc_dt = re.sub(r"\D", "", a_unit.findtext("부칙공포일자") or "")
                        anc_no = (a_unit.findtext("부칙공포번호") or "").strip()
                        a_body = (a_unit.findtext("부칙내용") or "").strip()
                        if a_body:
                            dt_fmt = f"{anc_dt[:4]}.{anc_dt[4:6]}.{anc_dt[6:]}." if len(anc_dt) == 8 else anc_dt
                            no_fmt = f"제{anc_no}호, " if anc_no else ""
                            article_blocks.append(f"부칙 <{no_fmt}{dt_fmt}>\n{a_body}")
                    if article_blocks:
                        break
                except Exception:
                    continue

            if not article_blocks:
                fallback_txt = law_api.get_law_content(mst_id, "law", query_filter)
                return _record("detail", compress_legal_text(fallback_txt, query_filter))

            header_str = (
                f"📘 [{chosen['lname']} | 🕰️ 구법(연혁법령) 타임머신 조회 (기준일: {ymd_int}) | "
                f"시행일: {chosen['ef_yd']} | 공포번호: 제{chosen['anc_no']}호 ({chosen['rev_nm']}) | MST: {mst_id}]"
            )
            full_raw = header_str + "\n\n" + "\n\n".join(article_blocks)
            _cache_set(full_hist_key, full_raw)

        compressed = compress_legal_text(full_raw, query_filter)
        _cache_set(cache_key, compressed)
        _record_law_articles(compressed)
        return _record("detail", compressed)
    except Exception as e:
        return f"❌ 구법(연혁법령) 조회 중 오류 발생 ({law_name}, 기준일 {ymd_int}): {e}"

def search_exchange_rate_for_gemini(start_date: str, end_date: str, currency: str = "USD") -> str:
    """한국은행(ECOS) 공식 환율을 조회합니다. start_date/end_date는 'YYYYMMDD', currency는 'USD','JPY','EUR','CNY' 등."""
    _emit_live_status(f"💱 1단계: 한국은행(ECOS) 공식 환율 조회 중 ({currency})...")
    print(f"\n[시스템] 💱 한국은행 환율 조회 도구 가동: {currency} ({start_date}~{end_date})")
    try:
        return _record("detail", law_api.get_bok_exchange_rate(start_date, end_date, currency))
    except Exception as e:
        return f"환율 조회 오류: {e}"

def search_base_rate_for_gemini(start_date: str, end_date: str) -> str:
    """한국은행 기준금리를 조회합니다. start_date/end_date는 'YYYYMMDD' 형식입니다."""
    _emit_live_status("📈 1단계: 한국은행(ECOS) 기준금리 조회 중...")
    print(f"\n[시스템] 📈 한국은행 기준금리 조회 도구 가동: ({start_date}~{end_date})")
    try:
        return _record("detail", law_api.get_bok_base_rate(start_date, end_date))
    except Exception as e:
        return f"기준금리 조회 오류: {e}"

def search_industry_code_for_gemini(keyword: str) -> str:
    """국세청 업종코드(6자리) 및 기준·단순경비율을 검색합니다. keyword에 업종명이나 6자리 코드를 넣으세요."""
    _emit_live_status(f"🏢 1단계: 국세청 업종코드·경비율 DB 조회 중 ('{keyword}')...")
    print(f"\n[시스템] 🏢 국세청 업종코드 검색 도구 가동: '{keyword}'")
    try:
        return _record("detail", law_api.search_industry_code(keyword))
    except Exception as e:
        return f"업종코드 조회 오류: {e}"

def search_dart_corp_for_gemini(corp_name: str, bsns_year: str = "") -> str:
    """DART 전자공시에서 기업개황·요약재무제표·최대주주 지분·배당 정보를 조회합니다. bsns_year 미지정 시 당해·직전 사업연도를 자동 순회합니다."""
    _eff_yr = (bsns_year or "").strip() or f"{get_kst_today_context()['year']}~{get_kst_today_context()['prev_year']}"
    _emit_live_status(f"📊 1단계: DART 전자공시 재무·지분 조회 중 ('{corp_name}')...")
    print(f"\n[시스템] 📊 DART 전자공시 통합 조회 가동: '{corp_name}' ({_eff_yr}년)")
    cap = 16000 if _is_unleashed() else 10000
    try:
        return _record("detail", law_api.get_dart_corp_info(corp_name, (bsns_year or "").strip())[:cap])
    except Exception as e:
        return f"DART 공시 조회 오류: {e}"

def check_nts_biz_status_for_gemini(biz_numbers: str) -> str:
    """국세청 사업자등록 상태(계속/휴·폐업) 및 과세유형(일반/간이/면세)을 실시간 조회합니다."""
    _emit_live_status("🔎 1단계: 국세청 사업자등록 상태·과세유형 실시간 조회 중...")
    print(f"\n[시스템] 🔎 국세청 사업자등록 상태·과세유형 실시간 조회 가동: '{biz_numbers}'")
    try:
        return _record("detail", law_api.get_nts_biz_status(biz_numbers))
    except Exception as e:
        return f"사업자 상태 조회 오류: {e}"

def verify_nts_biz_info_for_gemini(b_no: str, start_dt: str, p_nm: str, b_nm: str = "") -> str:
    """국세청 사업자등록 진위확인을 수행합니다. b_no(10자리), start_dt(개업일 YYYYMMDD), p_nm(대표자명)."""
    _emit_live_status("🛡️ 1단계: 국세청 사업자등록 진위확인 중...")
    print(f"\n[시스템] 🛡️ 국세청 사업자등록 진위확인 가동: {b_no} | {start_dt} | {p_nm}")
    try:
        if hasattr(law_api, "verify_nts_biz_info"):
            return _record("detail", law_api.verify_nts_biz_info(b_no, start_dt, p_nm, b_nm))
        return "현재 law_api.py에 진위확인 함수가 없습니다."
    except Exception as e:
        return f"사업자 진위확인 오류: {e}"

def search_real_estate_trade_for_gemini(property_type: str, region: str, deal_ymd: str, filter_keyword: str = "") -> str:
    """국토부 부동산 실거래가를 조회합니다. property_type('apt','offi','commercial','land'), region(지역명), deal_ymd('YYYYMM')."""
    _emit_live_status(f"🏘️ 1단계: 국토교통부 부동산 실거래가 조회 중 ({region})...")
    print(f"\n[시스템] 🏘️ 국토교통부 부동산 실거래가 조회 가동: 유형={property_type} | 지역={region} | 연월={deal_ymd} | 필터='{filter_keyword}'")
    try:
        if hasattr(law_api, "get_molit_real_estate_trade"):
            return _record("detail", law_api.get_molit_real_estate_trade(property_type, region, deal_ymd, filter_keyword))
        return "현재 law_api.py에 부동산 실거래가 조회 함수가 없습니다."
    except Exception as e:
        return f"실거래가 조회 오류: {e}"

def search_official_land_price_for_gemini(address: str, stdr_year: str = "") -> str:
    """브이월드 API로 부동산 개별공시지가 및 공동주택 공시가격을 조회합니다."""
    _emit_live_status(f"🏛️ 1단계: 브이월드 공시지가·공동주택공시가격 조회 중 ({address})...")
    print(f"\n[시스템] 🏛️ 브이월드 공시지가·공동주택공시가격 조회 가동: 주소='{address}' | 기준연도='{stdr_year}'")
    try:
        if hasattr(law_api, "get_vworld_official_price"):
            return _record("detail", law_api.get_vworld_official_price(address, stdr_year))
        return "현재 law_api.py에 공시지가 조회 함수가 없습니다."
    except Exception as e:
        return f"공시지가 조회 오류: {e}"

def search_real_estate_rent_for_gemini(property_type: str, region: str, deal_ymd: str, filter_keyword: str = "") -> str:
    """국토부 부동산 전월세(보증금·월세) 실거래가를 조회합니다. property_type('apt','offi','villa','house'), region(시군구명), deal_ymd('YYYYMM')."""
    _emit_live_status(f"🏠 1단계: 국토교통부 전월세 실거래가 조회 중 ({region})...")
    print(f"\n[시스템] 🏠 국토교통부 전월세 실거래가 조회 가동: 유형={property_type} | 지역={region} | 연월={deal_ymd} | 필터='{filter_keyword}'")
    try:
        if hasattr(law_api, "get_molit_real_estate_rent"):
            return _record("detail", law_api.get_molit_real_estate_rent(property_type, region, deal_ymd, filter_keyword))
        return "현재 law_api.py에 전월세 실거래가 조회 함수가 없습니다."
    except Exception as e:
        return f"전월세 실거래가 조회 오류: {e}"

def search_building_ledger_for_gemini(address: str) -> str:
    """국토부 건축물대장(표제부·층별개요)을 조회하여 주용도, 연면적, 층별 주택/상가 면적 비율(겸용주택 판정), 위반건축물 여부를 확인합니다."""
    _emit_live_status(f"🏢 1단계: 국토교통부 건축물대장 표제부·층별개요 조회 중 ({address})...")
    print(f"\n[시스템] 🏢 국토교통부 건축물대장 조회 가동: 주소='{address}'")
    try:
        if hasattr(law_api, "get_building_ledger_info"):
            return _record("detail", law_api.get_building_ledger_info(address))
        return "현재 law_api.py에 건축물대장 조회 함수가 없습니다."
    except Exception as e:
        return f"건축물대장 조회 오류: {e}"

def search_comwel_workplace_for_gemini(biz_no: str, insurance_type: str = "all") -> str:
    """근로복지공단 고용·산재보험 가입 사업장 현황(상시인원·피보험자수·성립일·업종)을 사업자번호(10자리)로 조회합니다."""
    _emit_live_status(f"👷 1단계: 근로복지공단 고용·산재보험 가입 현황 조회 중 ({biz_no})...")
    print(f"\n[시스템] 👷 근로복지공단 고용·산재보험 조회 가동: 사업자번호='{biz_no}' | 구분='{insurance_type}'")
    try:
        if hasattr(law_api, "get_comwel_workplace_info"):
            return _record("detail", law_api.get_comwel_workplace_info(biz_no, insurance_type))
        return "현재 law_api.py에 근로복지공단 조회 함수가 없습니다."
    except Exception as e:
        return f"고용·산재보험 조회 오류: {e}"

def search_nps_workplace_for_gemini(corp_name: str, biz_no_prefix6: str = "", region_keyword: str = "", target_year: str = "") -> str:
    """4대보험(국민연금·건강보험·노인장기요양보험·고용보험·산재보험) 전체의 월별 고지보험료, 연간 보험료 고지총액 합계, 사업주(회사)/근로자 부담분, 추정 과세보수총액 및 월별 가입자수(신규취득/상실 인원)를 실시간 통합 조회합니다. biz_no_prefix6에 10자리 사업자등록번호(또는 앞 6자리)를 입력하면 근로복지공단 업종·상시인원을 자동 연계하여 산재·고용보험 요율까지 정밀 산출합니다. target_year에 '2026', '2025' 등 연도를 지정할 수 있습니다."""
    _emit_live_status(f"🏦 1단계: 4대보험(연금·건보·장기요양·고용·산재) 월별·연간 고지보험료 통합 조회 중 ({corp_name})...")
    print(f"\n[시스템] 🏦 4대보험 월별/연간 고지액 통합 조회 가동: 상호='{corp_name}' | 사업자번호='{biz_no_prefix6}' | 지역='{region_keyword}' | 연도='{target_year}'")
    try:
        if hasattr(law_api, "get_nps_workplace_info"):
            return _record("detail", law_api.get_nps_workplace_info(corp_name, biz_no_prefix6, region_keyword, target_year))
        return "현재 law_api.py에 국민연금 사업장 조회 함수가 없습니다."
    except Exception as e:
        return f"국민연금 사업장 조회 오류: {e}"

def search_customs_exchange_rate_for_gemini(aply_bgn_dt: str, imex_type: str = "2", currency: str = "") -> str:
    """관세청 수출입 과세환율(관세법 제18조 주간 고시환율)을 조회합니다. aply_bgn_dt('YYYYMMDD'), imex_type('1'=수출, '2'=수입, 'all'=모두), currency('USD' 등)."""
    _emit_live_status(f"🚢 1단계: 관세청 수출입 과세환율 조회 중 ({aply_bgn_dt} · {currency or '전체'})...")
    print(f"\n[시스템] 🚢 관세청 수출입 과세환율 조회 가동: 일자={aply_bgn_dt} | 구분={imex_type} | 통화={currency}")
    try:
        if hasattr(law_api, "get_customs_exchange_rate"):
            return _record("detail", law_api.get_customs_exchange_rate(aply_bgn_dt, imex_type, currency))
        return "현재 law_api.py에 관세청 과세환율 조회 함수가 없습니다."
    except Exception as e:
        return f"관세청 과세환율 조회 오류: {e}"

def search_bizinfo_support_for_gemini(category: str = "", hashtags: str = "", keyword: str = "") -> str:
    """중소벤처기업부 기업마당(bizinfo.go.kr)에서 최신 정부지원사업·정책자금·R&D·고용지원금·창업·수출·바우처 공고를 실시간 조회합니다. category('금융'/'기술'/'인력'/'수출'/'내수'/'창업'/'경영'/'기타' 또는 공란), hashtags(지역명 '서울'/'경기'/'부산' 등 해시태그), keyword(세부 검색어)."""
    _emit_live_status(f"🏛️ 1단계: 기업마당(Bizinfo) 정부지원사업 공고 실시간 조회 중 (분야:{category or '전체'} · 지역/태그:{hashtags or '전체'} · 키워드:{keyword or '전체'})...")
    print(f"\n[시스템] 🏛️ 기업마당 정부지원사업 조회 가동: 분야='{category}' | 해시태그='{hashtags}' | 키워드='{keyword}'")
    try:
        if hasattr(law_api, "get_bizinfo_support_projects"):
            return _record("detail", law_api.get_bizinfo_support_projects(category=category, hashtags=hashtags, keyword=keyword))
        return "현재 law_api.py에 기업마당 지원사업 조회 함수가 없습니다."
    except Exception as e:
        return f"기업마당 지원사업 조회 오류: {e}"

# ---------------------------------------------------------
# 🛡️ 정밀 수리 계산기: AST 화이트리스트 보안 샌드박스 & 천 단위 쉼표 지능형 정제
#    (min(100,200) 공백 없는 인자 쉼표 보호 + 음수 거듭제곱 1.05**-3 허용 + pow(a,b) 지수 한도 검증 완벽 통합)
# ---------------------------------------------------------
_ALLOWED_CALC_FUNCS = {"abs", "round", "min", "max", "sum", "pow", "int", "float"}
_ALLOWED_MATH_ATTRS = {
    "floor", "ceil", "sqrt", "trunc", "log", "log10", "exp", "pow", "fabs", "isfinite", "pi", "e"
}
_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.keyword,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.Tuple,
    ast.List,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)

def _check_safe_pow_exponent(exp_node: ast.AST) -> None:
    """
    `10 ** 10000`이나 `pow(10, 10000)` 같은 과도한 거듭제곱을 차단하되,
    세무·회계 현재가치 할인 계산에 필수적인 음수 지수(`(1 + 0.05) ** -3`)는 안전하게 허용합니다.
    """
    if isinstance(exp_node, ast.Constant) and isinstance(exp_node.value, (int, float)) and not isinstance(exp_node.value, bool):
        if abs(exp_node.value) > 1000:
            raise ValueError("거듭제곱 지수가 너무 큽니다(최대 1000).")
        return
    if (
        isinstance(exp_node, ast.UnaryOp)
        and isinstance(exp_node.op, (ast.UAdd, ast.USub))
        and isinstance(exp_node.operand, ast.Constant)
        and isinstance(exp_node.operand.value, (int, float))
        and not isinstance(exp_node.operand.value, bool)
    ):
        if abs(exp_node.operand.value) > 1000:
            raise ValueError("거듭제곱 지수가 너무 큽니다(최대 1000).")
        return
    raise ValueError("거듭제곱 지수는 상수(-1000 ~ 1000)만 허용됩니다.")

_THOUSANDS_FULL_RE = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?![\d])")
_THOUSANDS_2PLUS_RE = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3}){2,}(?![\d])")
_INNER_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\(([^()\[\]]*)\)")
_INNER_LIST_RE = re.compile(r"\[([^\[\]]*)\]")

def _clean_call_inner_commas(func_name: str, inner: str) -> str:
    if re.search(r",\s+", inner):
        parts = re.split(r",\s+", inner)
        cleaned_parts = [_THOUSANDS_FULL_RE.sub(lambda m: m.group(0).replace(",", ""), p) for p in parts]
        return ", ".join(cleaned_parts)
    fn = func_name.split(".")[-1]
    raw_parts = inner.split(",")
    if fn in ("min", "max", "pow"):
        if len(raw_parts) <= 2:
            return inner
        cand2 = _THOUSANDS_2PLUS_RE.sub(lambda m: m.group(0).replace(",", ""), inner)
        if cand2.count(",") >= 1:
            return cand2
        if (
            len(raw_parts) == 4
            and len(raw_parts[1]) == 3 and raw_parts[1].isdigit()
            and len(raw_parts[3]) == 3 and raw_parts[3].isdigit()
            and (raw_parts[1] == "000" or raw_parts[3] == "000")
        ):
            return f"{raw_parts[0]}{raw_parts[1]}, {raw_parts[2]}{raw_parts[3]}"
        return inner
    if fn == "round":
        if len(raw_parts) >= 3:
            first_arg = _THOUSANDS_FULL_RE.sub(lambda m: m.group(0).replace(",", ""), ",".join(raw_parts[:-1]))
            return f"{first_arg}, {raw_parts[-1]}"
        return inner
    return _THOUSANDS_FULL_RE.sub(lambda m: m.group(0).replace(",", ""), inner)

def _strip_thousands_commas_safely(expr: str) -> str:
    r"""
    [AST·문맥 인식 천 단위 쉼표 정제기]
    1) 함수 호출 내부(`min(a,b)`, `max(1,200,300)`, `min(1,500,000, 2,000,000)`, `round(1,234,567.89, 1)`)와
       괄호 밖 사칙연산(`+ 1,000,000`)을 분리하여 처리합니다.
    2) `max(100,200) + min(300, 400)`처럼 공백 없는 다중 인자 함수와 공백 있는 함수가 한 수식에 공존하더라도
       인자 구분자 쉼표가 천 단위 쉼표로 오인되어 숫자가 합쳐지는 현상을 100% 차단합니다.
    """
    s = (expr or "").strip()
    if not s or "," not in s:
        return s

    def _repl_call(m: re.Match) -> str:
        fn = m.group(1)
        inner = m.group(2)
        cleaned_inner = _clean_call_inner_commas(fn, inner).replace(",", "\x00")
        return f"{fn}({cleaned_inner})"

    cur = s
    for _ in range(6):
        nxt = _INNER_CALL_RE.sub(_repl_call, cur)
        if nxt == cur:
            break
        cur = nxt

    def _repl_list(m: re.Match) -> str:
        inner = m.group(1)
        if re.search(r",\s+", inner):
            parts = [_THOUSANDS_FULL_RE.sub(lambda x: x.group(0).replace(",", ""), p) for p in re.split(r",\s+", inner)]
            return "[" + "\x00 ".join(parts) + "]"
        return "[" + inner.replace(",", "\x00") + "]"

    cur = _INNER_LIST_RE.sub(_repl_list, cur)
    cur = _THOUSANDS_FULL_RE.sub(lambda m: m.group(0).replace(",", ""), cur)
    return cur.replace("\x00", ",")

def _validate_safe_math_ast(expr: str) -> None:
    """
    [AST 화이트리스트 보안 샌드박스]
    1) `().__class__.__base__` 등 모든 언더스코어(`_`) 속성 접근 및 허용되지 않은 AST 노드를 원천 차단합니다.
    2) `[1]*10**9`, `10**10000`, `pow(10, 10000)` 같은 메모리/CPU 고갈 수식을 AST 단계에서 차단합니다.
    """
    if len(expr) > 400:
        raise ValueError("수식이 너무 깁니다(400자 제한).")
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(f"허용되지 않는 수식 구문입니다: {type(node).__name__}")

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise ValueError(f"숫자 외의 상수는 허용되지 않습니다: {node.value!r}")

        if isinstance(node, ast.Name):
            if node.id.startswith("_") or (node.id not in _ALLOWED_CALC_FUNCS and node.id != "math"):
                raise ValueError(f"허용되지 않는 식별자입니다: {node.id}")

        if isinstance(node, ast.Attribute):
            if (
                not isinstance(node.value, ast.Name)
                or node.value.id != "math"
                or node.attr.startswith("_")
                or node.attr not in _ALLOWED_MATH_ATTRS
            ):
                raise ValueError(f"허용되지 않는 속성 접근입니다: {getattr(node, 'attr', '')}")

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in _ALLOWED_CALC_FUNCS:
                    raise ValueError(f"허용되지 않는 함수 호출입니다: {node.func.id}")
                if node.func.id == "pow" and len(node.args) >= 2:
                    _check_safe_pow_exponent(node.args[1])
            elif isinstance(node.func, ast.Attribute):
                if (
                    not isinstance(node.func.value, ast.Name)
                    or node.func.value.id != "math"
                    or node.func.attr not in _ALLOWED_MATH_ATTRS
                ):
                    raise ValueError("허용되지 않는 모듈 함수 호출입니다.")
                if node.func.attr == "pow" and len(node.args) >= 2:
                    _check_safe_pow_exponent(node.args[1])
            else:
                raise ValueError("간접 함수 호출은 허용되지 않습니다.")

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            _check_safe_pow_exponent(node.right)

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            if isinstance(node.left, (ast.List, ast.Tuple)) or isinstance(node.right, (ast.List, ast.Tuple)):
                raise ValueError("리스트/튜플 곱셈은 허용되지 않습니다.")

# ──────────────────────────────────────────────────────────────────
# [보안] eval() 제거: 크기 한도를 실행 중에 강제하는 AST 직접 해석기
#   정적 검사(_validate_safe_math_ast)는 지수 '상수'만 볼 수 있어 (((9**999)**999)**50)처럼
#   상수 지수 중첩으로 결과 크기가 10^(수억) 자리로 폭발하는 것을 막지 못했습니다(실측: 프로세스 무한 정지).
#   해석기는 모든 연산 '전에' 결과 크기를 예측해 상한을 넘으면 즉시 거부합니다.
# ──────────────────────────────────────────────────────────────────
_CALC_MAX_INT_BITS = 256          # 2^256 ≈ 1.2×10^77 — 세무 계산 결과로 충분히 넓고, 연산 비용은 무시 가능
_CALC_MAX_SEQ_LEN = 200
_CALC_MAX_STEPS = 5_000
_CALC_FUNCS = {"abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow, "int": int, "float": float}
_CALC_MATH = {name: getattr(math, name) for name in _ALLOWED_MATH_ATTRS}


class _CalcLimitError(ValueError):
    pass


def _calc_check_num(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        if v.bit_length() > _CALC_MAX_INT_BITS:
            raise _CalcLimitError("계산 결과가 허용 범위(약 10^77)를 넘습니다.")
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            raise _CalcLimitError("계산 결과가 무한대 또는 NaN입니다.")
        return v
    if isinstance(v, (list, tuple)):
        if len(v) > _CALC_MAX_SEQ_LEN:
            raise _CalcLimitError("목록이 너무 깁니다.")
        return v
    raise _CalcLimitError(f"허용되지 않는 값 형식입니다: {type(v).__name__}")


def _calc_pow(a, b):
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        raise _CalcLimitError("목록에는 거듭제곱을 쓸 수 없습니다.")
    if isinstance(a, int) and isinstance(b, int) and b > 0:
        # 결과 비트 수 ≈ b × bit_length(a) — 계산 전에 차단
        if a not in (0, 1, -1) and b * max(1, abs(a).bit_length() - 1) > _CALC_MAX_INT_BITS:
            raise _CalcLimitError("거듭제곱 결과가 너무 큽니다.")
    elif abs(b) > 1000:
        raise _CalcLimitError("거듭제곱 지수가 너무 큽니다(최대 1000).")
    return pow(a, b)


def _calc_binop(op, a, b):
    if isinstance(op, ast.Add):
        return a + b
    if isinstance(op, ast.Sub):
        return a - b
    if isinstance(op, ast.Mult):
        if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
            raise _CalcLimitError("리스트/튜플 곱셈은 허용되지 않습니다.")
        if isinstance(a, int) and isinstance(b, int) and a.bit_length() + b.bit_length() > _CALC_MAX_INT_BITS + 1:
            raise _CalcLimitError("곱셈 결과가 너무 큽니다.")
        return a * b
    if isinstance(op, ast.Div):
        return a / b
    if isinstance(op, ast.FloorDiv):
        return a // b
    if isinstance(op, ast.Mod):
        return a % b
    if isinstance(op, ast.Pow):
        return _calc_pow(a, b)
    raise _CalcLimitError(f"허용되지 않는 연산자입니다: {type(op).__name__}")


_CMP_OPS = {
    ast.Eq: lambda x, y: x == y, ast.NotEq: lambda x, y: x != y, ast.Lt: lambda x, y: x < y,
    ast.LtE: lambda x, y: x <= y, ast.Gt: lambda x, y: x > y, ast.GtE: lambda x, y: x >= y,
}


def _safe_eval_math(expr: str):
    """화이트리스트 검증(_validate_safe_math_ast) 통과 후, 모든 중간값의 크기를 검사하며 AST를 직접 해석합니다."""
    tree = ast.parse(expr, mode="eval")
    steps = [0]

    def ev(node):
        steps[0] += 1
        if steps[0] > _CALC_MAX_STEPS:
            raise _CalcLimitError("수식이 너무 복잡합니다.")
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return _calc_check_num(node.value)
        if isinstance(node, (ast.List, ast.Tuple)):
            return _calc_check_num([ev(e) for e in node.elts])
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            if isinstance(node.op, ast.USub):
                return _calc_check_num(-v)
            if isinstance(node.op, ast.UAdd):
                return _calc_check_num(+v)
            if isinstance(node.op, ast.Not):
                return not v
            raise _CalcLimitError("허용되지 않는 단항 연산입니다.")
        if isinstance(node, ast.BinOp):
            return _calc_check_num(_calc_binop(node.op, ev(node.left), ev(node.right)))
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = ev(comp)
                if not _CMP_OPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return ev(node.body) if ev(node.test) else ev(node.orelse)
        if isinstance(node, ast.Name):
            if node.id == "math":
                raise _CalcLimitError("math 모듈 자체는 값으로 쓸 수 없습니다.")
            raise _CalcLimitError(f"허용되지 않는 식별자입니다: {node.id}")
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "math" and node.attr in ("pi", "e"):
                return getattr(math, node.attr)
            raise _CalcLimitError("허용되지 않는 속성 접근입니다.")
        if isinstance(node, ast.Call):
            if node.keywords:
                raise _CalcLimitError("키워드 인자는 허용되지 않습니다.")
            args = [ev(a) for a in node.args]
            if isinstance(node.func, ast.Name) and node.func.id in _CALC_FUNCS:
                fname, fn = node.func.id, _CALC_FUNCS[node.func.id]
            elif (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                  and node.func.value.id == "math" and node.func.attr in _CALC_MATH and node.func.attr not in ("pi", "e")):
                fname, fn = "math." + node.func.attr, _CALC_MATH[node.func.attr]
            else:
                raise _CalcLimitError("허용되지 않는 함수 호출입니다.")
            if fname in ("pow", "math.pow") and len(args) >= 2:
                if len(args) > 2:
                    raise _CalcLimitError("pow의 세 번째 인자는 허용되지 않습니다.")
                return _calc_check_num(_calc_pow(args[0], args[1]) if fname == "pow" else math.pow(args[0], args[1]))
            if fname in ("int", "float") and args and not isinstance(args[0], (int, float)):
                raise _CalcLimitError("int/float에는 숫자만 넣을 수 있습니다.")
            return _calc_check_num(fn(*args))
        raise _CalcLimitError(f"허용되지 않는 수식 구문입니다: {type(node).__name__}")

    return ev(tree)


def run_tax_calculator_for_gemini(formula_expression: str, description: str = "") -> str:
    """
    파이썬 사칙연산 수식(formula_expression)을 입력받아 단 1원의 오차 없이 정밀 계산합니다.
    - 숫자에는 천 단위 쉼표를 쓰지 말 것 (예: 1500000 * 0.15).
    - 함수 인자는 쉼표+공백으로 구분할 것 (예: min(1500000, 2000000), round(x, 2)).
    """
    expr_str = str(formula_expression or "").strip()
    desc_str = str(description or "").strip()
    _emit_live_status(f"🧮 2단계: 파이썬 1원 단위 정밀 수리 계산기 구동 중 ({desc_str or expr_str[:20]})...")
    print(f"\n[시스템] 🧮 파이썬 정밀 세액 계산기 가동: [{desc_str}] 수식: {expr_str}")
    if not expr_str:
        return "❌ 수식 계산 오류 (): 빈 수식입니다 -> 숫자에 쉼표 없이 올바른 파이썬 사칙연산 수식으로 다시 호출하세요."
    if len(expr_str) > 2000:   # 쉼표 정규화(정규식) 이전에 원문 길이 차단 — 거대 입력으로 인한 정규식 CPU 소모 방지
        return "❌ 수식 계산 오류: 수식이 너무 깁니다(2000자 제한) -> 수식을 나누어 다시 호출하세요."
    try:
        clean_expr = _strip_thousands_commas_safely(formula_expression)
        _validate_safe_math_ast(clean_expr)
        result = _safe_eval_math(clean_expr)
        if isinstance(result, (int, float)):
            return _record(
                "detail",
                f"🧮 [정밀 계산 완료 - {description} | 수식: {clean_expr}]\n- 입력 수식: {clean_expr}\n- 정확한 산출값: {result:,.4f} (정수 반올림: {round(result):,}원)"
            )
        return _record("detail", f"🧮 [정밀 계산 완료 - {description} | 수식: {clean_expr}]\n- 결과: {str(result)[:300]}")
    except Exception as e:
        return f"❌ 수식 계산 오류 ({formula_expression}): {e} -> 숫자에 쉼표 없이 올바른 파이썬 사칙연산 수식으로 다시 호출하세요."

# 3. 에이전트 시스템 프롬프트 템플릿 (기존 12대 도구 라우팅 규칙 100% 보존 + 1턴 직행 병렬 조회 + 계산기 쉼표 예방 문구 결합)
SYSTEM_PROMPT = """당신은 세무·법령·회계·노무 검토 자율 전문 에이전트입니다.
사용자의 질문 성격에 따라 아래의 **[투트랙(Two-Track) 운영 프로토콜]**을 지능적으로 구분하여 작동하세요.

[투트랙(Two-Track) 운영 프로토콜 — 최우선 판단 기준]
- **📋 트랙 1 [전문 검토 보고서 모드]**: 세무·법령·회계·노무·4대보험에 관한 법리 검토, 요건 판정, 수당·세액·공제 계산, 기업 공시·실거래가·공시지가·사업자 상태 조회 등 **법령 검색이나 데이터/수식 계산이 필요한 모든 전문 질문**일 때 작동합니다. 반드시 먼저 제공된 도구(API)들을 사용하여 실제 원문 데이터와 통계를 확인한 뒤, **3번의 `<precheck>` 정식 3단 크로스체크 검수표를 한 글자도 축약 없이 먼저 작성하고 이어서 [1. 결론 -> 2. 내용 -> 3. 관련법령] 보고서 양식**으로 출력하세요.
- **💬 트랙 2 [자유 대화 및 실무 초안 모드]**: 사용자가 일상적인 대화·인사·브레인스토밍을 하거나, 직전 검토 결과를 바탕으로 **'거래처/고객 안내용 카톡·문자·이메일 초안 작성', '쉬운 요약 설명', '문장 다듬기', '일반 양식 작성'** 등을 요청한 경우에 작동합니다. 이때는 `<precheck>`나 보고서 양식, 대괄호 출처 태그([조문:...])를 모두 생략하고 자연스럽고 친절한 대화체나 사용자가 요청한 실무 양식(카톡/이메일 등)으로 자유롭게 답변하세요.
  * **[📱 카카오톡·문자 안내문 작성 시 절대 고정 규칙]**:
    1. **100% 순수 텍스트 전용**: 카카오톡에 복사·붙여넣기 했을 때 기호가 그대로 노출되지 않도록 별표(`**굵게**`), 샵(`### 제목`), 마크다운 표(`| --- |`), 꺾쇠(`>`) 등 마크다운 문법을 **절대 단 한 개도 쓰지 말고**, 오직 순수 텍스트와 대괄호 소제목(`[한줄 결론]` 등), 하이픈(`- `)만 사용할 것.
    2. **법령명·조문번호·판례번호 완전 제외**: `조세특례제한법 제29조의8`, `제1항`, `대법원 2020두...` 같은 법령명이나 조문번호, 사건번호는 **단 한 글자도 적지 말 것.**
    3. **초간단·쉬운 일상 용어 사용**: 세법을 전혀 모르는 거래처 대표님이 스마트폰으로 5초 만에 이해할 수 있도록 어려운 전문용어(상시근로자, 사후관리 추징, 손금불산입, 익금산입, 과세표준 등)를 모두 쉬운 일상 표현(전체 직원 수, 직원이 줄면 세금을 다시 내야 함, 비용 처리 불가 등)으로 바꿔서 짧고 단순하게(10~12줄 이내) 작성할 것.

[트랙 1 (전문 검토 보고서 모드) 필수 도구 호출 원칙]
- **[핵심 조문 조회 및 ⚡ 1턴 고속 직행 원칙]**: 세법·노동법·공단 규정 등 법령 질문은 **법률과 시행령(필요시 시행규칙)의 해당 조문을 모두** 원문으로 조회한 뒤 답변할 것. 특히 정식 법령명을 알고 있는 현행 법령(예: 조세특례제한법, 조세특례제한법 시행령, 법인세법, 소득세법, 부가가치세법, 상속세 및 증여세법, 국세기본법, 지방세법, 농어촌특별세법, 근로기준법 등)은 `search_law_for_gemini` 목록 검색을 거치지 말고 첫 턴에 바로 `get_law_details_for_gemini(doc_id='조세특례제한법', target='law', query_filter='제29조의8, 제127조, 제132조')`처럼 `doc_id`에 정식 법령명을 넣고 필요한 조문번호들을 `query_filter`에 쉼표로 묶어 한 번에 직행 조회할 것(법률과 시행령도 한 턴에 동시에 병렬 호출할 것). 도구 호출은 필요한 만큼 하되, **이미 결과를 받은 검색을 같은 검색어로 반복하지 말 것.**
- **[🕰️ 과거 귀속연도(경정청구·세무조사·구법) 조회 원칙]**: 질문에 특정 과거 연도나 과거 시점(예: '2021년 귀속', '2022년 양도분', '종전 규정')이 명시된 경우, 반드시 **`search_historical_law_for_gemini(law_name, target_date, query_filter)`** 도구를 호출하여 해당 과거 과세기간 당시에 시행되던 구법(연혁법령) 원문을 직접 대조할 것.
- 법령 검색(search_law_for_gemini, target='law')의 keyword에는 **법령명만** 넣을 것 (예: '소득세법', '근로기준법', '소득세법 시행령'). 주제어는 넣지 말 것.
- 조회한 원문에서 직접 확인하지 못한 금액·비율·연도는 단정하지 말고 **"(원문 미확인)"**이라고 표시할 것.
- **[근거 표시 의무 (트랙 1 전용)]** 전문 검토 보고서(1. 결론 ~ 3. 관련법령)를 작성할 때 판례·심판례·해석례·예규·법령 조문을 근거로 쓰는 문장 끝에는 반드시 아래 형식의 근거 표시를 붙일 것(콜론 ':'과 닫는 대괄호 ']'가 누락되지 않도록 주의).
  * 판례: [판례:2005두9415] / 헌법재판소 결정례: [헌재:2021헌바123] / 조세심판: [심판례:조심2020서1234] / 법령해석례: [해석례:안건번호] / 예규·고시: [예규:문서명 또는 번호]
  * 법령 조문·부칙·별표: [조문:법인세법 시행령 제89조] / [부칙:조세특례제한법 부칙 제2조] / [별표:소득세법 시행령 별표1] (반드시 정식 법령명과 콜론 ':' 포함. '동법', '같은 법' 사용 금지)
- **판례·심판례·해석례 인용 규칙**: 판결요지·결정요지를 서술하는 사건은 반드시 get_law_details_for_gemini(target='prec' 등)로 **원문을 조회한 사건만** 쓸 것. 목록 검색에서만 본 사건은 사건번호·선고일만 적고 "(요지 미조회)"로 표시할 것. **도구로 조회하지 않은 사건번호를 기억으로 적지 말 것.**
- **법령 조문 인용 규칙**: 전문 검토 보고서에 법령명과 함께 적는 조문(예: 「법인세법」 제52조)은 반드시 get_law_details_for_gemini 또는 search_historical_law_for_gemini로 **그 조문을 조회한 것만** 쓸 것. 조회하지 않은 조문이 필요하면 먼저 조회할 것.
- **답변에 시스템·도구·검증 절차·삭제 여부에 대한 언급을 절대 쓰지 말 것**. 근거가 부족하면 "관련 원문을 확인하지 못했다"고만 쓸 것.
- **법령명은 반드시 정식 명칭**으로 쓸 것 (예: 「상속세 및 증여세법」, 「조세특례제한법 시행령」, 「근로기준법」).
- **근거 표시는 그 문장의 내용이 실제로 해당 원문에 있을 때만** 붙일 것. 한 판례에 없는 내용을 그 판례 근거 표시로 묶지 말 것.
- **따옴표(“ ”) 인용은 조회한 원문을 글자 그대로 옮길 때만** 사용하고, 요약·의역할 때는 따옴표를 쓰지 말 것.
- **[수식 및 표 작성 규칙]**: 인쇄용 문서 출력 시 글자가 깨지는 LaTeX 수식 문법($$, $, \\frac, \\times, \\text 등)은 절대 사용하지 말고 일반 텍스트 기호(×, ÷, +, -, =)로만 깔끔하게 표기할 것. 마크다운 표를 작성할 때는 반드시 표 위아래로 빈 줄을 띄우고 헤더 구분선(| --- | --- |)을 정확히 작성할 것.
- 현행 법령·판례·심판례·예규·지방세조례 확인: 정식 법령명을 아는 현행 법령은 'get_law_details_for_gemini'(doc_id에 법령명, query_filter에 조문번호 입력)로 바로 읽고, 판례·심판례·예규·조례는 'search_law_for_gemini'로 ID를 찾은 뒤 'get_law_details_for_gemini'로 원문을 읽을 것.
- 과거 시점 구법(연혁법령) 원문 확인: 'search_historical_law_for_gemini' 호출.
- 기업 공시·재무·지분·배당·출자 확인: 'search_dart_corp_for_gemini' 호출.
- 사업자 상태(휴·폐업/과세유형) 및 진위확인: 'check_nts_biz_status_for_gemini' 또는 'verify_nts_biz_info_for_gemini' 호출.
- 부동산 매매 실거래가 확인: 'search_real_estate_trade_for_gemini' 호출 / 전월세(보증금·월세) 실거래가 확인: 'search_real_estate_rent_for_gemini' 호출.
- 부동산 개별공시지가 및 공동주택 공시가격(기준시가) 확인: 'search_official_land_price_for_gemini' 호출.
- 건축물대장 표제부·층별개요(겸용주택 주택/상가 면적 비율·주용도·위반건축물 여부) 확인: 'search_building_ledger_for_gemini' 호출.
- 근로복지공단 고용·산재보험 사업장 상시인원(피보험자수)·성립일·업종 확인: 'search_comwel_workplace_for_gemini' 호출.
- 4대보험(국민연금·건강보험·노인장기요양보험·고용보험·산재보험) 전체 월별 고지보험료, 연간 보험료 고지총액 합계, 사업주(회사)/근로자 부담분, 추정 인건비(과세보수총액) 및 월별 가입자수(신규/상실) 통합 확인: 'search_nps_workplace_for_gemini' 호출 (사업자등록번호 10자리를 알고 있으면 biz_no_prefix6에 함께 넣어 산재·고용보험 업종요율까지 자동 연계할 것).
- 관세청 수출입 주간 과세환율(관세법 제18조 · 수입세금계산서 과세표준 검증) 확인: 'search_customs_exchange_rate_for_gemini' 호출.
- 중소기업·소상공인·창업기업 정부지원사업, 정책자금(융자·보증), R&D·기술개발, 고용·인력 지원금, 수출·내수·경영 바우처 공고 확인: 'search_bizinfo_support_for_gemini' 호출 (category에 '금융'/'기술'/'인력'/'수출'/'내수'/'창업'/'경영' 또는 공란, hashtags에 지역명 '서울'/'경기'/'부산' 등, keyword에 세부 검색어 입력).
- 세액·공제액·수당·지분율 등 모든 숫자 계산: 반드시 'run_tax_calculator_for_gemini'를 호출하여 단 1원의 오차도 없이 정확히 계산할 것. (수식 내 숫자에는 천 단위 쉼표를 넣지 말고 `1500000 * 0.15`처럼 적으며, 함수 인자는 `min(1500000, 2000000)`처럼 쉼표+공백으로 구분할 것)

1. 자료 검토 우선순위 및 기준
- 1순위 (법령 및 자치법규/행정규칙): 국가법령정보센터 기준 가장 최근 개정된 [법률 / 시행령 / 시행규칙 / 지방세 조례 / 행정규칙(고시·훈령)]을 최우선 기준으로 삼되, 과거 귀속연도 사안은 해당 과세기간 시행 연혁법령(구법)을 대조할 것.
- 2순위 (공식 유권해석·판례·조세심판례): [대법원 판례('prec') / 조세심판원 결정례('decc') / 법령해석례('expc') / 세법집행기준·예규]를 대조할 것.
- 3순위 (회계기준·DART 전자공시·국세청·국토부·한국은행·업종DB): 한국회계기준원, 금융감독원(DART), 국세청 사업자 상태/진위확인, 국토교통부 실거래가 및 공시지가(브이월드), 한국은행(ECOS) 공식 환율·금리, 국세청 업종코드 데이터를 참고할 것.
- 4순위 (실무 참고): 전문가 블로그 글은 전산 처리나 실무 흐름 파악용으로만 참고하되, 1~3순위 법령·예규와 충돌하거나 법적 근거가 없는 편법은 절대 채택하지 말 것.

2. 할루시네이션(임의 생성) 금지 규칙
- 확인되지 않은 법조문 번호, 통칙·집행기준 번호, 예규·판례·심판례 번호, 업종코드(6자리), 환율·금리·재무제표·지분율·실거래가·공시지가 수치, 깨진 상세 URL을 절대 임의로 추측하거나 조합해 만들어내지 말 것.

3. 트랙 1 (전문 검토 보고서 모드) 필수 출력 양식 (반드시 아래 `<precheck>` 3단 크로스체크 검수표를 최소 200자 이상 구체적인 조문·수치로 작성한 뒤, 그 검증 결과를 바탕으로 `### 1. 결론`을 도출할 것. `<precheck>`가 누락되거나 부실하면 감사 시스템에서 즉시 반려됨!)

<precheck>
- [1단: 오늘 날짜(KST) 기준 시점 부등식 및 법령 시행일·귀속시기·일몰 대조] 반드시 첫 줄에 「오늘 날짜(YYYY.MM.DD) vs 질문 사건 시점(연도 미지정 시 당해 연도인 2026년) vs 조회한 조문·부칙 시행일(예: 2026.1.1.)」의 선후 관계를 부등식(예: `2026.01.01 시행일 <= 오늘 날짜 → 이미 유예 종료되어 현재 2026년 전면 시행 중` / `2025.12.31 유예기한 < 오늘 날짜 → 이미 지난해 만료됨`)으로 먼저 확정하고, 도구로 실제 원문을 조회한 법률·시행령·시행규칙·부칙의 정확한 조·항·호 번호와 일몰기한을 대조할 것 (절대 현재를 2025년으로 착각하거나 2026.1.1. 시행 규정을 미시행 유예 규정으로 오판하지 말 것!)
- [2단: 단서·배제 요건 및 연쇄 세목(농특세·소득처분) 정밀 점검] 해당 조문의 단서(다만, ~제외한다), 특수관계인·지배주주·업종·규모 배제 요건, 최저한세(조세특례제한법 제132조), 중복지원 배제(제127조), 농어촌특별세(20%) 부과 여부, 사후관리 추징 요건, 그리고 법인세 손금불산입 시 소득처분(상여·배당·기타사외유출)에 따른 원천세·4대보험 연쇄 리스크 중 본 사안에 적용되는 항목을 빠짐없이 짚어낼 것
- [3단: 수리 계산식·지방소득세·가산세 감면율 최종 검산] 파이썬 정밀 계산기로 산출한 수식, 세율 구간·누진공제, 안분 비율, 공제 한도액의 오차 여부 및 지방소득세(10%) 별도 부과 여부를 수치로 직접 검산할 것 (수치 계산이 없는 법리·절차 질문인 경우 법정 신고·경정청구 기한, 가산세율 및 수정신고·기한후신고 감면율 요건을 수치로 재확인할 것)
</precheck>

### 1. 결론
- 위 3단 크로스체크 결과를 바탕으로 질문에 대한 핵심 결론(가능/불가능 여부, 적용 세율·산출세액·공제액·수당·과세유형·업종코드·회계처리 등)을 명확하고 간결하게 요약

---

### 2. 내용

#### (1) 상세 법리 및 기준 검토
- 1~3순위 근거(법령 조문, 단서·예외 요건, 지자체 조례, 회계기준, 각 기관 API 조회 데이터, 예규·판례·조세심판례)를 바탕으로 상세 법리 및 요건 설명
- **[🔄 최근 개정 조문 자동 신·구 비교 원칙]**: 만약 조회한 핵심 조문에 최근 개정사항(2025~2026년 개정·신설 또는 시행예정 규정)이 포함되어 있거나 과거 구법과 현행법을 비교하는 질의라면, 별도 요청이 없더라도 본 항목 안에 반드시 **`| 구분 | 종전 규정(구법) | 현행(개정) 규정 | 적용시기 및 실무 영향 |`** 형식의 마크다운 신·구 비교표를 포함하여 무엇이 바뀌었는지 한눈에 보이도록 정리할 것.

#### (2) 계산
- 정밀 계산기(run_tax_calculator_for_gemini)로 산출한 단계별 계산 과정 및 산출 내역 (※ 단, 질문에 세액·수당·비율 등 수치 계산 내용이 전혀 없는 단순 법리 질의라면 이 '(2) 계산' 소제목과 항목은 완전히 생략하고 바로 아래 항목을 '(2) 실무 적용 및 리스크 주의사항'으로 당겨서 작성할 것)

#### (3) 실무 적용 및 리스크 주의사항
- 가산세 및 사후관리(고용감소 추징 등) 리스크, 최저한세·농어촌특별세·중복공제 배제 여부, 소득처분·지방소득세 등 연쇄 세목 영향, 증빙 수취 요건, 홈택스/위택스 신고 시 주의할 점 정리 (※ 위 계산 항목이 생략된 경우 '(2) 실무 적용 및 리스크 주의사항'으로 번호를 맞춰 기재할 것)

---

### 3. 관련법령
- 이번 검토에서 실제 원문을 조회한 법령·조문·판례·예규만 나열하되, 하위 항목에「법령명」 제N조(조문제목) 또는 사건번호를 명확히 기재할 것
  * 국가법령정보센터(법령·판례·심판례·조례·기본통칙): https://www.law.go.kr
  * 금융감독원 전자공시시스템(DART): https://dart.fss.or.kr
  * 국토교통부 실거래가 공개시스템 / 브이월드(공시가격): https://rt.molit.go.kr / https://www.vworld.kr
  * 한국은행 경제통계시스템(ECOS) / 관세청 유니패스(과세환율): https://ecos.bok.or.kr / https://unipass.customs.go.kr
  * 국세청 홈택스(사업자상태/업종코드): https://www.hometax.go.kr
  * 4대사회보험 정보연계센터 / 국민연금·근로복지공단: https://www.4insure.or.kr / https://www.nps.or.kr / https://www.comwel.or.kr
  * 중소벤처기업부 기업마당(정부지원사업 통합공고): https://www.bizinfo.go.kr
"""

def _extract_and_strip_precheck(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    m = re.search(r"<precheck>(.*?)</precheck>", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        precheck_body = m.group(1).strip()
        cleaned = re.sub(r"<precheck>.*?</precheck>\s*", "", text, flags=re.DOTALL | re.IGNORECASE).lstrip()
        return cleaned, precheck_body
    elif "<precheck>" in text.lower() and "### 1. 결론" in text:
        idx = text.find("### 1. 결론")
        precheck_body = re.sub(r"</?precheck>", "", text[:idx], flags=re.IGNORECASE).strip()
        return text[idx:].lstrip(), precheck_body
    return text.lstrip(), ""

def _is_precheck_thorough(precheck_body: str) -> bool:
    """
    [속도 개선 ⑤ — 무손실 정밀 판정]
    - <precheck> 3단 자기검열(120자 이상 + 1·2·3단 필수 점검)은 이전과 100% 동일하게 강제하여 할루시네이션 차단력을 완벽히 유지합니다.
    - 다만 비계산 법리 질의에서 모델이 3단에 '기한', '가산세', '해당 없음' 등의 표현을 썼을 때 억울하게 부실 판정되어
      멀쩡한 보고서를 통째로 다시 쓰던(15~25초 지연) 오탐(False Positive)만 제거했습니다.
    """
    if not precheck_body or len(precheck_body.strip()) < 120:
        return False
    has_step1 = any(k in precheck_body for k in ("1단", "원문", "법령", "조문", "개정", "일몰", "귀속"))
    has_step2 = any(k in precheck_body for k in ("2단", "단서", "예외", "배제", "최저한세", "농어촌", "농특세", "사후관리", "소득처분", "요건"))
    has_step3 = any(k in precheck_body for k in ("3단", "검산", "계산", "수치", "기한", "가산세", "지방소득세", "세율", "공제액", "산출"))
    return bool(has_step1 and has_step2 and has_step3)

def _is_valid_report_body(text: str) -> bool:
    """재작성 응답이 '알겠습니다' 같은 짧은 대답일 때 기존 보고서를 덮어쓰지 않도록 검증합니다."""
    if not text or len(text.strip()) < 250:
        return False
    return bool(re.search(r"###\s*1\.\s*결론|###\s*2\.\s*내용", text))

# ---------------------------------------------------------
# 🔗 검증 완료된 법령·판례·심판례·해석례·예규·기본통칙 100% 원클릭 직링크 자동 결합 엔진
#    (괄호가 포함된 판례·해석례 URL 생성 시 `%28`, `%29` 인코딩으로 마크다운/PDF/워드 괄호 잔류 원천 방지)
# ---------------------------------------------------------
def _build_direct_law_url(kind: str, val: str, trace: dict, rev_id_map: dict, meta_map: dict, known_titles: list[str] | None = None) -> str:
    """검증된 태그 종류와 값으로부터 국가법령정보센터 공식 원문 직링크 URL을 생성합니다."""
    if known_titles is None:
        known_titles = _known_law_titles(trace)
    if kind in ("조문", "부칙"):
        refs = [r[:3] for r in _find_article_refs_with_kind(val, trace, titles=known_titles)]
        if refs:
            law_name, jo, gaji = refs[0]
            if kind == "부칙" or "부칙" in val:
                return f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}"
            art_str = f"제{jo}조" + (f"의{gaji}" if gaji else "")
            return f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}/{urllib.parse.quote(art_str)}"
        law_prefix = re.sub(r"부칙.*", "", val).strip()
        resolved_ln = _resolve_law_name(law_prefix, known_titles) if law_prefix else None
        if resolved_ln:
            return f"https://www.law.go.kr/법령/{urllib.parse.quote(resolved_ln)}"
    elif kind == "별표":
        seq_id = meta_map.get(("licbyl", _norm(val)))
        if seq_id:
            return f"https://www.law.go.kr/LSW/flDownload.do?flSeq={seq_id}"
        law_prefix = re.sub(r"별표.*", "", val).strip()
        resolved_ln = _resolve_law_name(law_prefix, known_titles) if law_prefix else None
        if resolved_ln:
            return f"https://www.law.go.kr/법령/{urllib.parse.quote(resolved_ln)}"
        return f"https://www.law.go.kr/LSW/lsSc.do?query={urllib.parse.quote(val)}"
    elif kind in ("헌재", "헌재결정례"):
        nos = _find_case_numbers(val)
        if nos:
            c_no = nos[0]
            seq_id = meta_map.get(("detc", _norm(c_no))) or rev_id_map.get(_norm(c_no))
            if seq_id:
                return f"https://www.law.go.kr/LSW/detcInfoP.do?detcSeq={seq_id}"
            return f"https://www.law.go.kr/헌재결정례/%28{urllib.parse.quote(c_no)}%29"
    elif kind == "판례":
        nos = _find_case_numbers(val)
        if nos:
            c_no = nos[0]
            if re.search(r"헌[가나다라마바사아]", c_no):
                seq_id = meta_map.get(("detc", _norm(c_no))) or rev_id_map.get(_norm(c_no))
                if seq_id:
                    return f"https://www.law.go.kr/LSW/detcInfoP.do?detcSeq={seq_id}"
                return f"https://www.law.go.kr/헌재결정례/%28{urllib.parse.quote(c_no)}%29"
            seq_id = meta_map.get(("prec", _norm(c_no))) or rev_id_map.get(_norm(c_no))
            if seq_id:
                return f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={seq_id}"
            return f"https://www.law.go.kr/판례/%28{urllib.parse.quote(c_no)}%29"
    elif kind == "심판례":
        nos = _find_case_numbers(val)
        if nos:
            c_no = nos[0]
            seq_id = meta_map.get(("decc", _norm(c_no))) or rev_id_map.get(_norm(c_no))
            if seq_id:
                return f"https://www.law.go.kr/LSW/deccInfoP.do?deccSeq={seq_id}"
            return f"https://www.law.go.kr/LSW/lsSc.do?query={urllib.parse.quote(c_no)}"
    elif kind == "해석례":
        clean_no = val.split()[0].strip()
        seq_id = meta_map.get(("expc", _norm(clean_no))) or meta_map.get(("expc", _norm(val)))
        if seq_id:
            return f"https://www.law.go.kr/LSW/expcInfoP.do?expcSeq={seq_id}"
        return f"https://www.law.go.kr/법령해석례/%28{urllib.parse.quote(clean_no)}%29"
    elif kind == "예규":
        clean_name = re.sub(r"\s+", "", val)
        seq_id = meta_map.get(("admrul", _norm(val)))
        if seq_id:
            return f"https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq={seq_id}"
        return f"https://www.law.go.kr/행정규칙/{urllib.parse.quote(clean_name)}"
    return ""

_UNLINKED_CITATION_TAG_RE = re.compile(
    r"(?<!\[)\[(판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])([^\]]+)\](?!\]|\(\s*https?://)"
)
_REF_BULLET_LINE_RE = re.compile(r"^(\s*(?:[-*•◦‣]|\d+\.)\s+)(.+)$")
_TRAILING_TAG_STRIP_RE = re.compile(
    r"\s*\[(?:판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])[^\]]+\]\s*$"
)

def _inject_direct_law_links(text: str, trace: dict = None) -> str:
    """
    1) 본문의 [조문:...], [부칙:...], [별표:...], [판례:...], [헌재:...], [심판례:...], [해석례:...], [예규:...] 태그(콜론 누락 포함)에 100% 검증된 법제처 원문 직링크를 결합합니다.
    2) '### 3. 관련법령' 섹션의 모든 하위 조문·부칙·판례·헌재결정례 줄 및 기본통칙 줄을 클릭하면 즉시 해당 법제처 원문 페이지로 이동하도록 글자 자체에 직링크를 걸어줍니다.
    """
    if not text:
        return ""

    text = _normalize_citation_tags(text)

    rev_id_map = {}
    meta_map = {}
    if trace:
        for doc_id, case_no in (trace.get("id_map") or {}).items():
            rev_id_map[_norm(case_no)] = str(doc_id).strip()
        meta_map = trace.get("meta_map") or {}

    local_url_memo: dict[tuple[str, str], str] = {}

    def _replace_tag_with_link(match: re.Match) -> str:
        kind = match.group(1).strip()
        val = match.group(2).strip()
        m_key = (kind, val)
        if m_key in local_url_memo:
            return local_url_memo[m_key]
        canonical_tag = f"[{kind}: {val}]"
        url = _build_direct_law_url(kind, val, trace, rev_id_map, meta_map, known_titles=known_titles)
        res_str = f"[{canonical_tag}]({url})" if url else canonical_tag
        local_url_memo[m_key] = res_str
        return res_str

    lines = text.split("\n")
    in_refs = False
    known_titles = _known_law_titles(trace)
    base_tax_laws = sorted(_COMMON_LAWS, key=len, reverse=True)
    out_lines = []

    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            in_refs = ("관련법령" in s) or ("관련 법령" in s) or ("근거 자료" in s) or ("근거자료" in s)
            out_lines.append(line)
            continue

        if not in_refs:
            linked_line = _UNLINKED_CITATION_TAG_RE.sub(_replace_tag_with_link, line) if "[" in line else line
            out_lines.append(linked_line)
            continue

        if s:
            m_bullet = re.match(r"^(\s*(?:[-*•◦‣]|\d+\.)\s+)(.+)$", line)
            if m_bullet and "](" not in line and "http://" not in line and "https://" not in line:
                prefix_bullet, item_body = m_bullet.group(1), m_bullet.group(2).strip()
                clean_item_body = re.sub(
                    r"\s*\[(?:판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])[^\]]+\]\s*$",
                    "",
                    item_body
                ).strip() or item_body
                direct_url = ""
                compact_body = _norm(item_body)

                if "기본통칙" in compact_body:
                    matched_base_law = ""
                    for blaw in base_tax_laws:
                        if blaw in compact_body:
                            matched_base_law = blaw
                            break
                    if not matched_base_law:
                        for alias, full in _LAW_ALIASES.items():
                            if alias in compact_body:
                                matched_base_law = full
                                break
                    if matched_base_law:
                        rule_title = f"{matched_base_law}기본통칙"
                        direct_url = f"https://www.law.go.kr/행정규칙/{urllib.parse.quote(rule_title)}"

                if not direct_url:
                    art_refs = _find_article_refs(item_body, trace)
                    if art_refs:
                        law_name, jo, gaji = art_refs[0]
                        if "부칙" in item_body:
                            direct_url = f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}"
                        else:
                            art_str = f"제{jo}조" + (f"의{gaji}" if gaji else "")
                            direct_url = f"https://www.law.go.kr/법령/{urllib.parse.quote(law_name)}/{urllib.parse.quote(art_str)}"

                if not direct_url:
                    case_nos = _find_case_numbers(item_body)
                    if case_nos:
                        c_no = case_nos[0]
                        if ("조심" in item_body) or ("국심" in item_body) or ("심판" in item_body):
                            seq_id = meta_map.get(("decc", _norm(c_no))) or rev_id_map.get(_norm(c_no))
                            if seq_id:
                                direct_url = f"https://www.law.go.kr/LSW/deccInfoP.do?deccSeq={seq_id}"
                            else:
                                direct_url = f"https://www.law.go.kr/LSW/lsSc.do?query={urllib.parse.quote(c_no)}"
                        elif re.search(r"헌[가나다라마바사아]", c_no) or ("헌재" in item_body) or ("헌법재판소" in item_body):
                            seq_id = meta_map.get(("detc", _norm(c_no))) or rev_id_map.get(_norm(c_no))
                            if seq_id:
                                direct_url = f"https://www.law.go.kr/LSW/detcInfoP.do?detcSeq={seq_id}"
                            else:
                                direct_url = f"https://www.law.go.kr/헌재결정례/%28{urllib.parse.quote(c_no)}%29"
                        else:
                            seq_id = meta_map.get(("prec", _norm(c_no))) or rev_id_map.get(_norm(c_no))
                            if seq_id:
                                direct_url = f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={seq_id}"
                            else:
                                direct_url = f"https://www.law.go.kr/판례/%28{urllib.parse.quote(c_no)}%29"

                if not direct_url:
                    for t in known_titles:
                        if t in compact_body:
                            direct_url = f"https://www.law.go.kr/법령/{urllib.parse.quote(t)}"
                            break

                if direct_url:
                    line = f"{prefix_bullet}[{clean_item_body}]({direct_url})"
                else:
                    line = re.sub(
                        r"(?<!\[)\[(판례|심판례|헌재|헌재결정례|해석례|예규|조문|부칙|별표)(?:\s*[:：]\s*|\s*)(?=[가-힣A-Za-z0-9「])([^\]]+)\](?!\]|\(\s*https?://)",
                        _replace_tag_with_link,
                        line
                    )

        out_lines.append(line)

    return "\n".join(out_lines)

def _clean_latex_for_export(text: str) -> str:
    if not text:
        return ""
    s, _ = _extract_and_strip_precheck(text)
    s = re.sub(r"\$\$(.*?)\$\$", r"\1", s, flags=re.DOTALL)
    s = re.sub(r"\$([^$\n]+)\$", r"\1", s)
    s = re.sub(r"\\text(?:bf|rm|it)?\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"(\1/\2)", s)
    s = s.replace(r"\times", " × ").replace(r"\div", " ÷ ").replace(r"\cdot", "·")
    s = s.replace(r"\%", "%").replace(r"\_", "_").replace(r"\,", ",")
    s = re.sub(r"\\(left|right|quad|qquad|mathrm|mathbf)\b", "", s)
    s = re.sub(
        r"(\[(?:조문|부칙|별표|판례|심판례|헌재|헌재결정례|해석례|예규)(?:\s*[:：]\s*|\s+)(?=[가-힣A-Za-z0-9「])[^\]\n(]+?)\s+(\()(?![^\n\[]*\])",
        r"\1] \2",
        s
    )
    s = _normalize_citation_tags(s)
    return s

def extract_safe_text(response) -> str:
    if not response:
        return ""
    try:
        if getattr(response, "text", None):
            return response.text
    except Exception:
        pass

    extracted_parts = []
    try:
        for cand in getattr(response, "candidates", []) or []:
            content = getattr(cand, "content", None)
            if content:
                for part in getattr(content, "parts", []) or []:
                    if getattr(part, "text", None):
                        extracted_parts.append(part.text)
    except Exception:
        pass
    return "\n".join(extracted_parts).strip()

def _execute_with_key_and_model(
    api_key: str,
    model_id: str,
    user_input: str,
    dynamic_prompt: str,
    tools_list: list,
    safety_settings: list,
    unleash: bool = False,
    raw_query: str = ""
) -> tuple[str, int]:
    timeout_ms = 120000 if unleash else 60000
    max_remote_calls = 30 if unleash else 20
    max_out_tokens = 32768 if unleash else 16384

    temp_client = make_genai_client(api_key, timeout_ms)

    chat = temp_client.chats.create(
        model=model_id,
        config=types.GenerateContentConfig(
            tools=tools_list,
            system_instruction=dynamic_prompt,
            safety_settings=safety_settings,
            max_output_tokens=max_out_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=max_remote_calls
            )
        )
    )
    stage_secs: list[tuple[str, float]] = []
    trace_token = _TOOL_TRACE.set(_new_trace(unleash=unleash))
    try:
        _emit_live_status(f"🔎 1단계: 질의 쟁점 분석 및 법제처·공공기관 DB 탐색 중 ({model_id})...")
        _t_stage = time.time()
        response = chat.send_message(user_input)
        raw_output = extract_safe_text(response)
        trace = _TOOL_TRACE.get()
        stage_secs = [("1차 답변+도구조회", time.time() - _t_stage)]

        tool_res_chars = sum(len(x) for x in trace["list"]) + sum(len(x) for x in trace["detail"])
        tool_call_cnt = sum(trace["counts"].values())
        _extract_and_log_response_usage(
            response, model_id, count_call=True,
            est_in_chars=len(user_input) + len(dynamic_prompt),
            est_out_chars=len(raw_output),
            tool_calls_count=tool_call_cnt,
            tool_result_chars=tool_res_chars
        )

        if not raw_output:
            _t_stage = time.time()
            follow_up = chat.send_message(
                "지금까지 조회한 법령 조문과 계산 결과를 바탕으로 추가 도구 호출 없이 즉시 <precheck> 3단 크로스체크(최소 200자 이상)를 먼저 작성한 뒤 [1. 결론 -> 2. 내용 -> 3. 관련법령] 순서로 답변을 작성해 주세요."
            )
            raw_output = extract_safe_text(follow_up)
            _extract_and_log_response_usage(follow_up, model_id, count_call=False, est_in_chars=500, est_out_chars=len(raw_output))
            stage_secs.append(("빈 응답 재요청", time.time() - _t_stage))
    finally:
        _TOOL_TRACE.reset(trace_token)

    if not raw_output:
        raise ValueError("빈 응답이 반환되었습니다.")

    stripped_body, precheck_text = _extract_and_strip_precheck(raw_output)
    is_formal_report = bool(re.search(r"###\s*1\.\s*결론|###\s*2\.\s*내용|###\s*3\.\s*관련법령", stripped_body))

    if is_formal_report and not _is_precheck_thorough(precheck_text):
        print(f"[시스템] ⚠️ 사전 3단 크로스체크 누락/부실 감지({len(precheck_text)}자) → 정밀 3단 체크 후 재작성 강제")
        enforce_precheck_msg = (
            "방금 답변에서 `<precheck> ... </precheck>` 사전 3단 크로스체크가 누락되었거나 너무 간략하게 작성되었습니다. "
            "결론을 내리기 전에 반드시 `<precheck>` 태그 안에 ① [1단: 법령·판례 원문 및 최근 개정·귀속시기·일몰 대조], "
            "② [2단: 단서·배제 요건 및 연쇄 세목(농특세·소득처분) 정밀 점검], ③ [3단: 수리 계산식·지방소득세·가산세 감면율 최종 검산]을 "
            "구체적인 조문 번호와 수치로 최소 200자 이상 꼼꼼히 먼저 작성한 뒤, "
            "그 검증 결과를 반영하여 `### 1. 결론`부터 `### 3. 관련법령`까지 전체 보고서를 다시 작성하세요."
        )
        trace_token_p = _TOOL_TRACE.set(trace)
        try:
            _t_stage = time.time()
            p_resp = chat.send_message(enforce_precheck_msg)
            stage_secs.append(("precheck 재작성", time.time() - _t_stage))
            p_raw = extract_safe_text(p_resp)
            _extract_and_log_response_usage(p_resp, model_id, count_call=False, est_in_chars=len(enforce_precheck_msg), est_out_chars=len(p_raw))
            if p_raw:
                s_body2, p_text2 = _extract_and_strip_precheck(p_raw)
                if _is_valid_report_body(s_body2):
                    raw_output = p_raw
                    stripped_body = s_body2
                    if p_text2:
                        precheck_text = p_text2
                    response = p_resp
                elif p_text2 and not precheck_text:
                    precheck_text = p_text2
        except Exception as e:
            print(f"[시스템]    ↳ 3단 크로스체크 재작성 호출 오류: {e}")
        finally:
            _TOOL_TRACE.reset(trace_token_p)

    if precheck_text:
        print(f"\n[시스템] 🛡️ 사전 3단 크로스체크 정밀 수행 완료 ({len(precheck_text):,}자):\n{precheck_text}")

    # [Stage 4 방어벽] 시점 인식 오류(2025년을 현재로 착각하거나 2026.1.1 시행 규정을 미시행 유예로 서술) 자동 스캔 및 강제 재작성
    timeline_errs = _scan_timeline_hallucinations(stripped_body, raw_query or user_input, full_user_input=user_input)
    if timeline_errs:
        _kst_fix = get_kst_today_context()
        print(f"[시스템] 🚨 시점/귀속연도 오인식 감지({len(timeline_errs)}건) → 즉시 교정 재작성 강제: {timeline_errs}")
        _emit_live_status("🚨 3단계: 시점·시행일 인식 오류 자동 감지 → 기준시점 즉시 교정 중...")
        timeline_fix_msg = (
            f"🚨 [시점·귀속연도 인식 오류 긴급 교정 명령]\n"
            f"방금 작성한 답변에서 다음과 같은 시점 오인식 오류가 감지되었습니다:\n- "
            + "\n- ".join(timeline_errs)
            + f"\n\n[절대 교정 기준]\n"
            f"1. 오늘 날짜는 **{_kst_fix['dot_full']}**이며, 현재 당해 연도는 {_kst_fix['prev_year']}년이 아니라 **{_kst_fix['year']}년({_kst_fix['year']}년 귀속)**입니다!\n"
            f"2. 법령·부칙의 **'{_kst_fix['year']}년 1월 1일 이후 시행/적용'** 규정은 올해({_kst_fix['year']}년) 이미 시행 중인 현행 규정이며, "
            f"반대로 이미 개정·공포되었더라도 **'{_kst_fix['next_year']}년 1월 1일 이후 시행/적용'**되는 규정은 오늘({_kst_fix['dot_full']}) 기준 **아직 시행일이 도래하지 않은 미시행(내년 시행예정) 규정**이므로 올해({_kst_fix['year']}년 귀속)에 지금부터 적용받는 것처럼 서술하면 절대 안 됩니다!\n"
            f"3. 질문의 귀속연도·거래시점 기준을 위 원칙에 맞게 바로잡아 `<precheck>`부터 `### 1. 결론` ~ `### 3. 관련법령` 전체를 즉시 다시 작성하세요."
        )
        trace_token_t = _TOOL_TRACE.set(trace)
        try:
            _t_stage = time.time()
            t_resp = chat.send_message(timeline_fix_msg)
            stage_secs.append(("시점오류 자동교정", time.time() - _t_stage))
            t_raw = extract_safe_text(t_resp)
            _extract_and_log_response_usage(t_resp, model_id, count_call=False, est_in_chars=len(timeline_fix_msg), est_out_chars=len(t_raw))
            if t_raw:
                t_body, t_pre = _extract_and_strip_precheck(t_raw)
                if _is_valid_report_body(t_body):
                    raw_output = t_raw
                    stripped_body = t_body
                    if t_pre:
                        precheck_text = t_pre
                    response = t_resp
        except Exception as e:
            print(f"[시스템]    ↳ 시점 오류 교정 재작성 호출 오류: {e}")
        finally:
            _TOOL_TRACE.reset(trace_token_t)

    final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", stripped_body)
    final_text = _clean_latex_for_export(final_text)

    citation_note = ""

    if is_formal_report and trace is not None:
        _emit_live_status("🛡️ 3단계: 미조회 근거 강제 차단(_scan_violations) 검증 중...")
        violations = _scan_violations(final_text, trace)
        if violations:
            has_body_violation = any(not in_refs for _, _, in_refs in violations)
            first_labels = _violation_labels(violations)

            patched_ok = False
            if has_body_violation:
                print(f"[시스템] 🔒 본문 미검증 근거 {len(first_labels)}건 감지 → 해당 줄만 부분 수정 요청: {first_labels[:8]}")
                _t_stage = time.time()
                final_text, patched_ok = _patch_violation_lines(chat, final_text, violations, trace, model_id)
                stage_secs.append(("미검증 근거 부분 수정" if patched_ok else "부분 수정 시도(실패)", time.time() - _t_stage))

            if has_body_violation and not patched_ok:
                print(f"[시스템] 🔒 본문 미검증 근거 {len(first_labels)}건 → 전체 재작성 요청: {first_labels[:8]}")
                fix_msg = (
                    "방금 답변에서 도구 조회 기록으로 확인되지 않는 근거가 발견되었습니다:\n- "
                    + "\n- ".join(first_labels[:15])
                    + "\n\n각 항목에 대해 ① get_law_details_for_gemini로 원문(판결요지·조문)을 조회해 확인한 뒤 근거 표시"
                      "([판례:사건번호], [조문:정식법령명 제N조], [예규:문서명] 등)를 붙여 인용하거나, "
                      "② 조회할 수 없으면 그 근거와 관련 서술을 답변에서 완전히 삭제하세요. "
                      "'대법원은 ~ 판시' 같은 서술에도 반드시 근거 표시가 있어야 합니다. "
                      "조회하지 않은 근거는 다시 쓰지 말고, `<precheck>` 3단 크로스체크와 양식(1. 결론 → 2. 내용 → 3. 관련법령)을 유지해 전체 답변을 다시 작성하세요. "
                      "다시 쓴 답변에는 이 검증 요청이나 삭제 사실, 시스템에 대한 언급을 절대 넣지 마세요."
                )
                trace_token2 = _TOOL_TRACE.set(trace)
                _t_stage = time.time()
                try:
                    retry_resp = chat.send_message(fix_msg)
                    retry_text = extract_safe_text(retry_resp)
                    _extract_and_log_response_usage(retry_resp, model_id, count_call=False, est_in_chars=len(fix_msg), est_out_chars=len(retry_text))
                except Exception as e:
                    retry_text = ""
                    print(f"[시스템]    ↳ 재작성 요청 실패: {e}")
                finally:
                    _TOOL_TRACE.reset(trace_token2)
                    stage_secs.append(("미검증 근거 전체 재작성", time.time() - _t_stage))

                if retry_text:
                    retry_body, retry_precheck = _extract_and_strip_precheck(retry_text)
                    if _is_valid_report_body(retry_body):
                        if retry_precheck:
                            precheck_text = retry_precheck
                        final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", retry_body)
                        final_text = _clean_latex_for_export(final_text)
                        response = retry_resp

            remaining = _scan_violations(final_text, trace)
            if remaining:
                final_text = _redact_lines(final_text, remaining)
                short = [r.split(":")[0] if r.startswith(("출처 표시 없는", "판례 인용문")) else r for r in _violation_labels(remaining)]
                short = list(dict.fromkeys(short))
                citation_note = (f"\n> 🚫 미검증 근거 후처리({_verify_mode()} 모드): "
                                 + "; ".join(short[:10]))
            else:
                citation_note = ("\n> 🔒 미검증 근거가 감지되어 "
                                 + ("**해당 줄만 수정**" if patched_ok else "**재작성**")
                                 + "(원문 조회 또는 삭제)했습니다. (최초 감지 " + str(len(first_labels)) + "건)")
        else:
            citation_note = "\n> ✅ 답변의 판례·조문·예규 근거가 모두 이번 조회 기록과 일치합니다."

        if SEMANTIC_VERIFY_ON and (trace["list"] or trace["detail"]):
            claims, sources = _extract_claims(final_text, trace)
            if claims:
                print(f"[시스템] 🧪 의미 검증 가동: 주장 {len(claims)}건 / 원문 {len(sources)}건")
                _t_stage = time.time()
                try:
                    verdicts = _semantic_verify(api_key, claims, sources, raw_query or user_input, full_user_input=user_input)
                    final_text, cnt = _apply_semantic_results(final_text, claims, verdicts, sources)
                    citation_note += (f"\n> 🧪 의미 검증 {len(claims)}건: 일치 {cnt['supported']} · "
                                      f"원문 확인 필요 {cnt['partial']} · 불일치 {cnt['unsupported']}"
                                      + (f" · 판정 누락 {cnt['unknown']}" if cnt.get("unknown") else ""))
                    v_info = get_last_verify_info()
                    if v_info.get("model"):
                        citation_note += (f" (검증 모델 {v_info['model']} · {v_info.get('cfg') or '-'}"
                                          + (f" · 실패 후 넘어감: {', '.join(v_info['failed'])}" if v_info.get("failed") else "")
                                          + ")")
                except Exception as e:
                    print(f"[시스템]    ↳ 의미 검증 실패: {e}")
                    citation_note += "\n> 🧪 의미 검증을 수행하지 못했습니다(검증 모델 오류). 근거 표시 문장은 직접 확인하세요."
                stage_secs.append(("의미 검증", time.time() - _t_stage))

        final_text = _inject_direct_law_links(final_text, trace)

    elif trace is not None:
        final_text = _strip_fake_cases_in_track2(final_text, trace, user_input)

    history = []
    try:
        history = chat.get_history(curated=False) or []
    except Exception:
        pass
    if not history:
        history = getattr(response, "automatic_function_calling_history", None) or []

    calls = []
    for c in history:
        for p in (getattr(c, "parts", None) or []):
            fc = getattr(p, "function_call", None)
            if fc and getattr(fc, "name", None):
                args = ", ".join(f"{k}={v}" for k, v in (fc.args or {}).items())
                calls.append(f"{fc.name}({args})")

    limit_hit = False
    try:
        for p in (response.candidates[0].content.parts or []):
            if getattr(p, "function_call", None):
                limit_hit = True
    except Exception:
        pass

    if calls:
        diag = "\n\n---\n> 🛠 도구 호출 " + str(len(calls)) + "회: " + " → ".join(calls)
    else:
        diag = "\n\n---\n> 🛠 도구 호출 없음 (자유 대화 / 자체 지식 답변)"
    if limit_hit:
        diag += "\n> ⚠️ 도구 호출 한도에 도달해 조회가 중간에 끊겼습니다. 결론을 원문과 대조해 확인하세요."
    diag += citation_note
    if stage_secs:
        diag += "\n> ⏱ 단계별 소요: " + " · ".join(f"{nm} {sec:.0f}초" for nm, sec in stage_secs)

    if _show_diag():
        final_text += diag
    else:
        print("[시스템] 📋 진단 정보(화면 미표시):" + diag.replace("\n> ", "\n   ").replace("\n\n---", ""))
    final_text = re.sub(r"\s*<br\s*/?>\s*", " / ", final_text)

    return _strip_leaked_temporal_guideline(_clean_latex_for_export(final_text)), len(precheck_text)

# 4. 실행 순서(유료키 전용):
#    - Flash 모드: gemini-3.8-flash → gemini-3.6-flash → gemini-3.5-flash-lite → gemini-2.5-flash
#    - Pro 심층 모드(1번 아르곤 직결): gemini-4-argon → gemini-3.1-pro-preview-customtools → gemini-3.1-pro-preview → gemini-2.5-pro

# ---------------------------------------------------------
# 🌐 일반 모드 (법령 검색 모드 OFF): 법령 도구·precheck·근거 검증 없이 Gemini + Google 웹 검색으로 자유 답변
# - app.py가 질문 앞에 "[일반]" 표시를 붙여 넘기면 run_agent가 이 경로로 보냅니다.
# - 화면 노출 여부는 Secrets의 ENABLE_GENERAL_MODE = "on" 으로 정합니다(없으면 기존 화면 그대로).
# ---------------------------------------------------------
GENERAL_MODE_TAG = "[일반]"

GENERAL_SYSTEM_PROMPT = (
    "당신은 유능한 한국어 AI 어시스턴트입니다. 질문에 맞춰 자유롭게 추론하고 답하세요. "
    "최신 정보·사실 확인이 필요하면 Google 검색을 활용하고, 검색으로 확인한 내용은 출처를 함께 밝히세요. "
    "이전 대화 맥락이 함께 주어지면 이어서 답하세요. "
    "세무·법률 판단이 핵심인 질문이라면 답변 끝에 '정확한 법령 근거 확인은 법령 검색 모드를 켜고 다시 질문하세요'라고 한 줄 안내하세요."
)

def is_general_mode_enabled() -> bool:
    return _secret_on("ENABLE_GENERAL_MODE")

def _is_general_request(raw_query: str, user_input: str) -> bool:
    if not is_general_mode_enabled():
        return False
    rq = (raw_query or "").lstrip()
    return rq.startswith(GENERAL_MODE_TAG) or f"[현재 사용자 질문]: {GENERAL_MODE_TAG}" in (user_input or "")

def _strip_general_tag(text: str) -> str:
    return (text or "").replace(f"[현재 사용자 질문]: {GENERAL_MODE_TAG}", "[현재 사용자 질문]:").replace(GENERAL_MODE_TAG, "", 1).strip()

def _grounding_sources_md(resp) -> str:
    """Google 검색 근거(grounding_metadata)의 웹 출처를 마크다운 목록으로 반환합니다."""
    try:
        gm = resp.candidates[0].grounding_metadata
    except Exception:
        gm = None
    if not gm:
        return ""
    seen, rows = set(), []
    for ch in (getattr(gm, "grounding_chunks", None) or []):
        web = getattr(ch, "web", None)
        uri = getattr(web, "uri", "") if web else ""
        if uri and uri not in seen:
            seen.add(uri)
            title = (getattr(web, "title", "") or uri).replace("[", "(").replace("]", ")")
            rows.append(f"- [{title}]({uri})")
    queries = [q for q in (getattr(gm, "web_search_queries", None) or []) if q]
    out = ""
    if rows:
        out += "\n\n---\n**🔎 참고한 웹 출처**\n" + "\n".join(rows[:10])
    if queries and _show_diag():
        out += "\n> 🔍 검색어: " + " · ".join(queries[:6])
    return out

def run_general_agent(user_input: str, raw_query: str = "", has_file: bool = False, room_key: str = "", status_callback=None) -> str:
    _t_run = time.time()
    live_pool = get_live_gemini_key_pool()
    if not live_pool:
        return "❌ 설정된 Gemini 유료 API 키가 없습니다. .env 또는 Streamlit Secrets에 GEMINI_PAID_KEY를 넣어 주세요."
    clean_input = _strip_general_tag(user_input)
    clean_query = _strip_general_tag(raw_query) if raw_query else clean_input
    rk_token = set_active_room_key(room_key) if room_key else None
    cb_token = set_live_status_callback(status_callback) if status_callback else None
    try:
        tier_mode, _, notice = select_optimal_model(user_query=clean_query, has_file=has_file, full_input_len=len(clean_input))
        is_pro = (tier_mode == "PRO")
        if is_pro:
            live_pool = get_pro_key_pool()
        flash_candidates = _get_flash_candidates()
        models = (_skip_slow_models(list(dict.fromkeys(PAID_PRO_MODEL_IDS))) + flash_candidates) if is_pro else flash_candidates
        prompt_text = clean_input.replace("[현재 사용자 질문]: [프로]", "[현재 사용자 질문]:", 1)
        if prompt_text.lstrip().startswith("[프로]"):
            prompt_text = prompt_text.replace("[프로]", "", 1).strip()
        prompt_text = ensure_hidden_date_directive_in_input(prompt_text, clean_query)
        _kst_gen = get_kst_today_context()
        _gen_sys = (
            f"[시스템 기준일 안내: 오늘은 {_kst_gen['dot_full']}이며, 현재 당해 연도는 {_kst_gen['year']}년({_kst_gen['year']}년 귀속)입니다. "
            f"질문에 별도 과거 연도 지정이 없으면 반드시 오늘({_kst_gen['dot_full']}) 및 {_kst_gen['year']}년 최신 기준으로 답변하세요.]\n\n"
            + GENERAL_SYSTEM_PROMPT
        )
        cfg = types.GenerateContentConfig(
            system_instruction=_gen_sys,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            max_output_tokens=32768 if is_pro else 16384,
        )
        diag_notes, last_error = [], None
        for key_label, current_key in live_pool:
            for model_id in models:
                _t_try = time.time()
                try:
                    _emit_live_status(f"🌐 일반 모드: Gemini 추론 + 웹 검색 중 ({model_id})...")
                    client = make_genai_client(current_key, 180000 if is_pro else 120000)
                    resp = client.models.generate_content(model=model_id, contents=prompt_text, config=cfg)
                    text = extract_safe_text(resp)
                    if not text:
                        raise ValueError("빈 응답이 반환되었습니다.")
                    _extract_and_log_response_usage(resp, model_id, count_call=True,
                                                    est_in_chars=len(prompt_text) + len(GENERAL_SYSTEM_PROMPT),
                                                    est_out_chars=len(text))
                    badge = ("👑 **[Pro 일반 모드 · 웹 검색]**" if is_pro else "🌐 **[일반 모드 · 웹 검색]**") + f" *(🔑 {key_label} · {model_id})*"
                    header = f"> {badge}"
                    if _show_diag():
                        header += f" ⏱ 전체 {time.time() - _t_run:.0f}초 (이번 성공 시도 {time.time() - _t_try:.0f}초)"
                    header += "\n"
                    if notice:
                        header += notice
                    if diag_notes and _show_diag():
                        header += f"> *(ℹ️ 앞선 시도 실패: {' | '.join(diag_notes)})*\n"
                    return header + "\n" + _strip_leaked_temporal_guideline(text) + _grounding_sources_md(resp)
                except Exception as e:
                    last_error = e
                    if _is_slow_error(e):
                        _mark_slow_model(model_id)
                    m_code = re.search(r"\b(4\d\d|5\d\d)\b", str(e))
                    err_short = m_code.group(1) if m_code else str(e).splitlines()[0][:40]
                    diag_notes.append(f"{key_label}({model_id}): {err_short} · {time.time() - _t_try:.0f}초")
                    continue
        return f"❌ 모든 API 키 호출이 실패했습니다. 마지막 오류: {str(last_error)}"
    finally:
        if cb_token is not None:
            _LIVE_STATUS_CB.reset(cb_token)
        if rk_token is not None:
            _ACTIVE_ROOM_KEY.reset(rk_token)

def run_agent(user_input: str, raw_query: str = "", has_file: bool = False, room_key: str = "", status_callback=None) -> str:
    if _is_general_request(raw_query, user_input):
        return run_general_agent(user_input, raw_query, has_file, room_key, status_callback)
    _t_run = time.time()
    live_pool = get_live_gemini_key_pool()
    if not live_pool:
        return "❌ 설정된 Gemini 유료 API 키가 없습니다. .env 또는 Streamlit Secrets에 GEMINI_PAID_KEY를 넣어 주세요."

    rk_token = set_active_room_key(room_key) if room_key else None
    cb_token = set_live_status_callback(status_callback) if status_callback else None
    try:
        query_for_routing = raw_query if raw_query else user_input
        tier_mode, mode_badge, recommend_pro_notice = select_optimal_model(
            user_query=query_for_routing,
            has_file=has_file,
            full_input_len=len(user_input)
        )
        unleash_mode = (tier_mode == "PRO")
        if unleash_mode:
            live_pool = get_pro_key_pool()

        _kst_now = get_kst_today_context()
        today_str = _kst_now["kr_full"]
        today_dot = _kst_now["dot_full"]
        cur_yr = _kst_now["year"]
        prev_yr = _kst_now["prev_year"]
        user_input = ensure_hidden_date_directive_in_input(user_input, query_for_routing)
        _q_yr_info = detect_query_attribution_years(query_for_routing, full_user_input=user_input)
        unleash_guide = (
            "\n[🚀 PRO/ARGON 3배 리미트 해제 모드 가동 중: 법령 검색 최대 21회, 원문 조회 최대 36회, 판례·심판례·예규 조회 최대 6~9회, "
            "원문 길이 최대 60,000자까지 한도가 3배 확장되었습니다. 관련 법령 조문과 판례·예규의 구체적 사실관계(이유)까지 빠짐없이 깊이 있게 대조하여 작성하세요.]\n"
            if unleash_mode else ""
        )
        if _q_yr_info["mode"] == "PAST_ONLY":
            _p_str = ", ".join(f"{y}년" for y in _q_yr_info["past_years"])
            _f_past = _q_yr_info["past_years"][0]
            _sys_yr_header = (
                f"[시스템 기준일 및 과거 귀속연도({_p_str}) 보호 원칙: 오늘은 {today_dot} ({today_str})이나, "
                f"이번 질문은 사용자가 **과거 귀속연도({_p_str})**를 직접 지정한 질의입니다! "
                f"절대 {cur_yr}년 최신 개정 세법을 소급 적용하여 답하지 말고, 반드시 `search_historical_law_for_gemini(law_name, target_date=\"{_f_past}1231\", ...)` 도구와 부칙 경과조치를 통해 **{_p_str} 과세기간 당시 시행 구법(종전 규정)**으로 결론과 계산을 도출하세요.]"
            )
        elif _q_yr_info["mode"] == "MIXED_PAST_AND_CURRENT":
            _p_str = ", ".join(f"{y}년" for y in _q_yr_info["past_years"])
            _sys_yr_header = (
                f"[시스템 기준일 및 복합 귀속연도({_p_str} vs {cur_yr}년) 분리 원칙: 오늘은 {today_dot} ({today_str})이며, "
                f"이번 질문은 과거 연도({_p_str})와 당해 연도({cur_yr}년)가 함께 등장하는 질의입니다. "
                f"과거({_p_str}) 발생분은 구법 타임머신(`search_historical_law_for_gemini`) 및 부칙 경과조치(종전 규정)로 판단하고, {cur_yr}년 당해 연도분은 현행 개정 세법으로 분리하여 절대 섞이지 않게 판단하세요.]"
            )
        else:
            _sys_yr_header = (
                f"[시스템 기준일 및 귀속연도 최우선 원칙: 오늘은 {today_dot} ({today_str})이며, 현재 당해 과세연도(귀속연도)는 {cur_yr}년({cur_yr}년 귀속)입니다. "
                f"① 이번 질문에는 특정 과거 연도가 명시되지 않았으므로 과거('{prev_yr}년 귀속' 등)가 아니라 반드시 당해 연도('{cur_yr}년 귀속') 및 오늘({today_dot}) 현재 시행 중인 최신 개정 세법·시행령을 최우선 기준으로 판단하세요. "
                f"② 단, 직전 대화 맥락이 과거 귀속 사안이거나 법령 부칙(적용례·경과조치)상 종전 규정이 적용되는 사안은 부칙 경과조치에 따라 종전 규정과 현행 개정 규정을 엄격히 구분하여 왜곡 없이 판단하세요.]"
            )
        dynamic_prompt = f"{_sys_yr_header}{unleash_guide}\n\n" + SYSTEM_PROMPT

        tools_list = [
            search_law_for_gemini,
            get_law_details_for_gemini,
            search_historical_law_for_gemini,
            search_exchange_rate_for_gemini,
            search_base_rate_for_gemini,
            search_industry_code_for_gemini,
            search_dart_corp_for_gemini,
            check_nts_biz_status_for_gemini,
            verify_nts_biz_info_for_gemini,
            search_real_estate_trade_for_gemini,
            search_real_estate_rent_for_gemini,
            search_official_land_price_for_gemini,
            search_building_ledger_for_gemini,
            search_comwel_workplace_for_gemini,
            search_nps_workplace_for_gemini,
            search_customs_exchange_rate_for_gemini,
            search_bizinfo_support_for_gemini,
            run_tax_calculator_for_gemini
        ]

        safety_settings = [
            types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
            types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        ]

        flash_candidates = _get_flash_candidates()
        execution_plan = []
        for lbl, k in live_pool:
            if tier_mode == "PRO":
                for m in _skip_slow_models(list(dict.fromkeys(PAID_PRO_MODEL_IDS))):
                    execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))
                for m in flash_candidates:
                    execution_plan.append((lbl, k, m, f"⚡ **[Pro 실패 → Flash 백업 (3배 리미트 개방 유지)]** *(🔑 {lbl} · {m})*"))
            else:
                for m in flash_candidates:
                    execution_plan.append((lbl, k, m, f"{mode_badge} *(🔑 {lbl} · {m})*"))

        last_error = None
        diag_notes = []
        dead_models = set()

        for key_label, current_key, target_model, final_badge in execution_plan:
            if target_model in dead_models:
                continue
            for attempt in range(2):
                _t_try = time.time()
                try:
                    final_text, precheck_len = _execute_with_key_and_model(
                        api_key=current_key,
                        model_id=target_model,
                        user_input=user_input,
                        dynamic_prompt=dynamic_prompt,
                        tools_list=tools_list,
                        safety_settings=safety_settings,
                        unleash=unleash_mode,
                        raw_query=query_for_routing
                    )
                    precheck_badge = f" · 🛡️ **3단 크로스체크 완료({precheck_len:,}자 검증)**" if precheck_len > 0 else ""
                    diag_header = f"> {final_badge}{precheck_badge}\n"
                    if _show_diag():
                        diag_header += f"> ⏱ 전체 {time.time() - _t_run:.0f}초 (이번 성공 시도 {time.time() - _t_try:.0f}초)\n"
                    if recommend_pro_notice:
                        diag_header += recommend_pro_notice
                    if diag_notes:
                        if _show_diag():
                            diag_header += f"> *(ℹ️ 앞선 시도 실패: {' | '.join(diag_notes)})*\n"
                        else:
                            print("[시스템] ℹ️ 앞선 시도 실패: " + " | ".join(diag_notes))
                    return diag_header + "\n" + final_text
                except Exception as e:
                    if _is_model_not_found(e):
                        dead_models.add(target_model)
                    if _is_slow_error(e):
                        _mark_slow_model(target_model)
                    m_code = re.search(r"\b(4\d\d|5\d\d)\b", str(e))
                    err_short = m_code.group(1) if m_code else str(e).splitlines()[0][:40]
                    retry_tag = "(재시도)" if attempt == 1 else ""
                    diag_notes.append(f"{key_label}({target_model}){retry_tag}: {err_short} · {time.time() - _t_try:.0f}초")
                    last_error = e
                    if attempt == 0 and err_short in ("500", "503"):
                        time.sleep(1.5)
                        continue
                    break

        return f"❌ 모든 API 키 호출이 실패했습니다. 마지막 오류: {str(last_error)}"
    finally:
        if cb_token is not None:
            _LIVE_STATUS_CB.reset(cb_token)
        if rk_token is not None:
            _ACTIVE_ROOM_KEY.reset(rk_token)


# ---------------------------------------------------------
# [보안] LLM 도구 함수(*_for_gemini) 출력의 API 키 마스킹
#  도구 결과는 LLM 입력·대화 기록·화면으로 그대로 흘러가므로, 외부 API 오류 문자열에 섞인 키를 반드시 가립니다.
#  functools.wraps로 이름·문서·시그니처(__wrapped__)를 보존하므로 Gemini 함수 선언 자동 생성과 호환됩니다.
# ---------------------------------------------------------
def _redact_tool_output(fn):
    import functools

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        try:
            res = fn(*args, **kwargs)
        except Exception as e:
            return f"❌ 도구 실행 오류: {law_api.safe_error(e)}"
        return law_api.redact_secrets(res) if isinstance(res, str) else res
    _wrapped.__redacting__ = True
    return _wrapped


for _tool_name, _tool_fn in list(globals().items()):
    if _tool_name.endswith("_for_gemini") and callable(_tool_fn) and getattr(_tool_fn, "__module__", "") == __name__ \
            and not getattr(_tool_fn, "__redacting__", False):
        globals()[_tool_name] = _redact_tool_output(_tool_fn)
del _tool_name, _tool_fn
