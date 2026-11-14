"""Load test: clients browsing and selecting in a 3,000-photo gallery, studio staff checking in.

Prepare data:  docker compose exec web python manage.py seed_load_test --photos 3000
Run:           uvx locust -f loadtest/locustfile.py --host http://localhost:8099 \
                   --headless -u 60 -r 10 -t 90s
"""

import os
import random

from locust import HttpUser, between, task

PASSWORD = os.environ.get("LOAD_TEST_PASSWORD", "load-test-pass-2026")
PAGE_SIZE = 60


class JsonUser(HttpUser):
    abstract = True

    def csrf_headers(self):
        token = self.client.cookies.get("csrftoken")
        if not token:
            self.client.get("/api/v1/auth/csrf", name="csrf")
            token = self.client.cookies.get("csrftoken")
        return {"X-CSRFToken": token, "Referer": self.host + "/"}

    def post(self, path, body=None, name=None):
        return self.client.post(path, json=body or {}, headers=self.csrf_headers(), name=name)


class GalleryClient(JsonUser):
    """A client on a phone: scrolls pages, opens photos, taps hearts."""

    weight = 5
    wait_time = between(1, 4)

    def on_start(self):
        self.post("/api/v1/client/login", {"username": "loadclient", "password": PASSWORD}, name="client login")
        self.seen = []

    @task(6)
    def scroll(self):
        page = random.randint(1, 3000 // PAGE_SIZE)
        response = self.client.get(f"/api/v1/client/photos?page={page}&page_size={PAGE_SIZE}", name="client photos page")
        if response.ok:
            self.seen = [p["id"] for p in response.json()["results"]]

    @task(2)
    def gallery_info(self):
        self.client.get("/api/v1/client/me", name="client me")

    @task(3)
    def toggle(self):
        if not self.seen:
            return
        photo = random.choice(self.seen)
        headers = self.csrf_headers()
        self.client.put(f"/api/v1/client/selections/{photo}", json={}, headers=headers, name="select")
        self.client.delete(f"/api/v1/client/selections/{photo}", headers=headers, name="unselect")


class StudioStaff(JsonUser):
    """Studio staff watching progress and paging through the event."""

    weight = 1
    wait_time = between(3, 8)

    def on_start(self):
        self.post("/api/v1/auth/login", {"email": "loadowner@loadtest.test", "password": PASSWORD}, name="studio login")
        events = self.client.get("/api/v1/events", name="events").json()
        self.event = next(e["id"] for e in events if e["title"] == "Load test wedding")

    @task(3)
    def progress(self):
        self.client.get(f"/api/v1/events/{self.event}/progress", name="progress")

    @task(2)
    def photos(self):
        page = random.randint(1, 3000 // PAGE_SIZE)
        self.client.get(f"/api/v1/events/{self.event}/photos?page={page}&page_size={PAGE_SIZE}", name="studio photos page")

    @task(1)
    def selection(self):
        self.client.get(f"/api/v1/events/{self.event}/selection", name="selection review")
