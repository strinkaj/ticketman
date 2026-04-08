"""CAPTCHA solving via 2Captcha or CapSolver."""

from __future__ import annotations

import asyncio
import logging

import httpx

from ticketman.models import CaptchaConfig

log = logging.getLogger(__name__)

TWOCAPTCHA_BASE = "https://2captcha.com"
CAPSOLVER_BASE = "https://api.capsolver.com"


class CaptchaSolver:
    """Solves reCAPTCHA v2/v3 using third-party solving services."""

    def __init__(self, config: CaptchaConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(timeout=30)

    async def solve_recaptcha_v2(self, sitekey: str, page_url: str) -> str:
        """Solve a reCAPTCHA v2 challenge and return the response token."""
        if self.config.provider == "2captcha":
            return await self._solve_2captcha(sitekey, page_url, version="v2")
        elif self.config.provider == "capsolver":
            return await self._solve_capsolver(sitekey, page_url, version="v2")
        else:
            raise ValueError(f"Unknown CAPTCHA provider: {self.config.provider}")

    async def solve_recaptcha_v3(
        self, sitekey: str, page_url: str, action: str = "verify"
    ) -> str:
        """Solve a reCAPTCHA v3 challenge and return a high-score token."""
        if self.config.provider == "2captcha":
            return await self._solve_2captcha(
                sitekey, page_url, version="v3", action=action
            )
        elif self.config.provider == "capsolver":
            return await self._solve_capsolver(
                sitekey, page_url, version="v3", action=action
            )
        else:
            raise ValueError(f"Unknown CAPTCHA provider: {self.config.provider}")

    async def _solve_2captcha(
        self,
        sitekey: str,
        page_url: str,
        *,
        version: str = "v2",
        action: str = "verify",
    ) -> str:
        """Submit to 2Captcha and poll for result."""
        log.info("Submitting reCAPTCHA %s to 2Captcha...", version)

        # Step 1: Submit task
        params: dict = {
            "key": self.config.api_key,
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": page_url,
            "json": 1,
        }
        if version == "v3":
            params["version"] = "v3"
            params["action"] = action
            params["min_score"] = 0.9

        resp = await self._client.get(f"{TWOCAPTCHA_BASE}/in.php", params=params)
        data = resp.json()
        if data.get("status") != 1:
            raise RuntimeError(f"2Captcha submit failed: {data}")

        task_id = data["request"]
        log.info("2Captcha task submitted: %s", task_id)

        # Step 2: Poll for solution
        for _ in range(self.config.timeout // 5):
            await asyncio.sleep(5)
            resp = await self._client.get(
                f"{TWOCAPTCHA_BASE}/res.php",
                params={"key": self.config.api_key, "action": "get", "id": task_id, "json": 1},
            )
            result = resp.json()
            if result.get("status") == 1:
                token = result["request"]
                log.info("2Captcha solved (token length: %d)", len(token))
                return token
            if result.get("request") != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2Captcha error: {result}")

        raise TimeoutError(f"2Captcha solve timed out after {self.config.timeout}s")

    async def _solve_capsolver(
        self,
        sitekey: str,
        page_url: str,
        *,
        version: str = "v2",
        action: str = "verify",
    ) -> str:
        """Submit to CapSolver and poll for result."""
        log.info("Submitting reCAPTCHA %s to CapSolver...", version)

        task_type = (
            "ReCaptchaV3TaskProxyLess" if version == "v3" else "ReCaptchaV2TaskProxyLess"
        )
        task: dict = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": sitekey,
        }
        if version == "v3":
            task["pageAction"] = action
            task["minScore"] = 0.9

        # Step 1: Create task
        resp = await self._client.post(
            f"{CAPSOLVER_BASE}/createTask",
            json={"clientKey": self.config.api_key, "task": task},
        )
        data = resp.json()
        if data.get("errorId", 1) != 0:
            raise RuntimeError(f"CapSolver submit failed: {data}")

        task_id = data["taskId"]
        log.info("CapSolver task submitted: %s", task_id)

        # Step 2: Poll for solution
        for _ in range(self.config.timeout // 3):
            await asyncio.sleep(3)
            resp = await self._client.post(
                f"{CAPSOLVER_BASE}/getTaskResult",
                json={"clientKey": self.config.api_key, "taskId": task_id},
            )
            result = resp.json()
            status = result.get("status")
            if status == "ready":
                token = result["solution"]["gRecaptchaResponse"]
                log.info("CapSolver solved (token length: %d)", len(token))
                return token
            if status != "processing":
                raise RuntimeError(f"CapSolver error: {result}")

        raise TimeoutError(f"CapSolver solve timed out after {self.config.timeout}s")

    async def close(self) -> None:
        await self._client.aclose()
