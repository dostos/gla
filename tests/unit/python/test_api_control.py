"""Tests for /api/v1/control/* endpoints."""


class TestControlPause:
    def test_pause_200(self, client, auth_headers):
        resp = client.post("/api/v1/control/pause", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

    def test_pause_calls_engine(self, client, auth_headers, mock_engine):
        client.post("/api/v1/control/pause", headers=auth_headers)
        mock_engine.pause.assert_called_once()

    def test_pause_no_auth_401(self, client):
        resp = client.post("/api/v1/control/pause")
        assert resp.status_code == 401


class TestControlResume:
    def test_resume_200(self, client, auth_headers):
        resp = client.post("/api/v1/control/resume", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_resume_calls_engine(self, client, auth_headers, mock_engine):
        client.post("/api/v1/control/resume", headers=auth_headers)
        mock_engine.resume.assert_called_once()


class TestControlStep:
    def test_step_default_200(self, client, auth_headers):
        resp = client.post("/api/v1/control/step", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stepped"
        assert data["count"] == 1

    def test_step_custom_count(self, client, auth_headers, mock_engine):
        resp = client.post("/api/v1/control/step?count=5", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 5
        mock_engine.step.assert_called_with(5)


class TestControlStatus:
    def test_status_running_200(self, client, auth_headers, mock_engine):
        mock_engine.is_running.return_value = True
        resp = client.get("/api/v1/control/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "running"
        assert data["is_running"] is True

    def test_status_paused_200(self, client, auth_headers, mock_engine):
        mock_engine.is_running.return_value = False
        resp = client.get("/api/v1/control/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "paused"
        assert data["is_running"] is False

    def test_status_no_auth_401(self, client):
        resp = client.get("/api/v1/control/status")
        assert resp.status_code == 401
