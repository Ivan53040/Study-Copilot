import { expect, test, type Page } from "@playwright/test";

// Smoke tests for the main flows. The server (scripts/e2e_server.py) uses a
// fixture vault and a scripted chat model that streams:
//   "According to your notes: <first sentence of source 1> [S1]. …"

const errors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const list: string[] = [];
  errors.set(page, list);
  page.on("pageerror", (error) => list.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") list.push(message.text());
  });
});

test.afterEach(async ({ page }) => {
  expect(errors.get(page) ?? [], "no errors in the browser console").toEqual([]);
});

async function ask(page: Page, text: string, scope = page.locator("body")) {
  const box = scope.locator(".composer textarea");
  await box.fill(text);
  await box.press("Enter");
}

function lastAnswer(scope: Page | ReturnType<Page["locator"]>) {
  return scope.locator(".turn-assistant").last();
}

async function waitForAnswer(scope: Page | ReturnType<Page["locator"]>) {
  await expect(lastAnswer(scope).locator(".turn-actions")).toBeVisible({ timeout: 30_000 });
}

test("chat streams a cited answer; regenerate and edit replace it", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".greeting")).toBeVisible();

  await ask(page, "What is calibrated trust?");
  // While the answer streams the send button is a Stop button.
  await expect(page.getByRole("button", { name: "Stop answering" })).toBeVisible();
  await expect(page.locator(".think-block")).toBeVisible();
  await waitForAnswer(page);

  const answer = lastAnswer(page);
  await expect(answer.locator(".md")).toContainText("Calibrated trust means");
  await expect(answer.locator(".cite-chip").first()).toBeVisible();
  await expect(answer.locator(".source-card").first()).toContainText("Trust Calibration");
  await expect(answer.locator(".think-toggle")).toContainText("Thought for");

  await answer.hover();
  await page.getByRole("button", { name: "Regenerate answer" }).click();
  await expect(page.getByRole("button", { name: "Stop answering" })).toBeVisible();
  await waitForAnswer(page);
  await expect(page.locator(".turn-assistant")).toHaveCount(1);

  await page.locator(".turn-user-wrap").hover();
  await page.getByRole("button", { name: "Edit message" }).click();
  await page.getByLabel("Edit your message").fill("How is reliability different from validity?");
  await page.getByLabel("Edit your message").press("Enter");
  await expect(page.locator(".turn-user")).toHaveText("How is reliability different from validity?");
  await waitForAnswer(page);
  await expect(page.locator(".turn-assistant")).toHaveCount(1);
  await expect(lastAnswer(page).locator(".source-card").first()).toContainText("Measurement");

  // The edited question titles the chat in Recents, and reloading it shows
  // the saved (replaced) conversation.
  await expect(page.locator(".sb-recents")).toContainText("How is reliability different");
  await page.reload();
  await page.locator(".sb-recents .sb-item").first().click();
  await expect(page.locator(".turn-user")).toHaveText(["How is reliability different from validity?"]);
  await expect(page.locator(".turn-assistant")).toHaveCount(1);
});

test("stop keeps what was written so far", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What does over-trust lead to?");
  await expect(page.locator(".turn.streaming .md")).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Stop answering" }).click();

  const answer = lastAnswer(page);
  await expect(answer).toContainText("Stopped before the answer was finished.");
  await expect(answer.locator(".md")).toContainText("According to");
  await expect(page.getByRole("button", { name: "Send message" })).toBeVisible();

  // The partial answer was saved.
  await page.reload();
  await page.locator(".sb-recents .sb-item").first().click();
  await expect(lastAnswer(page)).toContainText("Stopped before the answer was finished.");
});

test("stop before the answer starts: the question goes back in the box", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What is validity? (slow search)");
  await expect(page.locator(".turn-user")).toHaveText("What is validity? (slow search)");
  await page.getByRole("button", { name: "Stop answering" }).click();
  await expect(page.locator(".turn-user")).toHaveCount(0);
  await expect(page.locator(".composer textarea")).toHaveValue("What is validity? (slow search)");
  // Nothing was saved: no chat appears in Recents after a reload.
  await page.waitForTimeout(2000);
  await page.reload();
  await expect(page.locator(".sb-recents")).not.toContainText("slow search");
});

test("reasoning that only ends with </think> moves out of the answer", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What is calibrated trust? (think in the prompt)");
  await waitForAnswer(page);
  const answer = lastAnswer(page);
  await expect(answer.locator(".md")).toContainText("Calibrated trust means");
  await expect(answer.locator(".md")).not.toContainText("Working it out");
  await expect(answer.locator(".think-toggle")).toContainText("Thought for");
  await answer.locator(".think-toggle").click();
  await expect(answer.locator(".think-block")).toContainText("Working it out.");
});

test("the chat panel next to a note answers from that note", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Notes", exact: true }).click();
  await page.locator(".tree-row", { hasText: "DECO7250" }).click();
  await page.locator(".tree-row", { hasText: "Week 05" }).click();
  await page.locator(".tree-row", { hasText: "Trust Calibration" }).click();
  await expect(page.locator(".note-page .md h1").first()).toContainText("Trust Calibration");
  await expect(page.locator(".crumb")).toContainText("Trust Calibration");

  await page.getByRole("button", { name: "Toggle chat panel" }).click();
  const dock = page.locator(".chat-dock");
  await expect(dock.locator(".note-chip")).toContainText("Trust Calibration");
  await ask(page, "What are the risks?", dock);
  // Going to the Chat page and back while it answers doesn't lose the answer.
  await expect(dock.locator(".turn.streaming")).toBeVisible();
  await page.locator(".sb-new").click();
  await expect(dock).toBeHidden();
  await page.getByRole("button", { name: "Notes", exact: true }).click();
  await expect(dock).toBeVisible();
  await waitForAnswer(dock);
  await expect(dock.locator(".turn-note-chip")).toContainText("Trust Calibration");
  const titles = await dock.locator(".source-card .source-title").allInnerTexts();
  expect(titles.length).toBeGreaterThan(0);
  for (const title of titles) expect(["Trust Calibration", "Explainable AI"]).toContain(title);

  // Turning the chip off brings back the course picker.
  await dock.locator(".note-chip").click();
  await expect(dock.getByRole("button", { name: /All notes/ })).toBeVisible();
});

test("Today: add a date, see the countdown and the home nudge, remove it", async ({ page }) => {
  const due = new Date();
  due.setDate(due.getDate() + 10);
  const iso = `${due.getFullYear()}-${String(due.getMonth() + 1).padStart(2, "0")}-${String(due.getDate()).padStart(2, "0")}`;

  await page.goto("/");
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add date" }).click();
  const form = page.locator(".deadline-form");
  await form.getByLabel("What is due").fill("DECO7250 final exam");
  await form.getByLabel("Course").fill("DECO7250");
  await form.getByLabel("Date").fill(iso);
  await page.locator(".deadline-form button[type=submit]").click();
  const row = page.locator(".deadline", { hasText: "DECO7250 final exam" });
  await expect(row.locator(".countdown")).toHaveText("10 days");

  await page.locator(".sb-new").click();
  await expect(page.locator(".today-nudge")).toContainText("DECO7250 final exam in 10 days");
  await page.locator(".today-nudge").click();
  await expect(page.getByRole("heading", { name: "Today", exact: true })).toBeVisible();

  page.once("dialog", (dialog) => void dialog.accept());
  await row.hover();
  await page.getByRole("button", { name: "Remove DECO7250 final exam" }).click();
  await expect(page.locator(".deadline")).toHaveCount(0);
});

test("Quiz me on this: a quiz from an answer's sources, marked, then tracked on Today", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What is calibrated trust?");
  await waitForAnswer(page);
  await lastAnswer(page).getByRole("button", { name: /Quiz me on this/ }).click();

  await expect(page.locator(".note-banner")).toContainText("sources behind");
  const questions = page.locator(".result");
  await expect(questions).toHaveCount(2, { timeout: 20_000 });
  await questions.nth(0).getByLabel("Reliance matches what the system can do").check();
  await questions.nth(1).locator("textarea").fill("Show confidence and limitations");
  await page.getByRole("button", { name: "Submit answers" }).click();
  await expect(page.locator(".note-banner", { hasText: "Score" })).toBeVisible({ timeout: 20_000 });

  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(page.locator(".today-stats")).toContainText("tracked");
});

test("appearance and quick open", async ({ page }) => {
  await page.goto("/");
  await page.getByTitle("Settings", { exact: true }).click();
  await page.getByRole("radio", { name: /Ocean/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-palette", "ocean");

  await page.keyboard.press("Control+k");
  const search = page.getByPlaceholder("Search notes, chats and pages…");
  await expect(search).toBeFocused();
  await search.fill("Measurement");
  await expect(page.locator(".qo-results")).toContainText("Measurement");
  await search.press("Enter");
  await expect(page.locator(".note-page .md h1").first()).toContainText("Measurement");
});
