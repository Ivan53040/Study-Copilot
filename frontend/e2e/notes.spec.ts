import { expect, test, type Page } from "@playwright/test";

// The notes workspace: reading, links and mentions, tabs, editing with
// autosave, and the file actions. Runs against the fixture vault served by
// scripts/e2e_server.py (a fresh copy per run).

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

async function openNotes(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Notes", exact: true }).click();
  await expect(page.locator(".ws-tree .tree-row").first()).toBeVisible();
}

const heading = (page: Page) => page.locator(".note-pane .md h1").first();
const tree = (page: Page, name: string) =>
  page.locator(".ws-tree .tree-row", { hasText: new RegExp(`^[▾▸]?\\s*${name}$`) });

async function moreOptions(page: Page, item: string) {
  await page.getByTitle("More options").click();
  await page.locator(".note-actions-menu").getByRole("button", { name: item }).click();
}

test("read a note: outline, links, mentions and tabs", async ({ page }) => {
  await openNotes(page);
  await tree(page, "DECO7250 - Human-Computer Interaction").click();
  await tree(page, "Week 05").click();
  await tree(page, "Trust Calibration").click();
  await expect(heading(page)).toHaveText("Trust Calibration");
  await expect(page.locator(".tab.active")).toContainText("Trust Calibration");
  await expect(tree(page, "Trust Calibration")).toHaveClass(/active/);

  // Outline and backlinks in the right-hand panel.
  const outline = page.locator(".ws-toc");
  await expect(outline.locator(".toc-item", { hasText: "Why it matters" })).toBeVisible();
  await expect(outline.locator(".toc-item", { hasText: "How interfaces support it" })).toBeVisible();
  await expect(outline).toContainText("Linked mentions (1)");
  await expect(outline.locator(".mention-title")).toContainText(["Explainable AI"]);

  // A wikilink opens the linked note in the same tab…
  await page.locator(".note-pane .md .wikilink", { hasText: "Explainable AI" }).click();
  await expect(heading(page)).toHaveText("Explainable AI");
  await expect(page.locator(".tab")).toHaveCount(1);
  // …and Ctrl+click opens one in a new tab.
  await page.locator(".note-pane .md .wikilink", { hasText: "Trust Calibration" }).click({ modifiers: ["Control"] });
  await expect(heading(page)).toHaveText("Trust Calibration");
  await expect(page.locator(".tab")).toHaveCount(2);
  await page.locator(".tab", { hasText: "Explainable AI" }).click();
  await expect(heading(page)).toHaveText("Explainable AI");
  await page.locator(".tab", { hasText: "Explainable AI" }).locator(".tab-close").click();
  await expect(page.locator(".tab")).toHaveCount(1);
  await expect(heading(page)).toHaveText("Trust Calibration");

  // An unlinked mention can be turned into a link from the panel.
  await tree(page, "REIT6811 - Research Methods").click();
  await tree(page, "Week 03").click();
  await tree(page, "Measurement").click();
  await expect(heading(page)).toHaveText("Measurement");
  await expect(outline).toContainText("Unlinked mentions (1)");
  await outline.getByRole("button", { name: "Link" }).click();
  await expect(page.locator(".note-banner")).toContainText("Linked mention in Reading list.");
  await expect(outline).toContainText("Linked mentions (1)");
  await expect(outline).not.toContainText("Unlinked mentions");

  // The new tab button shows a note picker.
  await page.getByTitle("Open new tab").click();
  await page.getByPlaceholder("Search notes to open…").fill("Reading");
  await page.locator(".newtab-result", { hasText: "Reading list" }).click();
  await expect(heading(page)).toHaveText("Reading list");
  await expect(page.locator(".note-pane .md")).toContainText("Revisit Measurement before the quiz");
  await expect(page.locator(".note-pane .md .wikilink", { hasText: "Measurement" })).toBeVisible();
});

test("write: new note, autosave, history, rename, find, split, duplicate, delete", async ({ page }) => {
  await openNotes(page);

  page.once("dialog", (dialog) => void dialog.accept("Inbox/Scratch"));
  await page.getByTitle("New note").click();
  await expect(heading(page)).toHaveText("Scratch");
  await expect(tree(page, "Scratch")).toBeVisible();

  // Source view: type, let autosave write it, then read it back.
  await page.getByTitle("Source code view").click();
  const editor = page.locator(".cm-content");
  await expect(editor).toBeVisible();
  await editor.click();
  await page.keyboard.press("Control+End");
  const saved = page.waitForResponse(
    (response) => response.url().endsWith("/vault/note") && response.request().method() === "PUT",
  );
  await page.keyboard.type("Typed in the browser test.");
  expect((await saved).ok()).toBe(true);
  await page.getByTitle("Reading view").click();
  await expect(page.locator(".note-pane .md")).toContainText("Typed in the browser test.");
  const stored = await page.request.get("/vault/note?path=Inbox%2FScratch.md&links=false");
  expect((await stored.json()).content).toContain("Typed in the browser test.");

  // Version history lists the backup made by the edit.
  await moreOptions(page, "Open version history");
  const history = page.locator(".version-modal");
  await expect(history.getByRole("heading", { name: "Version history" })).toBeVisible();
  await expect(history.locator(".version-entry").first()).toBeVisible();
  await history.getByRole("button", { name: "Close" }).click();
  await expect(history).toHaveCount(0);

  // Rename from the ⋮ menu.
  page.once("dialog", (dialog) => void dialog.accept("Scratch pad"));
  await moreOptions(page, "Rename…");
  await expect(page.locator(".tab.active")).toContainText("Scratch pad");
  await expect(tree(page, "Scratch pad")).toBeVisible();
  await expect(tree(page, "Scratch")).toHaveCount(0);

  // Find bar.
  await moreOptions(page, "Find…");
  await expect(page.getByPlaceholder("Find in note")).toBeFocused();
  await page.locator(".find-bar .icon-btn").click();
  await expect(page.locator(".find-bar")).toHaveCount(0);

  // Split right shows the note twice; closing the split tab goes back to one pane.
  await moreOptions(page, "Split right");
  await expect(page.locator(".note-panes.split-right .note-pane")).toHaveCount(2);
  await page.locator(".right-split-tab-strip .tab-close").click();
  await expect(page.locator(".note-panes .note-pane")).toHaveCount(1);

  // Tree context menu: duplicate, then delete the copy.
  await tree(page, "Welcome").click({ button: "right" });
  await page.locator(".context-menu").getByRole("button", { name: "Duplicate note" }).click();
  await expect(page.locator(".tab.active")).toContainText("Welcome copy");
  await expect(tree(page, "Welcome copy")).toBeVisible();

  page.once("dialog", (dialog) => void dialog.accept());
  await tree(page, "Welcome copy").click({ button: "right" });
  await page.locator(".context-menu").getByRole("button", { name: "Delete file" }).click();
  await expect(tree(page, "Welcome copy")).toHaveCount(0);
  await expect(page.locator(".tab", { hasText: "Welcome copy" })).toHaveCount(0);
});
