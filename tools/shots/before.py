"""Before screenshots of the live site as a demo reader (deleted after)."""

import asyncio
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cdp  # noqa: E402

WEB = "https://readlayer-sourabh-26.web.app"
API = "https://readlayer-api-751104670850.asia-south1.run.app"
SIZES = ((1440, False), (1440, True), (390, False), (390, True))


async def main():
    cdp.launch()
    p, ws = await cdp.open_page()
    try:
        await p.viewport(1440)
        await cdp.Page.reset_auth(p, WEB)
        await p.goto(WEB + "/", wait=4)
        for w, dark in SIZES:
            await p.viewport(w, dark=dark)
            await asyncio.sleep(1)
            print("signin", w, dark, await p.shot(f"before-signin-{w}-{'dark' if dark else 'light'}", full=True))
        await p.viewport(1440)
        await p.click_text("button", "Newcomer", 5)
        content = (await p.api(API, "GET", "/v1/content?persona=newcomer"))["body"]
        article = content[0]["id"]
        pages = {"library": "/?persona=newcomer", "feed": "/for-you?persona=newcomer",
                 "reader": f"/read/{article}?persona=newcomer", "profile": "/profile?persona=newcomer"}
        for name, path in pages.items():
            for w, dark in SIZES:
                await p.viewport(w, dark=dark)
                await p.goto(WEB + path, wait=6)
                print(name, w, dark, await p.shot(f"before-{name}-{w}-{'dark' if dark else 'light'}", full=name != "reader"))
        d = await p.api(API, "DELETE", "/v1/me")
        print("cleanup DELETE /v1/me", d["status"])
    finally:
        await ws.close()
        cdp.stop()


asyncio.run(main())
