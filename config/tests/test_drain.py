from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from config import drain
from config.drain import DrainingHealthMiddleware


class DrainingHealthMiddlewareTests(SimpleTestCase):
    def setUp(self):
        drain.reset()
        self.addCleanup(drain.reset)
        self.middleware = DrainingHealthMiddleware(lambda _request: HttpResponse("ok"))
        self.factory = RequestFactory()

    @override_settings(WEB_HEALTH_CHECK_PATH="/api/csrf/")
    def test_health_path_serves_normally_until_the_process_drains(self):
        response = self.middleware(self.factory.get("/api/csrf/"))
        assert response.status_code == 200
        assert not drain.is_draining()

    @override_settings(WEB_HEALTH_CHECK_PATH="/api/csrf/")
    def test_health_path_is_503_while_draining_but_other_paths_keep_serving(self):
        drain.begin()

        health = self.middleware(self.factory.get("/api/csrf/"))
        other = self.middleware(self.factory.get("/api/openbase/audio/usage/"))

        assert health.status_code == 503
        assert other.status_code == 200
