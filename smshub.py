"""
smshub.org API wrapper
Docs: https://smshub.org/en/api
"""

import time
import requests

BASE_URL = "https://smshub.org/stubs/handler_api.php"


class SmsHubAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def _get(self, params: dict) -> str:
        params["api_key"] = self.api_key
        r = self.session.get(BASE_URL, params=params, timeout=15)
        r.raise_for_status()
        return r.text.strip()

    def get_balance(self) -> float:
        resp = self._get({"action": "getBalance"})
        if resp.startswith("ACCESS_BALANCE:"):
            return float(resp.split(":")[1])
        raise Exception(f"Balance error: {resp}")

    def get_number(self, service: str = "ot", country: int = 22,
                   operator: str = "any") -> dict:
        params = {
            "action": "getNumber",
            "service": service,
            "country": country,
        }
        if operator != "any":
            params["operator"] = operator
        resp = self._get(params)
        if resp.startswith("ACCESS_NUMBER:"):
            parts = resp.split(":")
            return {"id": int(parts[1]), "phone": parts[2]}
        raise Exception(f"Get number error: {resp}")

    def get_status(self, activation_id: int) -> dict:
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

    def set_status(self, activation_id: int, status: int) -> str:
        resp = self._get({"action": "setStatus", "id": activation_id, "status": status})
        return resp

    def cancel(self, activation_id: int) -> str:
        return self.set_status(activation_id, 6)

    def finish(self, activation_id: int) -> str:
        return self.set_status(activation_id, 3)

    def wait_for_sms(self, activation_id: int, max_wait: int = 120,
                     poll_interval: int = 5) -> str | None:
        waited = 0
        while waited < max_wait:
            result = self.get_status(activation_id)
            if result["status"] == "ok":
                return result["text"]
            elif result["status"] == "cancelled":
                return None
            time.sleep(poll_interval)
            waited += poll_interval
        return None

    def wait_for_second_sms(self, activation_id: int, max_wait: int = 120,
                             poll_interval: int = 5) -> str | None:
        self.set_status(activation_id, 8)
        return self.wait_for_sms(activation_id, max_wait, poll_interval)
