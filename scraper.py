"""
맞춤형 채용공고 스크래퍼
사람인 / 잡코리아 / 원티드 / 잡플래닛 / 게임잡
"""

import yaml
import requests
from bs4 import BeautifulSoup
import json
import time
import re
import webbrowser
import os
from datetime import datetime
from urllib.parse import quote, urlencode

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def should_exclude(title: str, exclude_keywords: list) -> bool:
    return any(kw in title for kw in exclude_keywords)


def emp_type_match(text: str, allowed: list) -> bool:
    if not allowed:
        return True
    return any(t in text for t in allowed)


# ── 사람인 ──────────────────────────────────────────────
def scrape_saramin(cfg) -> list:
    results = []
    search = cfg["search"]
    api_key = cfg.get("saramin_api_key", "").strip()

    for keyword in search["keywords"]:
        try:
            if api_key:
                results += _saramin_api(keyword, search, cfg["max_results_per_site"], api_key)
            else:
                results += _saramin_web(keyword, search, cfg["max_results_per_site"])
            time.sleep(1.2)
        except Exception as e:
            print(f"  [사람인] '{keyword}' 오류: {e}")
    return results


def _saramin_api(keyword, search, limit, api_key) -> list:
    url = "https://oapi.saramin.co.kr/job-search"
    params = {
        "access-key": api_key,
        "keywords": keyword,
        "count": min(limit, 110),
        "sr": "directhire",
        "fields": "posting-date,expiration-date,keyword,salary,position,company",
    }
    if search.get("locations"):
        params["loc_mcd"] = _saramin_loc_code(search["locations"][0])
    r = requests.get(url, params=params, headers=HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for job in data.get("jobs", {}).get("job", []):
        pos = job.get("position", {})
        company = job.get("company", {}).get("detail", {})
        title = pos.get("title", "")
        emp = pos.get("job-type", {}).get("name", "")
        if should_exclude(title, search.get("exclude_keywords", [])):
            continue
        if not emp_type_match(emp, search.get("employment_types", [])):
            continue
        jobs.append({
            "site": "사람인",
            "title": title,
            "company": company.get("name", ""),
            "location": pos.get("location", {}).get("name", ""),
            "experience": pos.get("experience-level", {}).get("name", ""),
            "employment_type": emp,
            "salary": job.get("salary", {}).get("name", ""),
            "deadline": job.get("expiration-date", ""),
            "url": job.get("url", ""),
            "keyword": keyword,
        })
    print(f"  [사람인 API] '{keyword}': {len(jobs)}건")
    return jobs


def _saramin_web(keyword, search, limit) -> list:
    loc = search.get("locations", [""])[0] if search.get("locations") else ""
    params = {
        "searchType": "search",
        "searchword": keyword,
        "loc_mcd": _saramin_loc_code(loc) if loc else "",
        "recruitPage": 1,
        "recruitPageCount": min(limit, 40),
    }
    url = "https://www.saramin.co.kr/zf_user/jobs/list/domestic?" + urlencode(params)
    r = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    jobs = []
    for item in soup.select("ul.list_grand > li.item")[:limit]:
        title_el = item.select_one("strong.tit")
        company_el = item.select_one("span.corp")
        location_el = item.select_one("li.company_local")
        desc_items = item.select("ul.desc > li")
        date_el = item.select_one("span.date")

        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if should_exclude(title, search.get("exclude_keywords", [])):
            continue

        link_el = item.select_one("a[href*='relay/view']")
        href = link_el.get("href", "") if link_el else ""
        full_url = "https://www.saramin.co.kr" + href if href.startswith("/") else href

        # desc[0]=지역, desc[1]=경력, desc[2]=학력 (사람인 목록 페이지)
        exp = desc_items[1].get_text(strip=True) if len(desc_items) > 1 else ""
        emp = ""  # 목록 페이지에서 고용형태 미제공

        jobs.append({
            "site": "사람인",
            "title": title,
            "company": company_el.get_text(strip=True) if company_el else "",
            "location": location_el.get_text(strip=True) if location_el else "",
            "experience": exp,
            "employment_type": emp,
            "salary": "",
            "deadline": date_el.get_text(strip=True) if date_el else "",
            "url": full_url,
            "keyword": keyword,
        })
    print(f"  [사람인] '{keyword}': {len(jobs)}건")
    return jobs


def _saramin_loc_code(loc: str) -> str:
    mapping = {"서울": "101000", "경기": "102000", "인천": "108000", "부산": "106000", "대구": "104000"}
    return mapping.get(loc, "")


# ── 잡코리아 ────────────────────────────────────────────
def scrape_jobkorea(cfg) -> list:
    results = []
    search = cfg["search"]
    for keyword in search["keywords"]:
        try:
            results += _jobkorea_web(keyword, search, cfg["max_results_per_site"])
            time.sleep(1.5)
        except Exception as e:
            print(f"  [잡코리아] '{keyword}' 오류: {e}")
    return results


def _jobkorea_web(keyword, search, limit) -> list:
    url = f"https://www.jobkorea.co.kr/Search/?stext={quote(keyword)}&tabType=recruit&Page_No=1"
    r = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    all_cards = soup.select("div.w-full.rounded-2xl")
    job_cards = [c for c in all_cards if c.select("a[href*='GI_Read']")]

    jobs = []
    for card in job_cards[:limit]:
        links = card.select("a[href*='GI_Read']")
        if not links:
            continue

        spans = card.find_all("span")
        title = ""
        for sp in spans:
            t = sp.get_text(strip=True)
            if t and t != "스크랩" and len(t) > 4:
                title = t
                break

        if not title or should_exclude(title, search.get("exclude_keywords", [])):
            continue

        # company: find span after title
        company = ""
        found_title = False
        for sp in spans:
            t = sp.get_text(strip=True)
            if not found_title and t == title:
                found_title = True
                continue
            if found_title and t and t != title:
                company = t
                break

        # location and experience from all span texts
        loc = exp = emp = ""
        for sp in spans:
            t = sp.get_text(strip=True)
            if not t:
                continue
            for city in ["서울", "경기", "부산", "인천", "대구", "광주", "대전", "제주", "세종"]:
                if city in t and not loc:
                    loc = t
            if re.search(r"경력\s*\d+|신입|경력무관", t) and not exp:
                exp = t
            if re.search(r"정규직|계약직|인턴|프리랜서|아르바이트", t) and not emp:
                emp = t

        deadline_el = card.select_one("time, [class*='date'], [class*='deadline']")
        deadline = deadline_el.get_text(strip=True) if deadline_el else ""

        href = links[0].get("href", "")
        full_url = href if href.startswith("http") else "https://www.jobkorea.co.kr" + href

        jobs.append({
            "site": "잡코리아",
            "title": title,
            "company": company,
            "location": loc,
            "experience": exp,
            "employment_type": emp,
            "salary": "",
            "deadline": deadline,
            "url": full_url,
            "keyword": keyword,
        })

    print(f"  [잡코리아] '{keyword}': {len(jobs)}건")
    return jobs


# ── 원티드 ──────────────────────────────────────────────
def scrape_wanted(cfg) -> list:
    results = []
    search = cfg["search"]
    for keyword in search["keywords"]:
        try:
            results += _wanted_api(keyword, search, cfg["max_results_per_site"])
            time.sleep(1)
        except Exception as e:
            print(f"  [원티드] '{keyword}' 오류: {e}")
    return results


def _wanted_api(keyword, search, limit) -> list:
    headers = {**HEADERS, "Accept": "application/json", "Referer": "https://www.wanted.co.kr/"}
    url = (
        f"https://www.wanted.co.kr/api/v4/jobs"
        f"?country=kr&job_sort=job.latest_order&locations=all"
        f"&limit={min(limit, 100)}&offset=0"
        f"&query={quote(keyword)}"
    )
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()
    raw_jobs = data.get("data") or []

    jobs = []
    for j in raw_jobs:
        title = j.get("position", "")
        if not title or should_exclude(title, search.get("exclude_keywords", [])):
            continue

        company = j.get("company", {}).get("name", "")
        job_id = j.get("id", "")
        full_url = f"https://www.wanted.co.kr/wd/{job_id}" if job_id else ""

        addr = j.get("address", {})
        location = addr.get("location", "") if isinstance(addr, dict) else ""

        annual_from = j.get("annual_from") or 0
        annual_to = j.get("annual_to") or 0
        if annual_from and annual_to:
            experience = f"{annual_from}~{annual_to}년"
        elif annual_from:
            experience = f"{annual_from}년 이상"
        elif annual_to == 0 and annual_from == 0:
            experience = "경력무관"
        else:
            experience = ""

        due = j.get("due_time", "")
        if due:
            due = due[:10]

        jobs.append({
            "site": "원티드",
            "title": title,
            "company": company,
            "location": location,
            "experience": experience,
            "employment_type": "정규직",
            "salary": "",
            "deadline": due,
            "url": full_url,
            "keyword": keyword,
        })

    print(f"  [원티드] '{keyword}': {len(jobs)}건")
    return jobs


# ── 잡플래닛 ────────────────────────────────────────────
def scrape_jobplanet(cfg) -> list:
    """잡플래닛은 JS 렌더링 기반 — HTML에서 기업 링크만 추출"""
    results = []
    search = cfg["search"]
    for keyword in search["keywords"]:
        try:
            results += _jobplanet_web(keyword, search, cfg["max_results_per_site"])
            time.sleep(2)
        except Exception as e:
            print(f"  [잡플래닛] '{keyword}' 오류: {e}")
    return results


def _jobplanet_web(keyword, search, limit) -> list:
    headers = {**HEADERS, "Referer": "https://www.jobplanet.co.kr/"}
    url = f"https://www.jobplanet.co.kr/job/search?q={quote(keyword)}"
    r = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    # 잡플래닛은 SPA — 기업명과 링크만 추출 가능
    company_links = soup.select("a[href*='/companies/']")
    jobs = []
    seen = set()
    for a in company_links[:limit]:
        company = a.get_text(strip=True)
        href = a.get("href", "")
        if not company or company in seen:
            continue
        seen.add(company)
        full_url = "https://www.jobplanet.co.kr" + href if href.startswith("/") else href
        jobs.append({
            "site": "잡플래닛",
            "title": f"{keyword} 채용 (잡플래닛 직접 확인)",
            "company": company,
            "location": "",
            "experience": "",
            "employment_type": "",
            "salary": "",
            "deadline": "",
            "url": full_url + "/jobs",
            "keyword": keyword,
        })

    print(f"  [잡플래닛] '{keyword}': {len(jobs)}건 (기업 링크)")
    return jobs


# ── 게임잡 (Playwright) ──────────────────────────────────
def scrape_gamejob(cfg) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [게임잡] playwright 미설치 — pip install playwright && python -m playwright install chromium")
        return []

    results = []
    search = cfg["search"]
    limit = cfg["max_results_per_site"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            for keyword in search["keywords"]:
                try:
                    results += _gamejob_playwright(page, keyword, search, limit)
                    time.sleep(1)
                except Exception as e:
                    print(f"  [게임잡] '{keyword}' 오류: {e}")
        finally:
            browser.close()

    return results


def _gamejob_playwright(page, keyword, search, limit) -> list:
    from urllib.parse import quote as _quote
    url = f"https://www.gamejob.co.kr/Recruit/joblist?menucode=searchtot&searchtype=all&searchstring={_quote(keyword)}"
    page.goto(url, timeout=15000)
    page.wait_for_load_state("networkidle", timeout=10000)

    soup = BeautifulSoup(page.content(), "html.parser")
    cards = soup.select("li:has(div.description)")

    # 1단계: 목록에서 기본 정보 수집
    stubs = []
    for card in cards[:limit]:
        title_el = card.select_one("div.description > a")
        company_el = card.select_one("div.company a, div.company strong")
        deadline_el = card.select_one("span.dday")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if should_exclude(title, search.get("exclude_keywords", [])):
            continue
        href = title_el.get("href", "")
        full_url = "https://www.gamejob.co.kr" + href if href.startswith("/") else href
        stubs.append({
            "title": title,
            "company": company_el.get_text(strip=True) if company_el else "",
            "deadline": deadline_el.get_text(strip=True) if deadline_el else "",
            "url": full_url,
        })

    # 2단계: 상세 페이지 방문으로 경력/지역/고용형태 추출
    jobs = []
    for stub in stubs:
        try:
            page.goto(stub["url"], timeout=12000)
            page.wait_for_load_state("networkidle", timeout=8000)
            detail = BeautifulSoup(page.content(), "html.parser")

            # dt/dd 쌍에서 정보 추출
            info = {}
            for dt in detail.select("dl dt"):
                dd = dt.find_next_sibling("dd")
                if dd:
                    info[dt.get_text(strip=True)] = dd.get_text(" ", strip=True)

            # li 목록에서도 추출 (사이드바 요약)
            loc = info.get("근무지역", "")
            if not loc:
                loc_el = detail.select_one("a[href*='area'], li:contains('서울'), li:contains('경기')")
                if loc_el:
                    loc = loc_el.get_text(strip=True)

            # 경력 추출
            exp_raw = info.get("경력", "") or info.get("경력조건", "")
            if not exp_raw:
                for li in detail.select("li"):
                    t = li.get_text(strip=True)
                    if re.search(r"^(신입|경력무관|경력\s*\d)", t):
                        exp_raw = t
                        break

            # 고용형태
            emp_raw = info.get("고용형태", "") or info.get("직종", "")
            if not emp_raw:
                for li in detail.select("li"):
                    t = li.get_text(strip=True)
                    if re.search(r"정규직|계약직|인턴|프리랜서", t):
                        emp_raw = t
                        break

            # 지역 정리
            if not loc:
                for li in detail.select("li"):
                    t = li.get_text(strip=True)
                    if re.search(r"서울|경기|부산|인천|대구|대전|광주|제주", t):
                        loc = t
                        break

            jobs.append({
                "site": "게임잡",
                "title": stub["title"],
                "company": stub["company"],
                "location": loc[:20] if loc else "",
                "experience": exp_raw[:20] if exp_raw else "",
                "employment_type": emp_raw[:15] if emp_raw else "",
                "salary": "",
                "deadline": stub["deadline"],
                "url": stub["url"],
                "keyword": keyword,
            })
            time.sleep(0.3)
        except Exception:
            # 상세 페이지 실패 시 기본 정보만
            jobs.append({
                "site": "게임잡",
                "title": stub["title"],
                "company": stub["company"],
                "location": "",
                "experience": "",
                "employment_type": "",
                "salary": "",
                "deadline": stub["deadline"],
                "url": stub["url"],
                "keyword": keyword,
            })

    print(f"  [게임잡] '{keyword}': {len(jobs)}건 (상세정보 포함)")
    return jobs


# ── 중복 제거 ────────────────────────────────────────────
def deduplicate(jobs: list) -> list:
    seen = set()
    unique = []
    for job in jobs:
        key = (job["title"].strip()[:30], job["company"].strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


# ── HTML 생성 ────────────────────────────────────────────
def _normalize_loc(loc: str) -> str:
    if not loc:
        return ""
    for city in ["서울", "경기", "부산", "인천", "대구", "대전", "광주", "울산", "제주", "세종"]:
        if city in loc:
            return city
    return loc.split()[0] if loc.split() else loc


def _normalize_exp(exp: str) -> str:
    if not exp:
        return ""
    if "신입" in exp:
        return "신입"
    if "무관" in exp or "경력무관" in exp:
        return "경력무관"
    m = re.search(r"(\d+)[~\-](\d+)년", exp)
    if m:
        return f"{m.group(1)}~{m.group(2)}년"
    m = re.search(r"(\d+)년", exp)
    if m:
        return f"{m.group(1)}년 이상"
    return exp


SITE_COLORS = {
    "사람인": "#0066CC",
    "잡코리아": "#E8401C",
    "원티드": "#36B3F7",
    "잡플래닛": "#4A90D9",
    "게임잡": "#2ECC71",
}


def _chip(text: str, color: str, bg: str) -> str:
    if not text or text == "-":
        return '<span class="chip chip-empty">미제공</span>'
    return f'<span class="chip" style="color:{color};background:{bg}">{text}</span>'


def _loc_chip(loc: str) -> str:
    if not loc or loc == "-":
        return '<span class="chip chip-empty">미제공</span>'
    # 지역 키워드 색상
    colors = {"서울": ("#1565c0", "#e3f2fd"), "경기": ("#2e7d32", "#e8f5e9"),
              "부산": ("#6a1b9a", "#f3e5f5"), "인천": ("#e65100", "#fff3e0"),
              "대구": ("#880e4f", "#fce4ec"), "광주": ("#01579b", "#e1f5fe"),
              "대전": ("#33691e", "#f1f8e9"), "제주": ("#006064", "#e0f7fa")}
    for city, (fg, bg) in colors.items():
        if city in loc:
            return f'<span class="chip" style="color:{fg};background:{bg}">{loc}</span>'
    return f'<span class="chip" style="color:#37474f;background:#eceff1">{loc}</span>'


def _exp_chip(exp: str) -> str:
    if not exp or exp == "-":
        return '<span class="chip chip-empty">미제공</span>'
    if "신입" in exp:
        return f'<span class="chip" style="color:#1b5e20;background:#c8e6c9">{exp}</span>'
    if "무관" in exp:
        return f'<span class="chip" style="color:#4a148c;background:#e1bee7">{exp}</span>'
    return f'<span class="chip" style="color:#bf360c;background:#fbe9e7">{exp}</span>'


def _emp_chip(emp: str) -> str:
    if not emp or emp == "-":
        return '<span class="chip chip-empty">미제공</span>'
    if "정규" in emp:
        return f'<span class="chip" style="color:#0d47a1;background:#bbdefb">{emp}</span>'
    if "계약" in emp:
        return f'<span class="chip" style="color:#e65100;background:#ffe0b2">{emp}</span>'
    if "인턴" in emp:
        return f'<span class="chip" style="color:#880e4f;background:#fce4ec">{emp}</span>'
    return f'<span class="chip" style="color:#37474f;background:#eceff1">{emp}</span>'


def generate_html(jobs: list, cfg: dict, output_file: str):
    keywords = cfg["search"]["keywords"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sites = sorted({j["site"] for j in jobs})

    # 필터용 고유값 수집
    all_locs = sorted({_normalize_loc(j["location"]) for j in jobs if j["location"]})
    all_exps = sorted({_normalize_exp(j["experience"]) for j in jobs if j["experience"]})
    all_emps = sorted({j["employment_type"] for j in jobs if j["employment_type"]})

    # jobs를 JS에 임베드할 JSON으로 직렬화 (지원현황 탭에서 사용)
    jobs_json = json.dumps([{
        "id": f"{j['site']}|{j['title'][:40]}|{j['company']}",
        "site": j["site"],
        "title": j["title"],
        "company": j["company"],
        "location": j["location"],
        "experience": j["experience"],
        "employment_type": j["employment_type"],
        "deadline": j["deadline"],
        "url": j["url"],
        "keyword": j["keyword"],
    } for j in jobs], ensure_ascii=False)

    rows = ""
    for job in jobs:
        color = SITE_COLORS.get(job["site"], "#666")
        badge = f'<span class="site-badge" style="background:{color}">{job["site"]}</span>'
        if job["url"]:
            title_cell = f'<a href="{job["url"]}" target="_blank" class="job-title">{job["title"]}</a>'
        else:
            title_cell = f'<span class="job-title-plain">{job["title"]}</span>'
        kw_badge = f'<span class="kw-badge">{job["keyword"]}</span>'

        loc_n = _normalize_loc(job["location"])
        exp_n = _normalize_exp(job["experience"])
        jid = json.dumps(f"{job['site']}|{job['title'][:40]}|{job['company']}", ensure_ascii=False)

        deadline_val = job['deadline'] or ''
        rows += f"""
        <tr data-site="{job['site']}" data-keyword="{job['keyword']}"
            data-loc="{loc_n}" data-exp="{exp_n}" data-emp="{job['employment_type']}"
            data-id={jid} data-deadline="{deadline_val}">
          <td>{badge}</td>
          <td class="td-title">{title_cell}<br>{kw_badge}</td>
          <td>{job['company'] or '-'}</td>
          <td>{_loc_chip(job['location'])}</td>
          <td>{_exp_chip(job['experience'])}</td>
          <td>{_emp_chip(job['employment_type'])}</td>
          <td class="td-dead" data-deadline-cell>{job['deadline'] or '-'}</td>
          <td style="white-space:nowrap;vertical-align:middle">
            <button class="apply-btn" data-id={jid} onclick="toggleApply(this)">지원하기</button>
            <button class="bookmark-btn" data-id={jid} onclick="toggleBookmark(this)" title="북마크">☆</button>
            <button class="hide-btn" data-id={jid} onclick="hideJob(this)" title="숨기기">✕</button>
            <button class="memo-toggle-btn" data-id={jid} onclick="toggleJobMemo(this)">메모</button>
          </td>
        </tr>
        <tr class="job-memo-row" data-memo-for={jid} style="display:none">
          <td colspan="8" style="padding:4px 12px 8px 40px;background:#fafafa">
            <textarea class="job-memo-ta" data-id={jid} rows="2" placeholder="이 공고에 대한 메모를 남겨보세요..."
              onblur="saveJobMemo(this)" style="width:100%;max-width:600px;border:1px solid #e2e5ea;border-radius:6px;padding:6px 8px;font-size:12px;font-family:inherit;resize:vertical;outline:none"></textarea>
          </td>
        </tr>"""

    site_btns = f'<button class="filter-btn active" data-filter="all" data-type="site">전체 {len(jobs)}건</button>'
    for site in sites:
        cnt = sum(1 for j in jobs if j["site"] == site)
        c = SITE_COLORS.get(site, "#666")
        site_btns += f'<button class="filter-btn" data-filter="{site}" data-type="site" style="--c:{c}">{site} {cnt}</button>'

    kw_opts = '<option value="all">전체 키워드</option>'
    for kw in keywords:
        kw_opts += f'<option value="{kw}">{kw}</option>'

    loc_opts = '<option value="all">전체 지역</option>'
    for loc in all_locs:
        loc_opts += f'<option value="{loc}">{loc}</option>'

    exp_opts = '<option value="all">전체 경력</option>'
    for exp in all_exps:
        exp_opts += f'<option value="{exp}">{exp}</option>'

    emp_opts = '<option value="all">전체 고용형태</option>'
    for emp in all_emps:
        emp_opts += f'<option value="{emp}">{emp}</option>'

    stat_html = "".join(
        f'<div class="stat"><strong>{sum(1 for j in jobs if j["site"]==s)}</strong>{s}</div>'
        for s in sites
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>맞춤 채용공고 {now}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; background: #f0f2f5; color: #222; }}

  /* ── 헤더 ── */
  header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: white; padding: 20px 32px 0; }}
  header h1 {{ font-size: 22px; font-weight: 700; }}
  header p {{ font-size: 12px; color: #8899bb; margin-top: 4px; }}
  .stats {{ display: flex; gap: 12px; margin-top: 14px; flex-wrap: wrap; }}
  .stat {{ background: rgba(255,255,255,.12); border-radius: 10px; padding: 9px 16px; font-size: 12px; }}
  .stat strong {{ display: block; font-size: 22px; font-weight: 700; }}

  /* ── 탭 ── */
  .tab-bar {{ display: flex; gap: 0; margin-top: 18px; }}
  .tab-btn {{
    padding: 10px 24px; font-size: 13px; font-family: inherit; cursor: pointer;
    border: none; background: rgba(255,255,255,.1); color: rgba(255,255,255,.6);
    border-radius: 8px 8px 0 0; margin-right: 4px; transition: all .15s; font-weight: 500;
    position: relative;
  }}
  .tab-btn.active {{ background: #f0f2f5; color: #1a1a2e; font-weight: 700; }}
  .tab-badge {{
    display: inline-block; background: #e8401c; color: white;
    border-radius: 10px; padding: 1px 6px; font-size: 10px; margin-left: 5px; vertical-align: middle;
  }}

  /* ── 탭 패널 ── */
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}

  /* ── 공고 탭 컨트롤 ── */
  .controls {{
    background: white; padding: 12px 32px; border-bottom: 1px solid #e2e5ea;
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,.06);
  }}
  .controls-row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; width: 100%; }}
  .controls-row + .controls-row {{ padding-top: 8px; border-top: 1px solid #f0f2f5; }}
  .filter-btn {{
    border: 1.5px solid #dde0e8; background: white; border-radius: 18px;
    padding: 6px 14px; cursor: pointer; font-size: 12px; transition: all .15s;
    font-family: inherit; white-space: nowrap;
  }}
  .filter-btn:hover {{ border-color: var(--c, #333); color: var(--c, #333); }}
  .filter-btn.active {{ background: var(--c, #1a1a2e); color: white; border-color: var(--c, #1a1a2e); font-weight: 600; }}
  .filter-btn[data-filter="all"].active {{ background: #1a1a2e; border-color: #1a1a2e; }}
  select {{
    border: 1.5px solid #dde0e8; border-radius: 8px;
    padding: 6px 10px; font-size: 12px; font-family: inherit; outline: none; cursor: pointer;
  }}
  select:focus {{ border-color: #4a90d9; }}
  input[type=text] {{
    border: 1.5px solid #dde0e8; border-radius: 8px;
    padding: 6px 12px; font-size: 12px; font-family: inherit; outline: none; width: 200px;
  }}
  input:focus {{ border-color: #4a90d9; }}

  /* ── 공통 테이블 ── */
  .container {{ padding: 16px 32px 32px; }}
  .count {{ font-size: 12px; color: #888; margin-bottom: 10px; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.07); }}
  th {{
    background: #1a1a2e; color: #b0bdd0; padding: 11px 12px;
    text-align: left; font-size: 12px; font-weight: 500; white-space: nowrap;
  }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #f0f2f5; font-size: 13px; vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f7f9ff; }}
  tr.hidden {{ display: none; }}

  /* ── 뱃지/칩 ── */
  .site-badge {{
    display: inline-block; padding: 3px 8px; border-radius: 5px;
    font-size: 11px; color: white; font-weight: 700; white-space: nowrap;
  }}
  .kw-badge {{
    display: inline-block; margin-top: 4px; padding: 2px 6px;
    background: #eef2ff; color: #4a6cf7; border-radius: 4px; font-size: 11px;
  }}
  .job-title {{ color: #1a1a2e; font-weight: 600; text-decoration: none; line-height: 1.45; font-size: 13px; }}
  .job-title:hover {{ color: #2563eb; text-decoration: underline; }}
  .job-title-plain {{ color: #1a1a2e; font-weight: 600; font-size: 13px; }}
  .td-title {{ max-width: 280px; }}
  .td-dead {{ white-space: nowrap; font-size: 12px; color: #666; }}
  .chip {{ display: inline-block; padding: 3px 9px; border-radius: 20px; font-size: 12px; font-weight: 500; white-space: nowrap; }}
  .chip-empty {{ background: #f5f5f5; color: #bbb; font-size: 11px; }}
  .sep {{ color: #dde0e8; font-size: 16px; }}

  /* ── 지원하기 버튼 ── */
  .apply-btn {{
    border: 1.5px solid #dde0e8; background: white; border-radius: 8px;
    padding: 5px 12px; font-size: 12px; cursor: pointer; font-family: inherit;
    white-space: nowrap; transition: all .15s; color: #555;
  }}
  .apply-btn:hover {{ border-color: #2563eb; color: #2563eb; }}
  .apply-btn.applied {{ background: #2563eb; color: white; border-color: #2563eb; }}

  /* ── 지원현황 탭 ── */
  .app-controls {{
    background: white; padding: 12px 32px; border-bottom: 1px solid #e2e5ea;
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    position: sticky; top: 0; z-index: 100; box-shadow: 0 2px 8px rgba(0,0,0,.06);
  }}
  .status-filter-btn {{
    border: 1.5px solid #dde0e8; background: white; border-radius: 18px;
    padding: 6px 14px; cursor: pointer; font-size: 12px; transition: all .15s;
    font-family: inherit; white-space: nowrap;
  }}
  .status-filter-btn.active {{ background: #1a1a2e; color: white; border-color: #1a1a2e; font-weight: 600; }}

  .status-sel {{
    border: 1.5px solid #dde0e8; border-radius: 8px; padding: 5px 8px;
    font-size: 12px; font-family: inherit; cursor: pointer; outline: none;
  }}
  .status-chip {{
    display: inline-block; padding: 3px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600; white-space: nowrap;
  }}
  .s-applied   {{ background: #dbeafe; color: #1d4ed8; }}
  .s-docs      {{ background: #fef9c3; color: #854d0e; }}
  .s-interview {{ background: #ede9fe; color: #6d28d9; }}
  .s-final     {{ background: #dcfce7; color: #15803d; }}
  .s-pass      {{ background: #d1fae5; color: #065f46; }}
  .s-fail      {{ background: #fee2e2; color: #b91c1c; }}
  .s-hold      {{ background: #f3f4f6; color: #6b7280; }}

  .memo-cell {{ max-width: 200px; }}
  .memo-input {{
    width: 100%; border: 1px solid #e2e5ea; border-radius: 6px;
    padding: 4px 8px; font-size: 12px; font-family: inherit; resize: none; outline: none;
    background: transparent; color: #444;
  }}
  .memo-input:focus {{ border-color: #93c5fd; background: white; }}

  .del-btn {{
    border: none; background: none; color: #ccc; cursor: pointer;
    font-size: 16px; padding: 2px 6px; border-radius: 4px; transition: color .15s;
  }}
  .del-btn:hover {{ color: #ef4444; }}

  .empty-state {{
    text-align: center; padding: 60px 0; color: #aaa; font-size: 14px;
  }}
  .empty-state p {{ margin-top: 8px; font-size: 12px; }}

  /* ── 상단 요약 카드 (지원현황) ── */
  .app-summary {{
    display: flex; gap: 12px; padding: 16px 32px 4px; flex-wrap: wrap;
  }}
  .app-sum-card {{
    background: white; border-radius: 10px; padding: 12px 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,.07); text-align: center; min-width: 90px;
  }}
  .app-sum-card strong {{ display: block; font-size: 24px; font-weight: 700; }}
  .app-sum-card span {{ font-size: 11px; color: #888; }}

  /* ── 북마크/숨기기/메모 버튼 ── */
  .bookmark-btn {{
    border: none; background: none; font-size: 16px; cursor: pointer; padding: 2px 4px;
    color: #ccc; transition: color .15s; vertical-align: middle;
  }}
  .bookmark-btn.bookmarked {{ color: #f59e0b; }}
  .hide-btn {{
    border: none; background: none; font-size: 13px; cursor: pointer; padding: 2px 5px;
    color: #ccc; border-radius: 4px; transition: color .15s; vertical-align: middle;
  }}
  .hide-btn:hover {{ color: #ef4444; }}
  .memo-toggle-btn {{
    border: 1px solid #dde0e8; background: #f7f8fa; border-radius: 6px;
    padding: 3px 8px; font-size: 11px; cursor: pointer; font-family: inherit;
    color: #888; transition: all .15s; vertical-align: middle;
  }}
  .memo-toggle-btn.has-memo {{ border-color: #93c5fd; color: #2563eb; background: #eff6ff; }}
  .memo-toggle-btn.has-memo::after {{ content: '•'; margin-left: 2px; color: #2563eb; }}
  /* ── 숨긴 공고 ── */
  tr.job-hidden {{ opacity: 0.4; background: #f9f9f9; }}
  tr.job-hidden td {{ color: #aaa; }}
  /* ── D-day 칩 ── */
  .dday-chip {{
    display: inline-block; padding: 1px 6px; border-radius: 10px;
    font-size: 11px; font-weight: 700; margin-left: 4px; white-space: nowrap;
  }}
  .dday-red {{ background: #fee2e2; color: #b91c1c; }}
  .dday-orange {{ background: #ffedd5; color: #c2410c; }}
  .dday-yellow {{ background: #fef9c3; color: #854d0e; }}
  .dday-green {{ background: #dcfce7; color: #15803d; }}
  /* ── 면접 임박 배너 ── */
  .interview-alert {{
    background: #fef9c3; border-left: 4px solid #f59e0b; padding: 10px 20px;
    margin: 8px 32px 0; border-radius: 8px; font-size: 13px; color: #78350f;
    cursor: pointer; display: flex; align-items: center; gap: 8px;
  }}
  .interview-alert:hover {{ background: #fef08a; }}

  @media (max-width: 900px) {{
    .container, header, .controls, .app-controls, .app-summary {{ padding-left: 14px; padding-right: 14px; }}
    th, td {{ padding: 8px; font-size: 11px; }}
    input[type=text] {{ width: 110px; }}
    .td-title {{ max-width: 140px; }}
  }}
</style>
</head>
<body>
<header>
  <h1>맞춤 채용공고 스크래퍼</h1>
  <p>수집: {now} &nbsp;|&nbsp; 키워드: {', '.join(keywords)}</p>
  <div class="stats">
    <div class="stat"><strong>{len(jobs)}</strong>총 공고</div>
    {stat_html}
  </div>
  <div class="tab-bar">
    <button class="tab-btn active" data-tab="jobs">공고 목록</button>
    <button class="tab-btn" data-tab="applied">내 지원 현황 <span class="tab-badge" id="appliedBadge">0</span></button>
    <div style="margin-left:auto;display:flex;align-items:center;gap:10px;padding-bottom:4px">
      <span id="updateMsg" style="font-size:11px;color:#8899bb"></span>
      <button id="updateBtn" onclick="triggerUpdate()" style="background:rgba(255,255,255,.15);color:white;border:1px solid rgba(255,255,255,.3);border-radius:8px;padding:7px 16px;font-size:12px;cursor:pointer;font-family:inherit;font-weight:600;transition:all .2s">공고 업데이트</button>
    </div>
  </div>
</header>

<!-- ════════ 공고 목록 탭 ════════ -->
<div class="tab-panel active" id="tab-jobs">
  <div class="controls">
    <div class="controls-row">
      <span style="font-size:11px;color:#999;white-space:nowrap">사이트</span>
      {site_btns}
      <span class="sep">|</span>
      <select id="kwFilter">{kw_opts}</select>
      <input type="text" id="search" placeholder="회사명/직무 검색...">
    </div>
    <div class="controls-row">
      <span style="font-size:11px;color:#999;white-space:nowrap">필터</span>
      <select id="locFilter">{loc_opts}</select>
      <select id="expFilter">{exp_opts}</select>
      <select id="empFilter">{emp_opts}</select>
      <button id="resetBtn" style="margin-left:auto;border:1px solid #dde0e8;background:#f7f8fa;border-radius:8px;padding:6px 12px;font-size:11px;cursor:pointer;font-family:inherit">초기화</button>
    </div>
    <div class="controls-row">
      <span style="font-size:11px;color:#999;white-space:nowrap">기타</span>
      <button id="bookmarkOnlyBtn" class="filter-btn" onclick="toggleBookmarkOnly()" title="북마크한 공고만 보기">⭐ 관심만 보기</button>
      <button id="deadlineBtn" class="filter-btn" onclick="toggleDeadlineFilter()" title="마감 7일 이내">마감임박 (D-7)</button>
      <label style="font-size:12px;color:#555;display:flex;align-items:center;gap:4px;cursor:pointer">
        <input type="checkbox" id="showHiddenChk" onchange="applyFilter()"> 숨긴 공고 표시
      </label>
    </div>
  </div>
  <div class="container">
    <p class="count" id="count">{len(jobs)}개 공고 표시 중</p>
    <table id="jobTable">
      <thead>
        <tr>
          <th>사이트</th><th>직무 / 키워드</th><th>회사</th>
          <th>지역</th><th>경력</th><th>고용형태</th><th>마감일</th><th>지원</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>

<!-- ════════ 지원 현황 탭 ════════ -->
<div class="tab-panel" id="tab-applied">
  <div class="app-controls">
    <button class="status-filter-btn active" data-sf="all">전체</button>
    <button class="status-filter-btn" data-sf="지원완료">지원완료</button>
    <button class="status-filter-btn" data-sf="서류검토">서류검토</button>
    <button class="status-filter-btn" data-sf="면접예정">면접예정</button>
    <button class="status-filter-btn" data-sf="최종합격">최종합격</button>
    <button class="status-filter-btn" data-sf="불합격">불합격</button>
    <button class="status-filter-btn" data-sf="보류">보류</button>
    <button onclick="exportCSV()" style="background:#16a34a;color:white;border:none;border-radius:8px;padding:7px 14px;font-size:12px;cursor:pointer;font-family:inherit;font-weight:600">CSV 내보내기</button>
    <button id="openAddBtn" style="margin-left:auto;background:#2563eb;color:white;border:none;border-radius:8px;padding:7px 16px;font-size:12px;cursor:pointer;font-family:inherit;font-weight:600">+ 직접 추가</button>
  </div>

  <!-- 직접 추가 폼 -->
  <div id="addForm" style="display:none;background:white;border-bottom:1px solid #e2e5ea;padding:16px 32px;">
    <div style="font-size:13px;font-weight:700;margin-bottom:12px;color:#1a1a2e">공고 직접 추가</div>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
      <div style="display:flex;flex-direction:column;gap:4px;flex:2;min-width:200px">
        <label style="font-size:11px;color:#888">공고 링크 (선택)</label>
        <input id="af-url" type="text" placeholder="https://..." style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;flex:2;min-width:160px">
        <label style="font-size:11px;color:#888">직무명 *</label>
        <input id="af-title" type="text" placeholder="예) UI/UX 디자이너" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;flex:1;min-width:120px">
        <label style="font-size:11px;color:#888">회사명 *</label>
        <input id="af-company" type="text" placeholder="예) 카카오" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;flex:1;min-width:100px">
        <label style="font-size:11px;color:#888">사이트</label>
        <input id="af-site" type="text" placeholder="예) 링크드인" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;flex:1;min-width:100px">
        <label style="font-size:11px;color:#888">마감일</label>
        <input id="af-deadline" type="text" placeholder="예) 07.31" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;flex:1;min-width:110px">
        <label style="font-size:11px;color:#888">지원일</label>
        <input id="af-applied" type="date" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none;height:36px">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;flex:1;min-width:100px">
        <label style="font-size:11px;color:#888">초기 상태</label>
        <select id="af-status" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none;height:36px">
          <option>지원완료</option><option>서류검토</option><option>면접예정</option>
          <option>최종합격</option><option>불합격</option><option>보류</option>
        </select>
      </div>
      <div style="display:flex;gap:8px;padding-bottom:1px">
        <button id="af-submit" style="background:#2563eb;color:white;border:none;border-radius:8px;padding:7px 20px;font-size:13px;cursor:pointer;font-family:inherit;font-weight:600;white-space:nowrap">추가</button>
        <button id="af-cancel" style="background:#f3f4f6;color:#555;border:none;border-radius:8px;padding:7px 14px;font-size:13px;cursor:pointer;font-family:inherit">취소</button>
      </div>
    </div>
    <div id="af-err" style="display:none;color:#ef4444;font-size:12px;margin-top:8px"></div>
  </div>

  <div id="interviewAlerts"></div>
  <div class="app-summary" id="appSummary"></div>
  <div class="container">
    <div id="appEmpty" class="empty-state" style="display:none">
      <div style="font-size:40px">📋</div>
      <strong>아직 지원한 공고가 없어요</strong>
      <p>공고 목록에서 "지원하기" 버튼을 누르거나, "+ 직접 추가"로 넣을 수 있어요.</p>
    </div>
    <table id="appTable" style="display:none">
      <thead>
        <tr>
          <th>사이트</th><th>직무</th><th>회사</th>
          <th>마감일</th><th>지원일 ✏️</th><th>면접일정 ✏️</th><th>진행상태</th><th>결과/메모 ✏️</th><th></th>
        </tr>
      </thead>
      <tbody id="appTbody"></tbody>
    </table>
  </div>
</div>

<!-- 수정 모달 -->
<div id="editModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:1000;align-items:center;justify-content:center">
  <div style="background:white;border-radius:16px;padding:28px 32px;width:min(520px,90vw);box-shadow:0 8px 40px rgba(0,0,0,0.18)">
    <div style="font-size:15px;font-weight:700;margin-bottom:20px;color:#1a1a2e">지원 기록 수정</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <div style="display:flex;flex-direction:column;gap:4px;grid-column:span 2">
        <label style="font-size:11px;color:#888">공고 링크</label>
        <input id="em-url" type="text" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <label style="font-size:11px;color:#888">직무명 *</label>
        <input id="em-title" type="text" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <label style="font-size:11px;color:#888">회사명 *</label>
        <input id="em-company" type="text" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <label style="font-size:11px;color:#888">사이트</label>
        <input id="em-site" type="text" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <label style="font-size:11px;color:#888">마감일</label>
        <input id="em-deadline" type="text" placeholder="예) 07.31" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <label style="font-size:11px;color:#888">지원일</label>
        <input id="em-applied" type="date" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <label style="font-size:11px;color:#888">면접일정</label>
        <input id="em-interview" type="date" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none">
      </div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <label style="font-size:11px;color:#888">진행상태</label>
        <select id="em-status" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none;height:36px">
          <option>지원완료</option><option>서류검토</option><option>면접예정</option>
          <option>최종합격</option><option>불합격</option><option>보류</option>
        </select>
      </div>
      <div style="display:flex;flex-direction:column;gap:4px;grid-column:span 2">
        <label style="font-size:11px;color:#888">결과/메모</label>
        <textarea id="em-memo" rows="3" style="border:1.5px solid #dde0e8;border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;outline:none;resize:vertical"></textarea>
      </div>
    </div>
    <div id="em-err" style="display:none;color:#ef4444;font-size:12px;margin-top:8px"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:20px">
      <button onclick="closeEditModal()" style="background:#f3f4f6;color:#555;border:none;border-radius:8px;padding:8px 20px;font-size:13px;cursor:pointer;font-family:inherit">취소</button>
      <button onclick="submitEdit()" style="background:#2563eb;color:white;border:none;border-radius:8px;padding:8px 24px;font-size:13px;cursor:pointer;font-family:inherit;font-weight:600">저장</button>
    </div>
  </div>
</div>

<script>
// ── 공고 데이터 ──
const JOBS = {jobs_json};

// ── 서버 모드 감지 (file:// 면 localStorage 폴백) ──
const IS_SERVER = location.protocol !== 'file:';
const LS_KEY = 'jobApps_v1';

let APPS = {{}};  // 메모리 캐시

async function loadApps() {{
  if (IS_SERVER) {{
    try {{
      const r = await fetch('/api/apps');
      APPS = await r.json();
    }} catch {{ APPS = {{}}; }}
    // 서버에 데이터 없고 로컬에 이전 데이터 있으면 복구 배너 표시
    if (Object.keys(APPS).length === 0) {{
      try {{
        const local = JSON.parse(localStorage.getItem(LS_KEY) || '{{}}');
        if (Object.keys(local).length > 0) {{
          showRecoverBanner(local);
        }}
      }} catch {{}}
    }}
  }} else {{
    try {{ APPS = JSON.parse(localStorage.getItem(LS_KEY) || '{{}}'); }} catch {{ APPS = {{}}; }}
  }}
  return APPS;
}}

function showRecoverBanner(localData) {{
  const cnt = Object.keys(localData).length;
  const banner = document.createElement('div');
  banner.id = 'recoverBanner';
  banner.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#1e40af;color:white;padding:16px 20px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.3);z-index:9999;font-size:13px;max-width:340px;line-height:1.5';
  banner.innerHTML = `<div style="font-weight:700;margin-bottom:8px">이전 지원 데이터 발견 (${{cnt}}개)</div>
    <div style="font-size:12px;color:#bfdbfe;margin-bottom:12px">이 브라우저 로컬에 저장된 지원 현황이 있어요. 서버로 복구하시겠어요?</div>
    <div style="display:flex;gap:8px">
      <button onclick="recoverLocalData()" style="background:#3b82f6;color:white;border:none;border-radius:8px;padding:7px 16px;font-size:12px;cursor:pointer;font-weight:600;font-family:inherit">복구하기</button>
      <button onclick="document.getElementById('recoverBanner').remove()" style="background:rgba(255,255,255,.15);color:white;border:none;border-radius:8px;padding:7px 12px;font-size:12px;cursor:pointer;font-family:inherit">닫기</button>
    </div>`;
  document.body.appendChild(banner);
}}

async function recoverLocalData() {{
  try {{
    const local = JSON.parse(localStorage.getItem(LS_KEY) || '{{}}');
    APPS = local;
    await saveApps();
    document.getElementById('recoverBanner')?.remove();
    updateBadge();
    alert('복구 완료! 지원 현황 탭에서 확인하세요.');
  }} catch(e) {{
    alert('복구 실패: ' + e.message);
  }}
}}

async function saveApps() {{
  if (IS_SERVER) {{
    await fetch('/api/apps', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(APPS),
    }});
  }} else {{
    localStorage.setItem(LS_KEY, JSON.stringify(APPS));
  }}
}}

// ── D-day 계산 ──
function parseDday(deadlineStr) {{
  if (!deadlineStr || deadlineStr === '-') return null;
  const today = new Date(); today.setHours(0,0,0,0);
  let m, day, month, year = today.getFullYear();
  // "~MM.DD" or "MM.DD" or "MM/DD"
  m = deadlineStr.match(/(\d{{1,2}})[./](\d{{1,2}})/);
  if (!m) return null;
  month = parseInt(m[1], 10) - 1;
  day   = parseInt(m[2], 10);
  let d = new Date(year, month, day);
  if (d < today) d = new Date(year + 1, month, day);
  return Math.round((d - today) / 86400000);
}}

function renderDday(deadlineStr) {{
  const d = parseDday(deadlineStr);
  if (d === null) return '';
  let cls = 'dday-green', label = 'D-' + d;
  if (d === 0) {{ cls = 'dday-red'; label = 'D-day'; }}
  else if (d <= 3) cls = 'dday-red';
  else if (d <= 7) cls = 'dday-orange';
  else if (d <= 14) cls = 'dday-yellow';
  return `<span class="dday-chip ${{cls}}">${{label}}</span>`;
}}

function initDdays() {{
  document.querySelectorAll('#jobTable tbody tr[data-deadline]').forEach(row => {{
    const dl = row.dataset.deadline;
    const cell = row.querySelector('[data-deadline-cell]');
    if (cell && dl) cell.innerHTML = (cell.textContent.trim() || dl) + renderDday(dl);
  }});
}}

// ── 북마크 ──
let bookmarkOnly = false;
function toggleBookmarkOnly() {{
  bookmarkOnly = !bookmarkOnly;
  const btn = document.getElementById('bookmarkOnlyBtn');
  btn.classList.toggle('active', bookmarkOnly);
  applyFilter();
}}

function toggleBookmark(btn) {{
  const id = btn.dataset.id;
  if (!APPS[id]) {{
    // create a stub entry just for bookmark
    const job = JOBS.find(j => j.id === id);
    if (!job) return;
    APPS[id] = {{ ...job, bookmarked: true, hidden: false, jobMemo: '',
      appliedDate: '', interviewDate: '', result: '', status: '', memo: '' }};
  }} else {{
    APPS[id].bookmarked = !APPS[id].bookmarked;
  }}
  btn.classList.toggle('bookmarked', !!APPS[id].bookmarked);
  btn.textContent = APPS[id].bookmarked ? '★' : '☆';
  saveApps();
}}

// ── 공고 숨기기 ──
function hideJob(btn) {{
  const id = btn.dataset.id;
  const job = JOBS.find(j => j.id === id);
  if (!APPS[id]) {{
    APPS[id] = {{ ...(job || {{}}), bookmarked: false, hidden: true, jobMemo: '',
      appliedDate: '', interviewDate: '', result: '', status: '', memo: '' }};
  }} else {{
    APPS[id].hidden = true;
  }}
  saveApps();
  applyFilter();
}}

// ── 공고 메모 ──
function toggleJobMemo(btn) {{
  const id = btn.dataset.id;
  const memoRow = document.querySelector(`.job-memo-row[data-memo-for="${{id}}"]`);
  if (!memoRow) return;
  const visible = memoRow.style.display !== 'none';
  memoRow.style.display = visible ? 'none' : '';
  if (!visible) {{
    const ta = memoRow.querySelector('.job-memo-ta');
    if (ta && APPS[id] && APPS[id].jobMemo) ta.value = APPS[id].jobMemo;
    ta && ta.focus();
  }}
}}

async function saveJobMemo(ta) {{
  const id = ta.dataset.id;
  const job = JOBS.find(j => j.id === id);
  if (!APPS[id]) {{
    APPS[id] = {{ ...(job || {{}}), bookmarked: false, hidden: false, jobMemo: ta.value,
      appliedDate: '', interviewDate: '', result: '', status: '', memo: '' }};
  }} else {{
    APPS[id].jobMemo = ta.value;
  }}
  await saveApps();
  // update memo button indicator
  const memoBtn = document.querySelector(`.memo-toggle-btn[data-id="${{id}}"]`);
  if (memoBtn) memoBtn.classList.toggle('has-memo', !!ta.value);
}}

// ── 마감임박 필터 ──
let deadlineFilterOn = false;
function toggleDeadlineFilter() {{
  deadlineFilterOn = !deadlineFilterOn;
  document.getElementById('deadlineBtn').classList.toggle('active', deadlineFilterOn);
  applyFilter();
}}

// ── CSV 내보내기 ──
function exportCSV() {{
  const rows = Object.values(APPS).filter(a => a.status);
  if (rows.length === 0) {{ alert('지원 기록이 없습니다.'); return; }}
  const headers = ['직무명','회사','사이트','마감일','지원일','면접일정','진행상태','메모'];
  const lines = [headers.join(',')];
  rows.forEach(a => {{
    const cols = [a.title, a.company, a.site, a.deadline, a.appliedDate, a.interviewDate, a.status, a.memo||''];
    lines.push(cols.map(c => '"' + (c||'').replace(/"/g, '""') + '"').join(','));
  }});
  const bom = '﻿';
  const blob = new Blob([bom + lines.join('\r\n')], {{ type: 'text/csv;charset=utf-8;' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url;
  a.download = '지원현황_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click(); URL.revokeObjectURL(url);
}}

// ── 면접 임박 배너 ──
function renderInterviewAlerts() {{
  const container = document.getElementById('interviewAlerts');
  if (!container) return;
  const today = new Date(); today.setHours(0,0,0,0);
  const tomorrow = new Date(today); tomorrow.setDate(tomorrow.getDate() + 1);
  const alerts = Object.values(APPS).filter(a => {{
    if (!a.interviewDate) return false;
    const d = new Date(a.interviewDate); d.setHours(0,0,0,0);
    return d.getTime() === today.getTime() || d.getTime() === tomorrow.getTime();
  }});
  container.innerHTML = alerts.map(a => {{
    const d = new Date(a.interviewDate); d.setHours(0,0,0,0);
    const when = d.getTime() === today.getTime() ? '오늘' : '내일';
    const safeId = a.id.replace(/['"<>&]/g, c => ({{"'":"&#39;",'"':'&quot;','<':'&lt;','>':'&gt;','&':'&amp;'}}[c]));
    return `<div class="interview-alert" onclick="scrollToAppRow('${{safeId}}')">
      ⚠️ [${{a.company}} - ${{a.title}}] 면접이 ${{when}}입니다!
    </div>`;
  }}).join('');
}}

function scrollToAppRow(id) {{
  const rows = document.querySelectorAll('#appTbody tr');
  for (const row of rows) {{
    const sel = row.querySelector(`[data-id="${{id}}"]`);
    if (sel) {{ row.scrollIntoView({{behavior:'smooth', block:'center'}}); break; }}
  }}
}}

// ── 지원 통계 추가 ──
function renderAppSummaryExtra(counts, total) {{
  const summary = document.getElementById('appSummary');
  const interviewed = (counts['면접예정']||0) + (counts['최종합격']||0);
  const passed = counts['최종합격'] || 0;
  const validTotal = total.filter(a => a.status).length;
  const passRate = validTotal > 0 ? Math.round(interviewed / validTotal * 100) : 0;
  const interviewRate = (counts['지원완료']||0) + (counts['서류검토']||0) + interviewed > 0
    ? Math.round(interviewed / validTotal * 100) : 0;
  summary.innerHTML += `
    <div class="app-sum-card"><strong style="color:#7c3aed">${{passRate}}%</strong><span>서류통과율</span></div>
    <div class="app-sum-card"><strong style="color:#0891b2">${{interviewRate}}%</strong><span>면접전환율</span></div>
  `;
}}

// ── 공고 업데이트 ──
let _pollTimer = null;
async function triggerUpdate() {{
  const btn = document.getElementById('updateBtn');
  const msg = document.getElementById('updateMsg');
  if (!IS_SERVER) {{
    alert('서버 모드(python server.py)에서만 사용 가능합니다.');
    return;
  }}
  btn.disabled = true;
  btn.textContent = '업데이트 중...';
  msg.textContent = '';
  try {{
    await fetch('/api/update', {{ method: 'POST' }});
    _pollTimer = setInterval(async () => {{
      const s = await (await fetch('/api/update/status')).json();
      msg.textContent = s.message + (s.last_updated ? ' (' + s.last_updated + ')' : '');
      if (!s.running) {{
        clearInterval(_pollTimer);
        btn.disabled = false;
        btn.textContent = '공고 업데이트';
        if (s.message === '완료') {{
          msg.textContent = '완료! 잠시 후 새로고침됩니다...';
          setTimeout(() => location.reload(), 1500);
        }}
      }}
    }}, 3000);
  }} catch (e) {{
    btn.disabled = false;
    btn.textContent = '공고 업데이트';
    msg.textContent = '서버 연결 실패';
  }}
}}

// ── 탭 전환 ──
document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'applied') renderAppTable();
  }});
}});

// ── 지원하기 버튼 ──
async function toggleApply(btn) {{
  const id = btn.dataset.id;
  if (APPS[id]) {{
    if (!confirm('지원 기록을 삭제할까요?')) return;
    delete APPS[id];
    btn.classList.remove('applied');
    btn.textContent = '지원하기';
  }} else {{
    const job = JOBS.find(j => j.id === id);
    APPS[id] = {{
      ...job,
      appliedDate: new Date().toISOString().slice(0,10),
      interviewDate: '',
      result: '',
      status: '지원완료',
      memo: '',
    }};
    btn.classList.add('applied');
    btn.textContent = '지원완료 ✓';
  }}
  await saveApps();
  updateBadge();
}}

function updateBadge() {{
  document.getElementById('appliedBadge').textContent = Object.keys(APPS).length;
}}

// ── 지원 현황 테이블 ──
const STATUS_LIST = ['지원완료','서류검토','면접예정','최종합격','불합격','보류'];
const STATUS_CLS  = {{'지원완료':'s-applied','서류검토':'s-docs','면접예정':'s-interview',
                      '최종합격':'s-final','불합격':'s-fail','보류':'s-hold'}};
const SITE_COL    = {{'사람인':'#0066CC','잡코리아':'#E8401C','원티드':'#36B3F7','잡플래닛':'#4A90D9','게임잡':'#2ECC71'}};

let appStatusFilter = 'all';

function renderAppTable() {{
  const entries = Object.values(APPS).filter(a =>
    appStatusFilter === 'all' || a.status === appStatusFilter
  );
  const tbody   = document.getElementById('appTbody');
  const empty   = document.getElementById('appEmpty');
  const tbl     = document.getElementById('appTable');
  const summary = document.getElementById('appSummary');
  const total   = Object.values(APPS);

  // 요약 카드
  const counts = {{}};
  STATUS_LIST.forEach(s => counts[s] = 0);
  total.forEach(a => {{ if (counts[a.status] !== undefined) counts[a.status]++; }});
  const sumColors = {{'지원완료':'#1d4ed8','서류검토':'#854d0e','면접예정':'#6d28d9','최종합격':'#065f46','불합격':'#b91c1c','보류':'#6b7280'}};
  summary.innerHTML =
    `<div class="app-sum-card"><strong>${{total.length}}</strong><span>총 지원</span></div>` +
    STATUS_LIST.map(s =>
      `<div class="app-sum-card"><strong style="color:${{sumColors[s]||'#333'}}">${{counts[s]}}</strong><span>${{s}}</span></div>`
    ).join('');
  renderAppSummaryExtra(counts, total);
  renderInterviewAlerts();

  if (entries.length === 0) {{
    empty.style.display = '';
    tbl.style.display = 'none';
    empty.innerHTML = total.length === 0
      ? '<div style="font-size:40px">📋</div><strong>아직 지원한 공고가 없어요</strong><p>공고 목록에서 "지원하기" 또는 "+ 직접 추가"를 이용하세요.</p>'
      : '<div style="font-size:40px">🔍</div><strong>해당 상태의 공고가 없어요</strong>';
    return;
  }}
  empty.style.display = 'none';
  tbl.style.display = '';

  tbody.innerHTML = entries.map(a => {{
    const sc       = STATUS_CLS[a.status] || 's-hold';
    const siteCol  = SITE_COL[a.site] || '#888';
    const isManual = a.keyword === '직접입력';
    const titleCell = a.url
      ? `<a href="${{a.url}}" target="_blank" class="job-title">${{a.title}}</a>`
      : `<span class="job-title-plain">${{a.title}}</span>`;
    const opts = STATUS_LIST.map(s =>
      `<option value="${{s}}" ${{a.status===s?'selected':''}}>${{s}}</option>`
    ).join('');
    const safeId = a.id.replace(/['"<>&]/g, c => ({{"'":"&#39;",'"':'&quot;','<':'&lt;','>':'&gt;','&':'&amp;'}}[c]));
    return `<tr data-sf="${{a.status}}">
      <td><span class="site-badge" style="background:${{siteCol}};${{isManual?'border:1.5px dashed #aaa':''}}">${{a.site}}</span></td>
      <td class="td-title">${{titleCell}}<br><span style="font-size:11px;color:#999">${{a.company||''}}</span></td>
      <td class="td-dead">${{a.deadline||'-'}}</td>
      <td>
        <input type="date" class="date-input" value="${{a.appliedDate||''}}"
          data-id="${{safeId}}" data-field="appliedDate" onchange="saveField(this)"
          title="지원일 수정">
      </td>
      <td>
        <input type="date" class="date-input" value="${{a.interviewDate||''}}"
          data-id="${{safeId}}" data-field="interviewDate" onchange="saveField(this)"
          placeholder="면접일" title="면접 일정">
      </td>
      <td>
        <span class="status-chip ${{sc}}">${{a.status}}</span>
        <select class="status-sel" data-id="${{safeId}}" onchange="changeStatus(this)" style="margin-top:4px;display:block">
          ${{opts}}
        </select>
      </td>
      <td class="memo-cell">
        <textarea class="memo-input" rows="2" placeholder="결과 메모 (면접 후기, 탈락 사유 등...)"
          data-id="${{safeId}}" onblur="saveField(this)" data-field="memo">${{a.memo||''}}</textarea>
      </td>
      <td style="white-space:nowrap">
        <button class="edit-btn" data-id="${{safeId}}" onclick="openEditModal(this.dataset.id)" title="수정" style="background:#f3f4f6;border:none;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:12px;margin-bottom:4px;display:block;width:100%">✏️ 수정</button>
        <button class="del-btn" data-id="${{safeId}}" onclick="deleteApp(this.dataset.id)">✕</button>
      </td>
    </tr>`;
  }}).join('');
}}

async function saveField(el) {{
  const id    = el.dataset.id;
  const field = el.dataset.field;
  if (!APPS[id]) return;
  APPS[id][field] = el.value;
  await saveApps();
  if (field === 'status') renderAppTable();
}}

async function changeStatus(sel) {{
  const id = sel.dataset.id;
  if (!APPS[id]) return;
  APPS[id].status = sel.value;
  await saveApps();
  renderAppTable();
}}

// ── 수정 모달 ──
let _editingId = null;
function openEditModal(id) {{
  const a = APPS[id];
  if (!a) return;
  _editingId = id;
  document.getElementById('em-url').value       = a.url || '';
  document.getElementById('em-title').value     = a.title || '';
  document.getElementById('em-company').value   = a.company || '';
  document.getElementById('em-site').value      = a.site || '';
  document.getElementById('em-deadline').value  = a.deadline || '';
  document.getElementById('em-applied').value   = a.appliedDate || '';
  document.getElementById('em-interview').value = a.interviewDate || '';
  document.getElementById('em-status').value    = a.status || '지원완료';
  document.getElementById('em-memo').value      = a.memo || '';
  document.getElementById('em-err').style.display = 'none';
  const modal = document.getElementById('editModal');
  modal.style.display = 'flex';
}}
function closeEditModal() {{
  document.getElementById('editModal').style.display = 'none';
  _editingId = null;
}}
async function submitEdit() {{
  if (!_editingId || !APPS[_editingId]) return;
  const title   = document.getElementById('em-title').value.trim();
  const company = document.getElementById('em-company').value.trim();
  if (!title || !company) {{
    const err = document.getElementById('em-err');
    err.textContent = '직무명과 회사명은 필수입니다.';
    err.style.display = '';
    return;
  }}
  APPS[_editingId] = {{
    ...APPS[_editingId],
    url:           document.getElementById('em-url').value.trim(),
    title,
    company,
    site:          document.getElementById('em-site').value.trim() || APPS[_editingId].site,
    deadline:      document.getElementById('em-deadline').value.trim(),
    appliedDate:   document.getElementById('em-applied').value,
    interviewDate: document.getElementById('em-interview').value,
    status:        document.getElementById('em-status').value,
    memo:          document.getElementById('em-memo').value,
  }};
  await saveApps();
  closeEditModal();
  renderAppTable();
}}
// 모달 바깥 클릭 시 닫기
document.getElementById('editModal').addEventListener('click', function(e) {{
  if (e.target === this) closeEditModal();
}});

async function deleteApp(id) {{
  if (!confirm('지원 기록을 삭제할까요?')) return;
  delete APPS[id];
  await saveApps();
  document.querySelectorAll(`.apply-btn[data-id="${{id}}"]`).forEach(btn => {{
    btn.classList.remove('applied');
    btn.textContent = '지원하기';
  }});
  updateBadge();
  renderAppTable();
}}

// ── 직접 추가 폼 ──
document.getElementById('openAddBtn').addEventListener('click', () => {{
  const f = document.getElementById('addForm');
  f.style.display = f.style.display === 'none' ? '' : 'none';
}});
document.getElementById('af-cancel').addEventListener('click', () => {{
  document.getElementById('addForm').style.display = 'none';
  document.getElementById('af-err').style.display = 'none';
}});
document.getElementById('af-submit').addEventListener('click', async () => {{
  const title    = document.getElementById('af-title').value.trim();
  const company  = document.getElementById('af-company').value.trim();
  const url      = document.getElementById('af-url').value.trim();
  const site     = document.getElementById('af-site').value.trim() || '직접입력';
  const deadline = document.getElementById('af-deadline').value.trim();
  const status   = document.getElementById('af-status').value;
  const applied  = document.getElementById('af-applied').value || new Date().toISOString().slice(0,10);
  const err      = document.getElementById('af-err');

  if (!title || !company) {{
    err.textContent = '직무명과 회사명은 필수입니다.'; err.style.display = ''; return;
  }}
  err.style.display = 'none';

  const id = 'manual|' + title.slice(0,40) + '|' + company + '|' + Date.now();
  APPS[id] = {{
    id, site, title, company,
    location: '', experience: '', employment_type: '',
    deadline, url, keyword: '직접입력',
    appliedDate: applied,
    interviewDate: '', result: '', status, memo: '',
  }};
  await saveApps();
  updateBadge();
  renderAppTable();

  ['af-url','af-title','af-company','af-site','af-deadline','af-applied'].forEach(i => document.getElementById(i).value = '');
  document.getElementById('addForm').style.display = 'none';
}});
document.getElementById('af-url').addEventListener('paste', () => {{
  setTimeout(() => document.getElementById('af-title').focus(), 50);
}});

// 상태 필터 버튼
document.querySelectorAll('.status-filter-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.status-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    appStatusFilter = btn.dataset.sf;
    renderAppTable();
  }});
}});

// ── 공고 목록 필터 ──
const allRows = Array.from(document.querySelectorAll('#jobTable tbody tr[data-id]'));
const countEl = document.getElementById('count');
let state = {{ site: 'all', kw: 'all', loc: 'all', exp: 'all', emp: 'all', q: '' }};

function applyFilter() {{
  const showHidden = document.getElementById('showHiddenChk').checked;
  let n = 0;
  allRows.forEach(r => {{
    if (!r.dataset.id) return; // skip memo rows
    const id = r.dataset.id;
    const appData = APPS[id] || {{}};
    const isHidden = appData.hidden === true;
    const isBookmarked = appData.bookmarked === true;
    // hidden logic
    if (isHidden) {{
      if (!showHidden) {{ r.classList.add('hidden'); r.nextElementSibling && r.nextElementSibling.classList.contains('job-memo-row') && (r.nextElementSibling.style.display='none'); return; }}
      r.classList.add('job-hidden');
    }} else {{
      r.classList.remove('job-hidden');
    }}
    // deadline filter
    let ddOk = true;
    if (deadlineFilterOn) {{
      const d = parseDday(r.dataset.deadline);
      ddOk = d !== null && d <= 7 && d >= 0;
    }}
    const ok =
      (state.site === 'all' || r.dataset.site === state.site) &&
      (state.kw   === 'all' || r.dataset.keyword === state.kw) &&
      (state.loc  === 'all' || r.dataset.loc.includes(state.loc)) &&
      (state.exp  === 'all' || r.dataset.exp === state.exp) &&
      (state.emp  === 'all' || r.dataset.emp === state.emp) &&
      (!state.q   || r.textContent.toLowerCase().includes(state.q)) &&
      (!bookmarkOnly || isBookmarked) &&
      ddOk;
    r.classList.toggle('hidden', !ok);
    if (ok) n++;
  }});
  countEl.textContent = n + '개 공고 표시 중';
}}
document.querySelectorAll('.filter-btn[data-filter]').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.filter-btn[data-filter]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.site = btn.dataset.filter;
    applyFilter();
  }});
}});
document.getElementById('kwFilter').addEventListener('change', e => {{ state.kw = e.target.value; applyFilter(); }});
document.getElementById('locFilter').addEventListener('change', e => {{ state.loc = e.target.value; applyFilter(); }});
document.getElementById('expFilter').addEventListener('change', e => {{ state.exp = e.target.value; applyFilter(); }});
document.getElementById('empFilter').addEventListener('change', e => {{ state.emp = e.target.value; applyFilter(); }});
document.getElementById('search').addEventListener('input', e => {{ state.q = e.target.value.toLowerCase(); applyFilter(); }});
document.getElementById('resetBtn').addEventListener('click', () => {{
  state = {{ site: 'all', kw: 'all', loc: 'all', exp: 'all', emp: 'all', q: '' }};
  bookmarkOnly = false; deadlineFilterOn = false;
  document.getElementById('bookmarkOnlyBtn').classList.remove('active');
  document.getElementById('deadlineBtn').classList.remove('active');
  document.getElementById('showHiddenChk').checked = false;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.filter-btn[data-filter="all"]').classList.add('active');
  ['kwFilter','locFilter','expFilter','empFilter'].forEach(id => document.getElementById(id).value = 'all');
  document.getElementById('search').value = '';
  applyFilter();
}});

// ── date-input 스타일 ──
const dStyle = document.createElement('style');
dStyle.textContent = `.date-input{{border:1px solid #e2e5ea;border-radius:6px;padding:4px 6px;font-size:11px;font-family:inherit;color:#444;width:130px;cursor:pointer}}.date-input:focus{{outline:none;border-color:#93c5fd}}`;
document.head.appendChild(dStyle);

// ── 초기화 ──
(async function init() {{
  await loadApps();
  Object.keys(APPS).forEach(id => {{
    const appData = APPS[id];
    // 지원하기 버튼 복원
    const btn = document.querySelector(`.apply-btn[data-id="${{id}}"]`);
    if (btn && appData.status) {{ btn.classList.add('applied'); btn.textContent = '지원완료 ✓'; }}
    // 북마크 복원
    const bkBtn = document.querySelector(`.bookmark-btn[data-id="${{id}}"]`);
    if (bkBtn && appData.bookmarked) {{ bkBtn.classList.add('bookmarked'); bkBtn.textContent = '★'; }}
    // 메모 버튼 dot 복원
    const memoBtn = document.querySelector(`.memo-toggle-btn[data-id="${{id}}"]`);
    if (memoBtn && appData.jobMemo) {{ memoBtn.classList.add('has-memo'); }}
  }});
  // 숨긴 공고 처리 (applyFilter가 처리)
  updateBadge();
  initDdays();
  applyFilter();
}})();
</script>
</body>
</html>"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n결과 저장: {output_file}")


# ── 메인 ────────────────────────────────────────────────
def main(no_browser=False):
    cfg = load_config()
    print("=" * 52)
    print("   맞춤 채용공고 수집 시작")
    print("=" * 52)

    all_jobs = []
    sites_cfg = cfg.get("sites", {})

    if sites_cfg.get("saramin", True):
        print("\n[사람인] 수집 중...")
        all_jobs += scrape_saramin(cfg)

    if sites_cfg.get("jobkorea", True):
        print("\n[잡코리아] 수집 중...")
        all_jobs += scrape_jobkorea(cfg)

    if sites_cfg.get("wanted", True):
        print("\n[원티드] 수집 중...")
        all_jobs += scrape_wanted(cfg)

    if sites_cfg.get("jobplanet", True):
        print("\n[잡플래닛] 수집 중... (JS 기반, 기업 링크만)")
        all_jobs += scrape_jobplanet(cfg)

    if sites_cfg.get("gamejob", True):
        print("\n[게임잡] 수집 중... (Playwright 브라우저)")
        all_jobs += scrape_gamejob(cfg)

    all_jobs = deduplicate(all_jobs)
    print(f"\n총 {len(all_jobs)}개 공고 수집 (중복 제거 완료)")

    output_file = cfg.get("output", {}).get("filename", "results.html")
    generate_html(all_jobs, cfg, output_file)

    if not no_browser and cfg.get("output", {}).get("open_browser", True):
        webbrowser.open(os.path.abspath(output_file))


if __name__ == "__main__":
    import sys as _sys
    no_browser = "--no-browser" in _sys.argv
    main(no_browser=no_browser)
