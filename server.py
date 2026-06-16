"""
채용공고 웹 서버
- 인터넷 어디서든 접속 가능 (Render 배포 시)
- apps.json을 GitHub 레포에 저장 → 모든 기기에서 영구 동기화
- 업데이트 버튼 → GitHub Actions 워크플로 트리거 → 자동 재배포

환경변수 (Render 대시보드에서 설정):
  GITHUB_TOKEN   : GitHub Personal Access Token (repo 권한)
  GITHUB_REPO    : 레포 이름 (예: username/job-scraper)
  GITHUB_WORKFLOW: 워크플로 파일명 (기본값: scrape.yml)
"""

from flask import Flask, jsonify, request, send_file
import json, os, threading, subprocess, sys, base64, requests as req_lib
from datetime import datetime

app = Flask(__name__)

APPS_FILE  = os.path.join(os.path.dirname(__file__), "apps.json")
HTML_FILE  = os.path.join(os.path.dirname(__file__), "results.html")
SCRAPER    = os.path.join(os.path.dirname(__file__), "scraper.py")

GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO     = os.environ.get("GITHUB_REPO", "")
GITHUB_WORKFLOW = os.environ.get("GITHUB_WORKFLOW", "scrape.yml")
GITHUB_BRANCH   = os.environ.get("GITHUB_BRANCH", "main")

_update_lock   = threading.Lock()
_update_status = {"running": False, "last_updated": None, "message": "대기 중"}


# ── GitHub API 헬퍼 ──────────────────────────────────────
def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

def _gh_get_file(path):
    """GitHub 레포에서 파일 내용과 sha 반환. 없으면 (None, None)."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return None, None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    r = req_lib.get(url, headers=_gh_headers(), params={"ref": GITHUB_BRANCH})
    if r.status_code == 200:
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    return None, None

def _gh_put_file(path, content_str, sha=None, message="Update apps.json"):
    """GitHub 레포에 파일 저장 (생성 또는 업데이트)."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    r = req_lib.put(url, headers=_gh_headers(), json=payload)
    return r.status_code in (200, 201)


# ── 지원 데이터 API ──────────────────────────────────────
def _load():
    # 1순위: GitHub 레포
    if GITHUB_TOKEN and GITHUB_REPO:
        content, _ = _gh_get_file("apps.json")
        if content:
            return json.loads(content)
        return {}
    # 2순위: 로컬 파일 (로컬 실행 시)
    if os.path.exists(APPS_FILE):
        with open(APPS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

def _save(data):
    content_str = json.dumps(data, ensure_ascii=False, indent=2)
    # GitHub 레포에 저장
    if GITHUB_TOKEN and GITHUB_REPO:
        _, sha = _gh_get_file("apps.json")
        _gh_put_file("apps.json", content_str, sha=sha)
    # 로컬에도 항상 저장 (캐시 / 로컬 실행 겸용)
    with open(APPS_FILE, "w", encoding="utf-8") as f:
        f.write(content_str)

@app.route("/api/apps", methods=["GET"])
def get_apps():
    return jsonify(_load())

@app.route("/api/apps", methods=["POST"])
def post_apps():
    _save(request.get_json(force=True))
    return jsonify({"ok": True})


# ── 공고 업데이트 API ────────────────────────────────────
def _trigger_github_actions():
    """GitHub Actions workflow_dispatch 이벤트 트리거."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False, "GITHUB_TOKEN / GITHUB_REPO 환경변수 미설정"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
    r = req_lib.post(url, headers=_gh_headers(), json={"ref": GITHUB_BRANCH})
    if r.status_code == 204:
        return True, "GitHub Actions 워크플로 시작됨 (2~5분 후 자동 반영)"
    return False, f"GitHub API 오류: {r.status_code} {r.text[:200]}"

def _run_local_scraper():
    """로컬 환경에서 직접 스크래퍼 실행."""
    try:
        subprocess.run(
            [sys.executable, SCRAPER, "--no-browser"],
            check=True,
            cwd=os.path.dirname(__file__),
        )
        return True, "완료"
    except Exception as e:
        return False, f"오류: {e}"

@app.route("/api/update", methods=["POST"])
def start_update():
    with _update_lock:
        if _update_status["running"]:
            return jsonify({"ok": False, "message": "이미 업데이트 중입니다."})
        _update_status["running"] = True
        _update_status["message"] = "수집 요청 중..."

    def _run():
        try:
            if GITHUB_TOKEN and GITHUB_REPO:
                ok, msg = _trigger_github_actions()
            else:
                ok, msg = _run_local_scraper()
            with _update_lock:
                _update_status["message"] = msg if ok else f"실패: {msg}"
                if ok:
                    _update_status["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            with _update_lock:
                _update_status["message"] = f"오류: {e}"
        finally:
            with _update_lock:
                _update_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/update/status")
def update_status():
    return jsonify(dict(_update_status))


# ── HTML 서빙 ────────────────────────────────────────────
@app.route("/")
def index():
    if not os.path.exists(HTML_FILE):
        return "<h2>results.html 없음 — 먼저 scraper.py를 실행하거나 GitHub Actions를 실행하세요.</h2>", 404
    return send_file(HTML_FILE)


# ── 실행 ────────────────────────────────────────────────
if __name__ == "__main__":
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "확인불가"

    mode = "GitHub 연동 모드" if (GITHUB_TOKEN and GITHUB_REPO) else "로컬 모드"
    print("=" * 52)
    print(f"  채용공고 서버 시작 [{mode}]")
    print("=" * 52)
    print(f"  이 PC:         http://localhost:5000")
    print(f"  같은 네트워크: http://{local_ip}:5000")
    if GITHUB_REPO:
        print(f"  GitHub 레포:   https://github.com/{GITHUB_REPO}")
    print("  종료: Ctrl+C")
    print("=" * 52)
    app.run(host="0.0.0.0", port=5000, debug=False)
