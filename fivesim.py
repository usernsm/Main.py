"""
5sim.net API wrapper
Docs: https://5sim.net/docs
"""

import time
import requests

BASE_URL = "https://5sim.net/v1"


class FiveSimAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        })

    def get_balance(self) -> dict:
        r = self.session.get(f"{BASE_URL}/user/profile", timeout=15)
        r.raise_for_status()
        data = r.json()
        return {"balance": data.get("balance", 0), "raw": data}

    def get_number(self, country: str = "india", operator: str = "any",
                   product: str = "other") -> dict:
        url = f"{BASE_URL}/user/buy/activation/{country}/{operator}/{product}"
        r = self.session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        return {
            "id": data.get("id"),
            "phone": data.get("phone"),
            "status": data.get("status"),
            "raw": data,
        }

    def get_sms(self, order_id: int) -> list:
        r = self.session.get(f"{BASE_URL}/user/check/{order_id}", timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("sms", [])

    def finish_order(self, order_id: int) -> dict:
        r = self.session.get(f"{BASE_URL}/user/finish/{order_id}", timeout=15)
        r.raise_for_status()
        return r.json()

    def cancel_order(self, order_id: int) -> dict:
        r = self.session.get(f"{BASE_URL}/user/cancel/{order_id}", timeout=15)
        r.raise_for_status()
        return r.json()

    def ban_order(self, order_id: int) -> dict:
        r = self.session.get(f"{BASE_URL}/user/ban/{order_id}", timeout=15)
        r.raise_for_status()
        return r.json()

    def wait_for_sms(self, order_id: int, max_wait: int = 120,
                     poll_interval: int = 5) -> list:
        waited = 0
        while waited < max_wait:
            sms_list = self.get_sms(order_id)
            if sms_list:
                return sms_list
            time.sleep(poll_interval)
            waited += poll_interval
        return []

    def wait_for_all_sms(self, order_id: int, expected_count: int = 2,
                         max_wait: int = 180, poll_interval: int = 5) -> list:
        waited = 0
        while waited < max_wait:
            sms_list = self.get_sms(order_id)
            if len(sms_list) >= expected_count:
                return sms_list
            time.sleep(poll_interval)
            waited += poll_interval
        return self.get_sms(order_id)
