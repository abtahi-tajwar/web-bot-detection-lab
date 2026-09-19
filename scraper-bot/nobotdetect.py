import json
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "http://localhost:3000"
OUTPUT = Path(__file__).resolve().parent / "results"


def main():
    OUTPUT.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chromium",
            headless=True,
        )

        try:
            page = browser.new_page(
                viewport={"width": 1280, "height": 900}
            )

            print("Opening BotD in a headless browser...")
            page.goto(URL, wait_until="load")

            # Wait until BotD displays its detection result.
            page.wait_for_function(
                r"""() => {
                    const element =
                        document.querySelector("#detection-result");

                    return element &&
                        /"bot"\s*:/.test(element.textContent);
                }""",
                timeout=30000,
            )

            result = json.loads(
                page.locator("#detection-result").inner_text()
            )

            report = {
                "mode": "headless",
                "browser_version": browser.version,
                "result": result,
                "detector_details": (
                    page.locator("#detectors").inner_text()
                ),
                "collected_data": (
                    page.locator("#collected-data").inner_text()
                ),
            }

            report_path = OUTPUT / "headless.json"
            report_path.write_text(
                json.dumps(report, indent=2),
                encoding="utf-8",
            )

            page.screenshot(
                path=str(OUTPUT / "headless.png"),
                full_page=True,
            )

            print("\nBotD result:")
            print(json.dumps(result, indent=2))

            if result["bot"]:
                print("\nBotD detected this automated browser.")
            else:
                print("\nBotD did not detect this automated browser.")

            print(f"\nEvidence saved in: {OUTPUT}")

        except Exception as error:
            print(f"\nTest inconclusive: {error}")
            print("Check that BotD is running at http://localhost:3000")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
