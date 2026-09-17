from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
ORGANIZER_SOURCE = ROOT / "src" / "organizer" / "livery-organizer-for-fh6.py"
PASS_MARKER = 'id="lo4fh6-browser-smoke-result" data-status="PASS"'
FAIL_MARKER = 'id="lo4fh6-browser-smoke-result" data-status="FAIL"'


def load_organizer():
    module_name = "fh6_browser_compare_smoke"
    organizer_dir = str(ORGANIZER_SOURCE.parent)
    if organizer_dir not in sys.path:
        sys.path.insert(0, organizer_dir)
    spec = importlib.util.spec_from_file_location(module_name, ORGANIZER_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Organizer source could not be loaded: {ORGANIZER_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def make_record(o, *, index: int, fingerprint: str, ui_key: str, car_id: int | None = None):
    timestamp = f"2026010{index}000000"
    car_id = index if car_id is None else car_id
    score = {1: 5, 2: 2, 3: 1}.get(index, 1)
    band = "automation-likely" if score >= 3 else ("review" if score == 2 else "inconclusive")
    display = f"{score}/5"
    audit = {
        "calibration": "lo4fh6-2026-09-provisional-v1",
        "eligible": True,
        "score": score,
        "max_score": 5,
        "band": band,
        "display": display,
        "scan_quality": "high",
        "scan_ratio_vs_declared": 1.0,
        "recovered_direct_records": 100 + index,
        "matched_rules": [f"rule-{n}" for n in range(score)],
        "missed_rules": [f"rule-{n}" for n in range(score, 5)],
        "rule_details": [
            {"id": f"rule-{n}", "label": f"監査条件{n + 1}", "matched": n < score}
            for n in range(5)
        ],
        "features": {"record_count": 100 + index},
        "note": "ブラウザsmoke用監査データ",
    }
    return o.LiveryRecord(
        livery_id=f"Livery_{index:04d}_{timestamp}",
        car_id=car_id,
        car_id_folder=car_id,
        car_id_c_livery=car_id,
        car_id_verified=True,
        timestamp_raw=timestamp,
        timestamp_local_guess=f"2026-01-0{index} 09:00:00 JST",
        fh6_date_raw=f"0{index}012026",
        fh6_date_display=f"0{index}/01/2026",
        title=f"Browser Smoke {index}",
        description=f"Browser smoke fixture {index}",
        creator="Browser Smoke",
        header_strings=[],
        vehicle_display_name=f"2026 Browser Smoke Car {index}",
        vehicle_make="Smoke",
        vehicle_model=f"Car {index}",
        vehicle_year=2026,
        vehicle_asset=f"smoke_{index}",
        vehicle_source="browser smoke",
        source_dir=f"Livery_{index:04d}_{timestamp}",
        relative_source_dir=f"Livery_{index:04d}_{timestamp}",
        snapshot_name="browser-smoke",
        preferred_copy=True,
        header_path="",
        c_livery_path="",
        image_path="",
        report_image="",
        header_size=1,
        c_livery_size=1,
        image_size=0,
        header_sha256_16=(str(index) * 16)[:16],
        c_livery_sha256_16=(str(index + 3) * 16)[:16],
        image_sha256_16="",
        fingerprint=fingerprint,
        c_livery_compressed_size=1,
        c_livery_uncompressed_size=1,
        c_livery_zlib_valid=True,
        vinyl_count=100 + index,
        duplicate_copies=1,
        duplicate_sources=[],
        livery_reference_id=f"smoke-ref-{index}",
        applied_state="unknown",
        applied_reference_paths=[],
        parse_warnings=[],
        authorship_audit=audit,
        ui_key=ui_key,
    )


def smoke_records(o):
    # Slot #001 is independent. Slots #002/#003 intentionally share a fingerprint
    # so the exact-duplicate flow can be exercised in the same generated report.
    return [
        make_record(o, index=1, fingerprint="1" * 32, ui_key="browser-smoke-1"),
        make_record(o, index=2, fingerprint="d" * 32, ui_key="browser-smoke-dup-a", car_id=2),
        make_record(o, index=3, fingerprint="d" * 32, ui_key="browser-smoke-dup-b", car_id=2),
    ]


def smoke_stats() -> dict:
    return {
        "livery_folders": 3,
        "unique_liveries": 3,
        "unique_car_ids": 3,
        "historical_duplicate_copies": 0,
        "fh6_exact_duplicate_groups": 1,
        "fh6_exact_duplicate_cards": 2,
        "fh6_exact_duplicate_instances": 2,
        "vehicle_db_size": 0,
        "scan_finished_local": "2026-01-03 09:00:00 JST",
    }


SMOKE_SCRIPT = r"""
<script id="lo4fh6BrowserSmokeHarness">
(() => {
  const result = document.createElement("pre");
  result.id = "lo4fh6-browser-smoke-result";
  document.body.appendChild(result);
  const finish = (status, message) => {
    result.dataset.status = status;
    result.textContent = `${status}: ${message}`;
    document.title = `LO4FH6_BROWSER_SMOKE_${status}`;
  };
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  try {
    assert(typeof renderCompareMembers === "function", "renderCompareMembers is unavailable");
    assert(typeof renderExactDuplicateModal === "function", "renderExactDuplicateModal is unavailable");
    assert(cards.length === 3, `expected 3 cards, got ${cards.length}`);

    const first = cards.find(card => fh6LocationForCard(card)?.slotNumber === 1);
    const second = cards.find(card => fh6LocationForCard(card)?.slotNumber === 2);
    assert(first && second, "slot #001/#002 cards were not found");
    const firstInstance = currentFh6InstanceForCard(first);
    assert(firstInstance, "first card has no FH6 instance");
    assert(fh6LocationForCard(first)?.slotNumber === 1, "first card is not slot #001");
    assert(fh6LocationForCard(second)?.slotNumber === 2, "second card is not slot #002");
    assert(first.dataset.authorshipAuditScore === "5", "authorship audit score is missing from card data");
    assert(first.querySelector(".authorship-audit-score")?.textContent?.trim() === "5/5", "authorship audit summary score is missing");

    renderCompareMembers([first, second], {mode:"selected", title:"Browser smoke"});
    let grid = document.getElementById("compareGrid");
    assert(grid?.querySelectorAll(".compare-item").length === 2, "compare view did not render 2 cards");
    assert(grid?.textContent?.includes("作成方法監査"), "authorship audit is missing from compare view");
    assert(grid?.textContent?.includes("5/5"), "authorship audit score is missing from compare view");
    const deleteButton = [...grid.querySelectorAll('[data-compare-state="delete"]')]
      .find(button => button.dataset.compareKey === first.dataset.key);
    assert(deleteButton, "delete-candidate button is missing");
    deleteButton.click();
    assert(getState(first) === "delete", "compare decision did not reach setState");
    grid = document.getElementById("compareGrid");
    const pressedDelete = [...grid.querySelectorAll('[data-compare-state="delete"]')]
      .find(button => button.dataset.compareKey === first.dataset.key);
    assert(pressedDelete?.getAttribute("aria-pressed") === "true", "compare decision did not redraw active state");

    const tempDeleteButton = [...grid.querySelectorAll("[data-compare-temp-delete]")]
      .find(button => button.dataset.compareTempDelete === String(firstInstance.instance_id || ""));
    assert(tempDeleteButton, "FH6 temp-delete button is missing from compare view");
    tempDeleteButton.click();
    assert(fh6TempDeletedInstanceIds.has(String(firstInstance.instance_id || "")), "FH6 temp-delete state was not saved");
    assert(activeCompareMembers.length === 1 && activeCompareMembers[0] === second, "compare view did not remove deleted member");
    assert(document.querySelectorAll("#compareGrid .compare-item").length === 1, "compare view did not redraw remaining member");
    assert(fh6LocationForCard(second)?.slotNumber === 1, "FH6 slot numbers were not compacted after temp delete");

    renderFh6TempDeletedModal();
    const deletedSearch = document.getElementById("fh6TempDeletedSearch");
    assert(deletedSearch, "FH6 temp-deleted search is missing");
    deletedSearch.value = "Browser Smoke 1 #001U";
    deletedSearch.dispatchEvent(new Event("input", {bubbles:true}));
    assert(document.querySelectorAll("#fh6TempDeletedBody .fh6-temp-delete-row").length === 1, "FH6 temp-deleted search did not match vehicle/title/position");
    assert(document.getElementById("fh6TempDeletedSearchStatus")?.textContent === "表示 1 / 1件", "FH6 temp-deleted search count is incorrect");
    deletedSearch.value = "no-such-design";
    deletedSearch.dispatchEvent(new Event("input", {bubbles:true}));
    assert(document.querySelectorAll("#fh6TempDeletedBody .fh6-temp-delete-row").length === 0, "FH6 temp-deleted search did not filter unmatched item");
    document.getElementById("fh6TempDeletedSearchClear")?.click();
    assert(document.querySelectorAll("#fh6TempDeletedBody .fh6-temp-delete-row").length === 1, "FH6 temp-deleted search clear did not restore list");

    assert(restoreAllFh6TempDeletedInstances(), "FH6 temp-delete restore failed");
    assert(fh6LocationForCard(second)?.slotNumber === 2, "FH6 slot numbers were not restored");

    const duplicateEntries = exactDuplicateGroupEntries();
    assert(duplicateEntries.length === 1, `expected 1 duplicate group, got ${duplicateEntries.length}`);
    const [group, members] = duplicateEntries[0];
    assert(members.length === 2, `expected 2 duplicate members, got ${members.length}`);
    assert(renderExactDuplicateModal(group), "exact duplicate modal failed to render");
    const duplicateDeleteButton = document.querySelector("#exactDuplicateGrid [data-compare-temp-delete]");
    assert(duplicateDeleteButton, "FH6 temp-delete button is missing from exact-duplicate view");
    const duplicateInstanceId = String(duplicateDeleteButton.dataset.compareTempDelete || "");
    duplicateDeleteButton.click();
    assert(fh6TempDeletedInstanceIds.has(duplicateInstanceId), "exact-duplicate temp-delete state was not saved");
    assert(!exactDuplicateGroupEntries().some(([entryGroup]) => entryGroup === group), "resolved duplicate group is still active");
    assert(document.getElementById("exactDuplicateModal")?.classList.contains("hidden"), "resolved final duplicate group did not close modal");
    restoreAllFh6TempDeletedInstances();

    finish("PASS", "compare decision, FH6 temp-delete search/restore, slot recompute, and exact-duplicate flow");
  } catch (error) {
    console.error(error);
    finish("FAIL", error && error.message ? error.message : String(error));
  }
})();
</script>
""".strip()


def inject_smoke_harness(html: str) -> str:
    if "</body>" not in html:
        raise ValueError("Generated report has no </body> marker")
    return html.replace("</body>", SMOKE_SCRIPT + "\n</body>", 1)


def browser_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for name in ("msedge.exe", "msedge", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        unique.append(path)
    return unique


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003 - stdlib signature
        pass


@contextlib.contextmanager
def local_server(directory: Path):
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(directory), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def cleanup_browser_profile(profile: Path, *, attempts: int = 20, delay: float = 0.25) -> bool:
    """Remove an isolated Chromium profile after child processes release Windows cache files."""
    for attempt in range(attempts):
        try:
            shutil.rmtree(profile)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if attempt + 1 >= attempts:
                break
            time.sleep(delay)
    # Cleanup failure must not turn a successful browser assertion into a false test failure.
    # A best-effort final pass normally succeeds once Chromium's detached cache process exits.
    shutil.rmtree(profile, ignore_errors=True)
    return not profile.exists()


def run_headless_browser(browser: Path, html_path: Path, *, timeout: int = 30) -> tuple[bool, str]:
    # Keep the Chromium profile outside the report TemporaryDirectory. On Windows, Edge can
    # retain cache-file handles briefly after --dump-dom exits; nesting the profile under the
    # report directory makes TemporaryDirectory.__exit__ raise WinError 5 even after PASS.
    profile = Path(tempfile.mkdtemp(prefix="lo4fh6-browser-profile-"))
    try:
        with local_server(html_path.parent) as port:
            url = f"http://127.0.0.1:{port}/{html_path.name}"
            command = [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=2000",
                "--dump-dom",
                url,
            ]
            if os.name != "nt":
                command.insert(2, "--no-sandbox")
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        if PASS_MARKER in stdout:
            return True, stdout
        detail = stdout if FAIL_MARKER in stdout else stderr[-4000:]
        return False, detail
    finally:
        if not cleanup_browser_profile(profile):
            print(f"WARN — browser profile cleanup deferred: {profile}", file=sys.stderr)


def build_smoke_report(directory: Path) -> Path:
    organizer = load_organizer()
    organizer.set_language("ja")
    root = directory / "source"
    out = directory / "report"
    root.mkdir(parents=True, exist_ok=True)
    records = smoke_records(organizer)
    html_path = organizer.write_report(
        root,
        records,
        smoke_stats(),
        out,
        embed_images=True,
        fh6_records=records,
    )
    html = html_path.read_text(encoding="utf-8")
    html_path.write_text(inject_smoke_harness(html), encoding="utf-8")
    return html_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LO4FH6 compare/FH6 browser smoke test")
    parser.add_argument("--require-browser", action="store_true", help="fail instead of skip when no supported browser is found")
    args = parser.parse_args(argv)

    browsers = browser_candidates()
    if not browsers:
        message = "SKIP — Microsoft Edge / Chromium-compatible browser was not found."
        print(message)
        return 1 if args.require_browser else 0

    with tempfile.TemporaryDirectory(prefix="lo4fh6-browser-smoke-") as tmp:
        html_path = build_smoke_report(Path(tmp))
        errors: list[str] = []
        for browser in browsers:
            try:
                ok, detail = run_headless_browser(browser, html_path)
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(f"{browser}: {exc}")
                continue
            if ok:
                print(f"PASS — browser compare/FH6 smoke test: {browser}")
                print("Checked authorship audit, compare decisions, FH6 temp-delete search/restore, slot recompute, and exact-duplicate resolution.")
                return 0
            errors.append(f"{browser}: {detail[-1200:]}")

    print("FAIL — browser compare/FH6 smoke test")
    for error in errors:
        print(error)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
