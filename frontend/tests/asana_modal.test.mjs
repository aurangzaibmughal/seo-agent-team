import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const pagePath = path.resolve(__dirname, "../src/app/page.tsx");

test("Asana Modal: Unconfigured State renders neutral note instead of yellow warning", () => {
  const pageContent = fs.readFileSync(pagePath, "utf-8");

  // Extract Asana modal content block
  const asanaModalStart = pageContent.indexOf("{showAsanaModal && (");
  assert.ok(asanaModalStart > 0, "showAsanaModal section must exist");
  const asanaModalEnd = pageContent.indexOf("{showHistoryModal && (", asanaModalStart);
  assert.ok(asanaModalEnd > asanaModalStart, "showHistoryModal must follow showAsanaModal");
  const asanaModalBlock = pageContent.slice(asanaModalStart, asanaModalEnd);

  // 1. Verify the old yellow warning is completely gone from the Asana modal
  assert.equal(
    asanaModalBlock.includes("ASANA_ACCESS_TOKEN is not configured in backend .env"),
    false,
    "The old ASANA_ACCESS_TOKEN yellow warning text should be removed"
  );
  assert.equal(
    asanaModalBlock.includes("bg-amber-950/40 border border-amber-800/60"),
    false,
    "Amber warning styling should no longer be present on the unconfigured Asana note"
  );

  // 2. Verify the new neutral note is present with exact requested wording
  const expectedNeutralNote = "Direct sync to Asana is off. You can still download asana_import.csv below.";
  assert.equal(
    asanaModalBlock.includes(expectedNeutralNote),
    true,
    `Asana modal should contain the exact neutral note: "${expectedNeutralNote}"`
  );

  // 3. Verify neutral styling
  assert.equal(
    asanaModalBlock.includes("bg-slate-900/60 border border-slate-800 p-3 rounded-xl text-slate-300"),
    true,
    "Neutral note should use neutral slate border and background styling"
  );

  // 4. Verify preview and CSV download button remain intact
  assert.equal(
    asanaModalBlock.includes("Download asana_import.csv"),
    true,
    "CSV download button should remain intact"
  );
  assert.equal(
    asanaModalBlock.includes("Milestone Start Date:"),
    true,
    "Milestone Start Date control should remain intact"
  );
  assert.equal(
    asanaModalBlock.includes("Dry-Run Task Mapping Preview"),
    true,
    "Dry-Run Task Mapping Preview header should remain intact"
  );
  assert.equal(
    asanaModalBlock.includes("asanaPreviewTasks?.map"),
    true,
    "Task preview table mapping should remain intact"
  );
});
