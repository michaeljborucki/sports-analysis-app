"""Discord webhook adapter."""
import logging
import time

import requests

logger = logging.getLogger("mirofish.notify.discord")


def send_discord(webhook_url: str, messages: list[str]) -> int:
    """POST each message to a Discord webhook. Returns number sent successfully."""
    if not webhook_url:
        logger.warning("Discord webhook URL is empty — skipping")
        return 0
    sent = 0
    for msg in messages:
        try:
            resp = requests.post(
                webhook_url,
                json={"content": msg},
                timeout=15,
            )
            if resp.status_code in (200, 204):
                sent += 1
            elif resp.status_code == 429:
                # rate-limited; honor retry_after, then retry once
                retry_after = float(resp.json().get("retry_after", 1.0))
                logger.warning("Discord 429: sleeping %.2fs", retry_after)
                time.sleep(retry_after)
                resp2 = requests.post(webhook_url, json={"content": msg}, timeout=15)
                if resp2.status_code in (200, 204):
                    sent += 1
                else:
                    logger.error("Discord retry failed: %d %s", resp2.status_code, resp2.text[:200])
            else:
                logger.error("Discord send failed: %d %s", resp.status_code, resp.text[:200])
        except requests.RequestException as e:
            logger.error("Discord request error: %s", e)
        # Short pause between messages to avoid rate-limit
        time.sleep(0.5)
    return sent
