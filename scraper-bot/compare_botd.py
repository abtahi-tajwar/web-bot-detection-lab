import argparse
import json
import platform
import random
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright


URL = "http://localhost:3000"
OUTPUT = Path(__file__).resolve().parent / "results"

# Test number: (browser engine, headless mode)
CASES = {
    "1": ("chromium", True),
    "2": ("firefox", True),
    "3": ("webkit", True),
    "4": ("chromium", False),
    "5": ("firefox", False),
    "6": ("webkit", False),
}


def run_test(playwright, case_id, repetition):
    engine, headless = CASES[case_id]
    mode = "headless" if headless else "headed"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    folder = OUTPUT / (
        f"{timestamp}_{engine}_{mode}_"
        f"run{repetition}_{uuid4().hex[:8]}"
    )
    folder.mkdir(parents=True, exist_ok=True)

    launch_options = {"headless": headless}

    # Use the same Chromium distribution in both modes.
    if engine == "chromium":
        launch_options["channel"] = "chromium"

    report = {
        "case": case_id,
        "repetition": repetition,
        "timestamp_utc": timestamp,
        "url": URL,
        "engine": engine,
        "mode": mode,
        "launch_options": launch_options,
        "python_version": platform.python_version(),
        "playwright_version": version("playwright"),
        "operating_system": platform.platform(),
        "status": "inconclusive",
    }

    browser = None
    page = None

    print(f"\nTest {case_id}: {engine}, {mode}, run {repetition}")

    try:
        browser_type = getattr(playwright, engine)
        browser = browser_type.launch(**launch_options)
        report["browser_version"] = browser.version

        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="UTC",
        )

        page = context.new_page()
        page.goto(URL, wait_until="load", timeout=30000)

        # The playground contains hidden placeholder error text.
        # Only consider an error when BotD marks it as displayed.
        page.wait_for_function(
            """() => {
                const errorContainer =
                    document.getElementById("error-container");

                if (
                    errorContainer &&
                    errorContainer.classList.contains(
                        "error-container-visible"
                    )
                ) {
                    return true;
                }

                try {
                    const element =
                        document.getElementById("detection-result");

                    if (!element) return false;

                    const result = JSON.parse(element.textContent);
                    return typeof result.bot === "boolean";
                } catch {
                    return false;
                }
            }""",
            timeout=30000,
        )

        # Read the existing page output without changing its signals.
        snapshot = page.evaluate(
            """() => {
                const read = id =>
                    document.getElementById(id)?.textContent || "";

                const errorContainer =
                    document.getElementById("error-container");

                const errorVisible = Boolean(
                    errorContainer &&
                    errorContainer.classList.contains(
                        "error-container-visible"
                    )
                );

                return {
                    errorVisible,
                    error: read("error-message").trim(),
                    result: read("detection-result"),
                    detectors: read("detectors"),
                    components: read("collected-data"),
                    debug: read("debug-data")
                };
            }"""
        )

        if snapshot["errorVisible"]:
            raise RuntimeError(
                snapshot["error"] or "BotD displayed an error."
            )

        result = json.loads(snapshot["result"])
        detectors = json.loads(snapshot["detectors"])
        components = json.loads(snapshot["components"])
        debug = json.loads(snapshot["debug"])

        if not isinstance(result.get("bot"), bool):
            raise ValueError("BotD did not return a boolean verdict.")

        triggered = {
            name: value
            for name, value in detectors.items()
            if value.get("bot") is True
        }

        # In this BotD snapshot, state 0 means successful collection.
        source_errors = {
            name: value
            for name, value in components.items()
            if value.get("state") != 0
        }

        report.update({
            "status": "completed",
            "result": result,
            "triggered_detectors": triggered,
            "all_detectors": detectors,
            "components": components,
            "source_errors": source_errors,
            "debug": debug,
        })

        verdict = "DETECTED" if result["bot"] else "NOT DETECTED"

        print(f"Verdict: {verdict}")
        print(f"BotD label: {result.get('botKind', 'none')}")

        print("\nTriggered rules:")
        if triggered:
            for name, value in triggered.items():
                label = value.get("botKind", "unknown")
                print(f"  - {name}: {label}")
        else:
            print("  No rule returned a positive result.")

        print(f"\nSource collection errors: {len(source_errors)}")

        for name, value in source_errors.items():
            print(f"  - {name}: {value.get('error', 'Unavailable')}")

    except Exception as error:
        report["error"] = str(error)
        print(f"INCONCLUSIVE: {error}")
        print(
            "Check that the original BotD playground is running "
            "at http://localhost:3000."
        )

    finally:
        if page is not None:
            try:
                page.screenshot(
                    path=str(folder / "screenshot.png"),
                    full_page=True,
                    timeout=10000,
                )
            except Exception as error:
                report["screenshot_error"] = str(error)

        if browser is not None:
            try:
                browser.close()
            except Exception as error:
                report["cleanup_error"] = str(error)

        (folder / "report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )

        print(f"Saved: {folder}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Compare local BotD results across browser configurations."
    )
    parser.add_argument(
        "case",
        choices=["all", *CASES],
        help="Choose test 1–6, or all.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of fresh browser launches per configuration.",
    )
    args = parser.parse_args()

    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    selected = list(CASES) if args.case == "all" else [args.case]

    jobs = [
        (case_id, repetition)
        for repetition in range(1, args.repeat + 1)
        for case_id in selected
    ]

    random.Random(42).shuffle(jobs)

    reports = []

    with sync_playwright() as playwright:
        for case_id, repetition in jobs:
            reports.append(
                run_test(playwright, case_id, repetition)
            )

    print("\nSUMMARY")

    for report in reports:
        if report["status"] != "completed":
            verdict = "INCONCLUSIVE"
        else:
            verdict = (
                "DETECTED"
                if report["result"]["bot"]
                else "NOT DETECTED"
            )

        print(
            f"{report['engine']:8} "
            f"{report['mode']:8} "
            f"run {report['repetition']}: {verdict}"
        )


if __name__ == "__main__":
    main()