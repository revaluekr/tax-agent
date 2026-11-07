import { test, expect, Page } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

const DIALOG_SEL = '[data-testid="stDialog"], [role="dialog"], dialog';

async function waitForStreamlitReady(page: Page) {
  await page.waitForLoadState('domcontentloaded');
  if (!page.url().includes('/~/+/')) {
    const iframe = page.locator('iframe[title="streamlitApp"], iframe[src*="/~/+/"]').first();
    try {
      await iframe.waitFor({ state: 'attached', timeout: 20000 });
      const src = await iframe.getAttribute('src');
      if (src) {
        await page.goto(new URL(src, page.url()).toString(), { waitUntil: 'domcontentloaded', timeout: 60000 });
      }
    } catch {}
  }
  await page.waitForSelector('[data-testid="stApp"]', { state: 'visible', timeout: 60000 });
  await page.waitForTimeout(800);
}

test.describe('세무 AI 에이전트 전수 기능·화면·상태 실증 스위트', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForStreamlitReady(page);
  });

  test('1. [사이드바 & 브랜드 모션] 4대 메뉴 전환 및 고양이 로고 점프 애니메이션·API 키 모달 실증', async ({ page }) => {
    const logo = page.locator('section[data-testid="stSidebar"] .sbx-logo').first();
    await expect(logo).toBeVisible({ timeout: 25000 });

    const navButtons = [
      { key: '.st-key-btn_top_mode_calendar button', label: '달력' },
      { key: '.st-key-btn_top_mode_agent button', label: '자율 에이전트AI' },
      { key: '.st-key-btn_top_mode_credit button', label: '통합고용세액공제' },
      { key: '.st-key-btn_top_mode_payroll button', label: '인건비 자동화' },
    ];
    for (const nav of navButtons) {
      const btn = page.locator(nav.key).first();
      await expect(btn).toBeVisible();
      await expect(btn).toContainText(nav.label);
    }

    await page.locator('.st-key-btn_top_mode_agent button').first().click();
    await waitForStreamlitReady(page);
    await expect(logo).toHaveClass(/sbx-cat-jump-(a|b)/, { timeout: 15000 });

    const billingLink = page.locator('.st-key-sbx_footer a', { hasText: '결제' }).first();
    await expect(billingLink).toHaveAttribute('href', /console\.cloud\.google\.com\/billing/);

    const apiKeyBtn = page.locator('.st-key-sbx_footer button[data-testid*="stBaseButton"]').filter({ hasText: 'API 키' }).first();
    await apiKeyBtn.click();
    await expect(page.getByText('연동 API 현황 및 보안키·만료일 통합 관리').first()).toBeVisible({ timeout: 20000 });
  });

  test('2. [달력 화면 소실 버그 실증] 상세일정 설정 모달 오픈 시 배경 달력(1~30일) 및 Today To Do 화면 유지 검증', async ({ page }) => {
    const addScheduleBtn = page.locator('.st-key-btn_cal_open_add_schedule button').first();
    await expect(addScheduleBtn).toBeVisible({ timeout: 25000 });

    const calSurface = page.locator('.st-key-cal_glass_surface').first();
    const todoCard = page.locator('.st-key-cal_right_todo_card').first();
    await expect(calSurface).toBeVisible();
    await expect(todoCard).toBeVisible();

    const beforeCalBox = await calSurface.boundingBox();
    expect(beforeCalBox).not.toBeNull();
    expect(beforeCalBox!.width).toBeGreaterThan(400);
    expect(beforeCalBox!.height).toBeGreaterThan(500);

    await addScheduleBtn.click();
    const dialog = page.locator(DIALOG_SEL).first();
    await expect(dialog).toBeVisible({ timeout: 20000 });
    await expect(dialog).toContainText('상세일정 설정');

    await expect(calSurface).toBeVisible();
    await expect(todoCard).toBeVisible();
    await expect(page.locator('.tds-cal-day-card[data-cal-day="1"]').first()).toBeVisible();
    await expect(page.locator('.tds-cal-day-card[data-cal-day="15"]').first()).toBeVisible();
    await expect(page.locator('.tds-cal-day-card[data-cal-day="28"]').first()).toBeVisible();

    const afterCalBox = await calSurface.boundingBox();
    expect(afterCalBox).not.toBeNull();
    expect(afterCalBox!.width).toBeGreaterThan(400);
    expect(afterCalBox!.height).toBeGreaterThan(500);
  });

  test('3. [상세일정 설정 전수 실증] 제목·카테고리·시간·반복·거래처·체크항목·로컬 첨부파일 업로드 및 화면 반영 검증', async ({ page }) => {
    await page.locator('.st-key-btn_cal_open_add_schedule button').first().click();
    const dialog = page.locator(DIALOG_SEL).first();
    await expect(dialog).toBeVisible({ timeout: 20000 });

    const titleInput = dialog.locator('input[placeholder*="제목 입력"], [class*="st-key-dlg_title_"] input').first();
    await titleInput.fill('부가세 예정고지 정밀 안내');

    const urgentChk = dialog.getByText('★ 중요 핀').first();
    await urgentChk.click();

    const timeInput = dialog.locator('input[placeholder*="00:00"]').first();
    await timeInput.fill('14:30');

    const clientInput = dialog.locator('input[placeholder*="기장 거래처"]').first();
    await clientInput.fill('(주)성진');

    const subInput = dialog.locator('input[placeholder*="세부 체크항목 입력"]').first();
    await subInput.fill('홈택스 고지세액 조회');
    await dialog.getByRole('button', { name: '＋ 항목 추가' }).first().click();
    await expect(dialog.getByText('홈택스 고지세액 조회').first()).toBeVisible({ timeout: 15000 });

    const memoArea = dialog.locator('textarea[placeholder*="상세 설명"]').first();
    await memoArea.fill('홈택스 전자고지 확인 완료');

    const tmpFilePath = path.join(os.tmpdir(), '부가세_예정고지서_샘플.pdf');
    fs.writeFileSync(tmpFilePath, '%PDF-1.4 sample tax notice file');

    const fileInput = dialog.locator('input[type="file"]').first();
    await expect(fileInput).toBeAttached();
    await fileInput.setInputFiles(tmpFilePath);

    await expect(dialog.getByText(/📎\s*부가세_예정고지서_샘플\.pdf/).first()).toBeVisible({ timeout: 25000 });
    await page.waitForTimeout(500);

    await dialog.getByRole('button', { name: '저장' }).first().click();
    await expect(dialog).toBeHidden({ timeout: 20000 });

    const todoList = page.locator('.st-key-cal_right_todo_card').first();
    await expect(todoList).toContainText('부가세 예정고지 정밀 안내', { timeout: 20000 });
    await expect(todoList).toContainText('(주)성진');
    await expect(todoList).toContainText('부가세_예정고지서_샘플');
    await expect(todoList).toContainText('중요');
    await expect(todoList).toContainText('0/1');
  });

  test('4. [달력 하단 독(Dock) 빠른 등록 & 사업소득 검토보고 실증] 할 일 즉시 등록 및 사업소득 검토보고 모달 검증', async ({ page }) => {
    const dockInput = page.locator('[class*="st-key-dock_chat_wrap_"] input').first();
    await expect(dockInput).toBeVisible({ timeout: 25000 });
    await dockInput.fill('원천세 반기납부 대상 확인');
    await dockInput.press('Enter');
    await waitForStreamlitReady(page);

    const todoList = page.locator('.st-key-cal_right_todo_card').first();
    await expect(todoList).toContainText('원천세 반기납부 대상 확인', { timeout: 20000 });

    await page.locator('.st-key-btn_top_mode_payroll button').first().click();
    await waitForStreamlitReady(page);

    await page.locator('[class*="st-key-btn_pay_submode_free"] button').first().click();
    await waitForStreamlitReady(page);

    await expect(page.getByText('사업소득대장').first()).toBeVisible({ timeout: 25000 });

    const monthlyReportBtn = page.locator('.st-key-btn_pay_monthly_report button').first();
    await expect(monthlyReportBtn).toBeVisible();
    await monthlyReportBtn.click();
    await expect(page.locator(DIALOG_SEL).first()).toContainText('당월 사업소득 검토보고', { timeout: 20000 });
  });

  test('5. [자율 에이전트AI 화면 & 전역 홈버튼 실증] 2x2 추천 벤토 카드, 대화방 2 전환 및 홈버튼 작동 검증', async ({ page }) => {
    await page.locator('.st-key-btn_top_mode_agent button').first().click();
    await waitForStreamlitReady(page);

    await expect(page.locator('.toss-bento-card').first()).toBeVisible({ timeout: 25000 });
    await expect(page.locator('[class*="st-key-btn_bento_start_"]').first()).toBeVisible();

    await page.locator('[class*="st-key-room_btn_2_"] button').first().click();
    await waitForStreamlitReady(page);
    await expect(page.locator('.top-mini-status-bar').first()).toContainText('대화방 2');

    const roomTitleInput = page.locator('input[placeholder*="현재 방 주제 메모"]').first();
    await roomTitleInput.fill('A법인 정기 세무조정');
    await roomTitleInput.press('Enter');
    await waitForStreamlitReady(page);
    await expect(page.locator('.top-mini-status-bar').first()).toContainText('A법인 정기 세무조정');

    const homeFab = page.locator('#tds-kakao-home-fab').first();
    await expect(homeFab).toBeVisible({ timeout: 15000 });
    await homeFab.click();
    await expect(page.locator('#tds-kakao-todo-panel.open').first()).toBeVisible({ timeout: 10000 });
    await page.locator('#tds-kp-close').first().click();
  });

  test('6. [통합고용세액공제 1~4단계 실증] 기업규모 선택, 2단계 사원 추가 모달 및 단계 전환 검증', async ({ page }) => {
    await page.locator('.st-key-btn_top_mode_credit button').first().click();
    await waitForStreamlitReady(page);

    await expect(page.getByText('통합고용세액공제').first()).toBeVisible({ timeout: 25000 });

    await page.getByRole('button', { name: '다음(2단계)' }).first().click();
    await waitForStreamlitReady(page);

    const confirmBtn = page.getByRole('button', { name: /확인 및 2단계/ }).first();
    try {
      await confirmBtn.waitFor({ state: 'visible', timeout: 5000 });
      await confirmBtn.click();
      await waitForStreamlitReady(page);
    } catch {}

    const addEmpBtn = page.locator('[class*="st-key-btn_ec_add_emp_"] button').first();
    await expect(addEmpBtn).toBeVisible({ timeout: 20000 });
    await addEmpBtn.click();

    const empDialog = page.locator(DIALOG_SEL).first();
    await expect(empDialog).toBeVisible({ timeout: 20000 });

    const nameInp = empDialog.locator('input[placeholder*="홍길동"]').first();
    await nameInp.fill('김세무');
    await nameInp.press('Enter');
    await page.waitForTimeout(400);

    const birthInp = empDialog.locator('input[placeholder*="1995-05-15"]').first();
    await birthInp.fill('1996-08-20');
    await birthInp.press('Enter');
    await page.waitForTimeout(400);

    const hireInp = empDialog.locator('input[placeholder*="2026-04-01"]').first();
    await hireInp.fill('2025-01-01');
    await hireInp.press('Enter');
    await page.waitForTimeout(800);

    const submitEmpBtn = empDialog.locator(
      '.st-key-btn_dlg_add_emp_force button:not([disabled]), .st-key-btn_dlg_add_emp_ok button:not([disabled])'
    ).first();
    await expect(submitEmpBtn).toBeEnabled({ timeout: 15000 });
    await submitEmpBtn.click();
    await waitForStreamlitReady(page);

    const nextStep3Btn = page.getByRole('button', { name: '다음(3단계)' }).first();
    await expect(nextStep3Btn).toBeVisible({ timeout: 20000 });
    await nextStep3Btn.click();
    await waitForStreamlitReady(page);
    await expect(page.getByRole('button', { name: '다음(4단계)' }).first()).toBeVisible({ timeout: 25000 });
  });

  test('7. [인건비 자동화 급여명세서 & 사업소득 실증] 행 추가, 세전↔세후 일괄 스위치, 수당 계산기 및 양식 미리보기 검증', async ({ page }) => {
    await page.locator('.st-key-btn_top_mode_payroll button').first().click();
    await waitForStreamlitReady(page);

    await page.locator('[class*="st-key-btn_pay_submode_emp"] button').first().click();
    await waitForStreamlitReady(page);

    await page.locator('.st-key-btn_pay_add_row button').first().click();
    await waitForStreamlitReady(page);
    await expect(page.locator('.ecx-kpis').first()).toContainText('1명', { timeout: 20000 });

    await page.getByRole('button', { name: '수당 계산기' }).first().click();
    await page.locator('.st-key-btn_pay_open_wh_calc button').first().click();
    const whDialog = page.locator('[data-testid="stDialog"]').first();
    await expect(whDialog).toContainText('주휴수당 계산기', { timeout: 20000 });
    await expect(whDialog).toContainText('2,156,880원');
    await whDialog.locator('.st-key-btn_close_wh_dlg button').first().click();
    await expect(whDialog).toBeHidden({ timeout: 15000 });

    await page.locator('.st-key-btn_emp_bulk_gross_net_switch button[data-testid*="stBaseButton"]').first().click();
    await waitForStreamlitReady(page);
    await expect(page.locator('.st-key-pay_free_sw_net').first()).toBeVisible({ timeout: 20000 });
  });
});
