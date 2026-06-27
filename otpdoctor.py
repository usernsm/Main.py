"""
OTP Doctor API wrapper (sms-activate compatible)
Base: http://otpdoctor.in/stubs/handler_api.php
"""

import re
import time
import logging
import requests

logger = logging.getLogger(__name__)

BASE_URL = "http://otpdoctor.in/stubs/handler_api.php"


class OTPDoctorAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self._service_cache: dict = {}

    def _get(self, params: dict, timeout: int = 15) -> str:
        params = {"api_key": self.api_key, **params}
        r = self.session.get(BASE_URL, params=params, timeout=timeout)
        r.raise_for_status()
        return r.text.strip()

    def get_balance(self) -> float:
        resp = self._get({"action": "getBalance"})
        if resp.startswith("ACCESS_BALANCE:"):
            return float(resp.split(":")[1])
        raise Exception(f"Balance error: {resp}")

    def get_services(self) -> dict:
        import json as _json

        param_variants = [
            {"action": "getServices"},
            {"action": "getServices", "country": "in"},
            {"action": "getServices", "country": "22"},
        ]

        for attempt in range(4):
            params = param_variants[attempt % len(param_variants)]
            try:
                resp = self._get(params, timeout=18)
                if resp.startswith("{"):
                    data = _json.loads(resp)
                    if data:
                        self._service_cache = data
                        logger.info("getServices OK: %d services (attempt %d)", len(data), attempt + 1)
                        return data
                logger.warning("getServices bad response (attempt %d): %s", attempt + 1, resp[:60])
            except Exception as e:
                logger.warning("getServices error (attempt %d): %s", attempt + 1, e)
            time.sleep(3)

        logger.error("getServices failed all attempts — returning cached (%d items)", len(self._service_cache))
        return self._service_cache

    def find_service_id(self, service_name_keyword: str, server_name_keyword: str = "") -> str | None:
        services = self.get_services()
        if not services:
            return None

        keyword_lower = service_name_keyword.lower()
        server_lower  = server_name_keyword.lower()

        for sid, info in services.items():
            sname  = info.get("service_name", "").lower()
            svname = info.get("server_name", "").lower()
            if keyword_lower in sname and (not server_lower or server_lower in svname):
                return sid

        return None

    def get_number(self, service_id: str, country: str = "in") -> dict:
        resp = self._get({
            "action": "getNumber",
            "service": service_id,
            "country": country,
        })
        if resp.startswith("ACCESS_NUMBER:"):
            parts = resp.split(":")
            return {"id": parts[1], "phone": parts[2]}
        raise Exception(f"getNumber error: {resp}")

    def get_status(self, activation_id: str) -> dict:
        resp = self._get({"action": "getStatus", "id": activation_id})
        if resp == "STATUS_WAIT_CODE":
            return {"status": "waiting", "text": None}
        elif resp == "STATUS_CANCEL":
            return {"status": "cancelled", "text": None}
        elif resp.startswith("STATUS_OK:"):
            return {"status": "ok", "text": resp.split(":", 1)[1]}
        elif resp == "STATUS_WAIT_RESEND":
            return {"status": "waiting_resend", "text": None}
        return {"status": "unknown", "raw": resp, "text": None}

    def set_status(self, activation_id: str, status: int) -> str:
        return self._get({"action": "setStatus", "id": activation_id, "status": status})

    def cancel(self, activation_id: str) -> str:
        return self.set_status(activation_id, 6)

    def finish(self, activation_id: str) -> str:
        return self.set_status(activation_id, 3)

    def wait_for_sms(self, activation_id: str, max_wait: int = 120,
                     poll_interval: int = 5) -> str | None:
        waited = 0
        while waited < max_wait:
            try:
                result = self.get_status(activation_id)
                if result["status"] == "ok":
                    return result["text"]
                elif result["status"] == "cancelled":
                    logger.warning("Activation %s cancelled", activation_id)
                    return None
            except Exception as e:
                logger.warning("get_status error: %s", e)
            time.sleep(poll_interval)
            waited += poll_interval
        return None

    def wait_for_second_sms(self, activation_id: str, max_wait: int = 1200,
                             poll_interval: int = 10) -> str | None:
        """
        After first SMS, keep requesting second SMS (voucher) aggressively.
        set_status(8) har 30 sec pe call hoga — max 20 min wait.
        """
        waited = 0
        last_resend = -30  # pehli baar turant set_status(8) call ho

        while waited < max_wait:
            if waited - last_resend >= 30:
                try:
                    self.set_status(activation_id, 8)
                    logger.info("set_status(8) sent (waited=%ds)", waited)
                    last_resend = waited
                except Exception as e:
                    logger.warning("set_status(8) error: %s", e)

            try:
                result = self.get_status(activation_id)
                if result["status"] == "ok":
                    return result["text"]
                elif result["status"] == "cancelled":
                    logger.warning("Activation %s cancelled during 2nd SMS wait", activation_id)
                    return None
            except Exception as e:
                logger.warning("get_status error: %s", e)

            time.sleep(poll_interval)
            waited += poll_interval

        return None


def extract_otp(sms_text: str) -> str | None:
    m = re.search(r'\b(\d{6})\b', sms_text)
    if m:
        return m.group(1)
    m = re.search(r'\b(\d{4})\b', sms_text)
    if m:
        return m.group(1)
    m = re.search(r'\b(\d{8})\b', sms_text)
    if m:
        return m.group(1)
    return None


def extract_voucher(sms_text: str) -> str | None:
    # Uppercase the ASCII part for matching (keeps Marathi chars safe)
    sms_upper = sms_text.upper()

    # ── 1. Marathi/Hindi SMS: "CODE हा कोड वापरा" or "CODE ha code vapra" ──
    m = re.search(r'([A-Z0-9]{8,20})\s+(?:हा\s*कोड|HA\s*KOD)', sms_upper)
    if m:
        return m.group(1)

    # ── 2. Amazon standard gift card: XXXX-XXXXXX-XXXX ──
    m = re.search(r'([A-Z0-9]{4}-[A-Z0-9]{4,6}-[A-Z0-9]{4}(?:-[A-Z0-9]{4})?)', sms_upper)
    if m:
        return m.group(1)

    # ── 3. Keyword-prefixed codes ──
    keyword_patterns = [
        r'(?:AMAZON\s*(?:GIFT\s*CARD|VOUCHER|CODE|GC))[:\s#]*([A-Z0-9]{4,}(?:-[A-Z0-9]{4,})*)',
        r'(?:VOUCHER|GIFT\s*CARD|GIFT\s*CODE|CLAIM\s*CODE|REDEEM)[:\s#]+([A-Z0-9]{4,}(?:-[A-Z0-9]{4,})*)',
        r'CODE\s*[:\s]+([A-Z0-9]{8,})',
    ]
    for pattern in keyword_patterns:
        m = re.search(pattern, sms_upper)
        if m:
            return m.group(1)

    # ── 4. Long alphanumeric block 14-20 chars (no hyphens) ──
    m = re.search(r'(?<![A-Z0-9])([A-Z0-9]{14,20})(?![A-Z0-9])', sms_upper)
    if m:
        return m.group(1)

    # ── 5. Fallback: 10-13 char uppercase alphanumeric ──
    m = re.search(r'(?<![A-Z0-9])([A-Z0-9]{10,13})(?![A-Z0-9])', sms_upper)
    if m:
        return m.group(1)

    return None
