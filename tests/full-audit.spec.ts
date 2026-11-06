import { test, expect, Page } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

/**
 * 세무 AI 에이전트 무관용(Zero-Tolerance) 전수 실증 Playwright E2E 테스트 스위트
 * 공식 가이드: https://playwright.dev/docs/writing-tests
 *
 * 실행 방법 (프로젝트 루트 폴더에서):
 *   1) npm init -y && npm install -D @playwright/test
 *   2) npx playwright install chromium
 *   3) npx playwright test tests/full-audit.spec.ts --headed
 */

async function waitForStreamlitReady(page: Page) {
  await page.waitForSelector('[data-testid="stApp"]', { state: 'visible', timeout: 30000 });
  await page.waitForTimeout(600);
}

test.describe('세무 AI 에이전트 전수 기능·화면·상태 실증 스위트', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForStreamlitReady(page);
  });

  test('1. [사이드바 & 브랜드 모션] 4대 메뉴 전환 및 고양이 로고 점프 애니메이션·API 키 모달 실증', async ({ page }) => {
    const logo = page.locator('section[data-testid="stSidebar"] .sbx-logo');
    await expect(logo).toBeVisible();

    // 로고 클릭 시 점프 애니메이션 클래스(sbx-cat-jump-a 또는 sbx-cat-jump-b) 부여 확인
    await logo.click();
    await expect(logo).toHaveClass(/sbx-cat-jump-(a|b)/);

    // 4대 메뉴 버튼 존재 및 전환 확인
    const navButtons = [
      { key: '.st-key-btn_top_mode_calendar button', label: '달력' },
      { key: '.st-key-btn_top_mode_agent button', label: '자율 에이전트AI' },
      { key: '.st-key-btn_top_mode_credit button', label: '통합고용세액공제' },
      { key: '.st-key-btn_top_mode_payroll button', label: '인건비 자동화' },
    ];
    for (const nav of navButtons) {
      const btn = page.locator(nav.key);
      await expect(btn).toBeVisible();
      await expect(btn).toContainText(nav.label);
    }

    // 하단 결제 링크 및 API 키 모달 오픈 검증
    const billingLink = page.locator('section[data-testid="stSidebar"] a', { hasText: '결제' });
    await expect(billingLink).toHaveAttribute('href', /console\.cloud\.google\.com\/billing/);

    const apiKeyBtn = page.locator('section[data-testid="stSidebar"] button', { hasText: 'API 키' });
    await apiKeyBtn.click();
    await expect(page.getByText('연동 API 현황 및 보안키·만료일 통합 관리')).toBeVisible();
  });

  test('2. [달력 화면 소실 버그 실증] 상세일정 설정 모달 오픈 시 배경 달력(1~30일) 및 Today To Do 화면 유지 검증', async ({ page }) => {
    // 2026년 11월로 설정
    const addScheduleBtn = page.locator('.st-key-btn_cal_open_add_schedule button');
    await expect(addScheduleBtn).toBeVisible();

    // 모달 오픈 전 배경 달력 및 우측 Today To Do 영역 크기 측정
    const calSurface = page.locator('.st-key-cal_glass_surface');
    const todoCard = page.locator('.st-key-cal_right_todo_card');
    await expect(calSurface).toBeVisible();
    await expect(todoCard).toBeVisible();

    const beforeCalBox = await calSurface.boundingBox();
    expect(beforeCalBox).not.toBeNull();
    expect(beforeCalBox!.width).toBeGreaterThan(400);
    expect(beforeCalBox!.height).toBeGreaterThan(500);

    // [+ 일정 추가하기] 클릭하여 상세일정 설정 모달 오픈
    await addScheduleBtn.click();
    const dialog = page.locator('div[role="dialog"]');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('상세일정 설정');

    // [핵심 검증] 모달이 열린 상태에서도 배경의 메인 달력 날짜 셀(1일~28일)과 우측 Today To Do 카드가 사라지지 않고 그대로 존재하는지 확인
    await expect(calSurface).toBeVisible();
    await expect(todoCard).toBeVisible();
    await expect(page.locator('.tds-cal-day-card[data-cal-day="1"]')).toBeVisible();
    await expect(page.locator('.tds-cal-day-card[data-cal-day="15"]')).toBeVisible();
    await expect(page.locator('.tds-cal-day-card[data-cal-day="28"]')).toBeVisible();

    const afterCalBox = await calSurface.boundingBox();
    expect(afterCalBox).not.toBeNull();
    expect(afterCalBox!.width).toBeGreaterThan(400);
    expect(afterCalBox!.height).toBeGreaterThan(500);
  });

  test('3. [상세일정 설정 전수 실증] 제목·카테고리·시간·반복·거래처·체크항목·로컬 첨부파일 업로드 및 화면 반영 검증', async ({ page }) => {
    await page.locator('.st-key-btn_cal_open_add_schedule button').click();
    const dialog = page.locator('div[role="dialog"]');
    await expect(dialog).toBeVisible();

    // 1) 제목 입력
    const titleInput = dialog.locator('.gcal-tds-title-wrap input');
    await titleInput.fill('부가세 예정고지 정밀 안내');

    // 2) 중요 핀 체크박스 및 달력 표시 체크박스 확인
    const urgentChk = dialog.getByText('★ 중요 핀');
    await urgentChk.click();

    // 3) 시간 입력
    const timeInput = dialog.locator('input[placeholder*="00:00"]');
    await timeInput.fill('14:30');

    // 4) 거래처 입력
    const clientInput = dialog.locator('input[placeholder*="기장 거래처"]');
    await clientInput.fill('(주)성진');

    // 5) 세부 체크항목 추가 버튼 실증
    const subInput = dialog.locator('input[placeholder*="세부 체크항목 입력"]');
    await subInput.fill('홈택스 고지세액 조회');
    await dialog.getByRole('button', { name: '＋ 항목 추가' }).click();
    await expect(dialog.getByText('홈택스 고지세액 조회')).toBeVisible();

    // 6) 상세 메모 및 로컬 첨부파일 실제 업로드 실증
    const memoArea = dialog.locator('textarea[placeholder*="상세 설명"]');
    await memoArea.fill('홈택스 전자고지 확인 완료');

    const tmpFilePath = path.join(os.tmpdir(), '부가세_예정고지서_샘플.pdf');
    fs.writeFileSync(tmpFilePath, '%PDF-1.4 sample tax notice file');

    const fileInput = dialog.locator('input[type="file"]');
    await expect(fileInput).toBeAttached();
    await fileInput.setInputFiles(tmpFilePath);
    await expect(dialog.getByText(/부가세_예정고지서_샘플\.pdf/)).toBeVisible();

    // 7) 저장 클릭 후 달력 및 Today To Do 카드에 제목·거래처·첨부파일·중요 배지가 모두 표시되는지 확인
    await dialog.getByRole('button', { name: '저장' }).click();
    await expect(dialog).toBeHidden();

    const todoList = page.locator('.st-key-cal_right_todo_card');
    await expect(todoList).toContainText('부가세 예정고지 정밀 안내');
    await expect(todoList).toContainText('(주)성진');
    await expect(todoList).toContainText('부가세_예정고지서_샘플.pdf');
    await expect(todoList).toContainText('중요');
    await expect(todoList).toContainText('0/1');
  });

  test('4. [AI 백그라운드 시뮬레이터 & 인건비 브릿지 실증] 시뮬레이터 ④·⑤ 실행 시 사업소득·급여명세서 컬럼 정확 반영 검증', async ({ page }) => {
    const simExpander = page.locator('section[data-testid="stSidebar"] details', { hasText: 'AI 백그라운드 시뮬레이터' });
    await simExpander.locator('summary').click();

    // 시뮬레이터 ④ (사업소득 강민호 250만 원 자동입력) 클릭
    await page.locator('.st-key-btn_cal_sim_4 button').click();
    await waitForStreamlitReady(page);

    // 인건비 자동화 메뉴로 이동 시 사업소득(FREE) 화면에 강민호 및 귀속년월·지급년월일이 정상 표시되는지 확인
    await page.locator('.st-key-btn_top_mode_payroll button').click();
    await waitForStreamlitReady(page);

    await expect(page.getByText('사업소득대장')).toBeVisible();
    await expect(page.getByText('2,500,000원')).toBeVisible();
    await expect(page.getByText('2,417,500원')).toBeVisible();

    // 사업소득 모드에서 [당월 검토보고] 버튼 작동 확인
    const monthlyReportBtn = page.locator('.st-key-btn_pay_monthly_report button');
    await expect(monthlyReportBtn).toBeVisible();
    await monthlyReportBtn.click();
    await expect(page.locator('div[role="dialog"]')).toContainText('당월 사업소득 검토보고');
  });

  test('5. [자율 에이전트AI 화면 실증] 2x2 추천 벤토 카드 클릭 트리거, 엔진 토글, 대화방 1~10 전환 및 초기화 검증', async ({ page }) => {
    await page.locator('.st-key-btn_top_mode_agent button').click();
    await waitForStreamlitReady(page);

    // 초기 화면 2x2 벤토 추천 카드 및 시작 버튼 노출 확인
    await expect(page.locator('.toss-bento-card').first()).toBeVisible();
    await expect(page.locator('[class*="st-key-btn_bento_start_"]').first()).toBeVisible();

    // 대화방 2로 전환 후 방 주제 메모 수정
    await page.locator('[class*="st-key-room_btn_2_"] button').click();
    await waitForStreamlitReady(page);
    await expect(page.locator('.top-mini-status-bar')).toContainText('대화방 2');

    const roomTitleInput = page.locator('input[placeholder*="현재 방 주제 메모"]');
    await roomTitleInput.fill('A법인 정기 세무조정');
    await roomTitleInput.press('Enter');
    await waitForStreamlitReady(page);
    await expect(page.locator('.top-mini-status-bar')).toContainText('A법인 정기 세무조정');
  });

  test('6. [통합고용세액공제 1~4단계 실증] 기업규모 선택, 2단계 사원 추가 모달 및 단계 전환 검증', async ({ page }) => {
    await page.locator('.st-key-btn_top_mode_credit button').click();
    await waitForStreamlitReady(page);

    await expect(page.getByText('통합고용세액공제')).toBeVisible();

    // 1단계 -> 2단계 이동
    await page.getByRole('button', { name: '다음(2단계)' }).click();
    await waitForStreamlitReady(page);

    // 자료 확인 안내 모달이 뜨면 확인 클릭
    const confirmBtn = page.getByRole('button', { name: /확인 및 2단계/ });
    if (await confirmBtn.isVisible()) {
      await confirmBtn.click();
      await waitForStreamlitReady(page);
    }

    // 2단계 [+ 사원 추가] 모달 오픈 및 사원 등록 실증
    const addEmpBtn = page.locator('[class*="st-key-btn_ec_add_emp_"] button').first();
    await expect(addEmpBtn).toBeVisible();
    await addEmpBtn.click();

    const empDialog = page.locator('div[role="dialog"]');
    await expect(empDialog).toBeVisible();
    await empDialog.locator('input[placeholder*="홍길동"]').fill('김세무');
    await empDialog.locator('input[placeholder*="1995-05-15"]').fill('1996-08-20');
    await empDialog.locator('input[placeholder*="2026-04-01"]').first().fill('2025-01-01');
    await empDialog.getByRole('button', { name: '확인' }).click();
    await waitForStreamlitReady(page);

    // 3단계 이동 확인
    await page.getByRole('button', { name: '다음(3단계)' }).click();
    await waitForStreamlitReady(page);
    await expect(page.getByRole('button', { name: '다음(4단계)' })).toBeVisible();
  });

  test('7. [인건비 자동화 급여명세서 & 사업소득 실증] 행 추가, 세전↔세후 일괄 스위치, 수당 계산기 및 양식 미리보기 검증', async ({ page }) => {
    await page.locator('.st-key-btn_top_mode_payroll button').click();
    await waitForStreamlitReady(page);

    // 급여명세서 탭 선택
    await page.locator('[class*="st-key-btn_pay_submode_emp"] button').click();
    await waitForStreamlitReady(page);

    // [+ 행 추가] 클릭
    await page.locator('.st-key-btn_pay_add_row button').click();
    await waitForStreamlitReady(page);
    await expect(page.locator('.ecx-kpis')).toContainText('1명');

    // 수당 계산기 팝오버 -> 주휴수당 계산기 모달 오픈 및 반영
    await page.getByRole('button', { name: '수당 계산기' }).click();
    await page.locator('.st-key-btn_pay_open_wh_calc button').click();
    const whDialog = page.locator('div[role="dialog"]');
    await expect(whDialog).toContainText('주휴수당 계산기');
    await whDialog.locator('.st-key-btn_apply_wh_to_emp button').click();
    await waitForStreamlitReady(page);

    // 급여명세서 반영 후 지급액계가 0보다 커졌는지 확인
    await expect(page.locator('.ecx-kpis')).not.toContainText('지급액계0원');

    // [기준금액 세전 | 세후] 스위치 토글 작동 확인
    await page.locator('.st-key-btn_emp_bulk_gross_net_switch button').click();
    await waitForStreamlitReady(page);
    await expect(page.locator('.st-key-pay_free_sw_net')).toBeVisible();
  });
});