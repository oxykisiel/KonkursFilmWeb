# -*- coding: utf-8 -*-
"""
filmweb_agent.py — Agent konkursów Filmweb (skaner + dzienny limit + CSV + artefakty + filtr zakończonych)
"""
from __future__ import annotations
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from urllib.parse import quote_plus, urljoin
from datetime import datetime, timedelta
import argparse, csv, os, re, time

EMAIL = "mail"
USER_DATA_DIR = "pw_user_filmweb"
LOG_CSV = "filmweb_agent_log.csv"

SENT_STATUSES = {"SENT", "SENT_CONFIRMED", "SENT_UNCONFIRMED"}
LOCAL_OFFSET = timedelta(hours=1)

def today_local_iso() -> str:
    now_utc = datetime.utcnow(); local = now_utc + LOCAL_OFFSET; return local.date().isoformat()

def ensure_log():
    if not os.path.exists(LOG_CSV):
        with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["timestamp","contest_url","question","answer","mode","status","source"])

def log_row(url: str, q: str, a: str, mode: str, status: str, source: str = ""):
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([datetime.now().isoformat(), url, q or "", a or "", mode, status, source or ""])

def count_today_sent() -> int:
    if not os.path.exists(LOG_CSV): return 0
    today = today_local_iso(); cnt = 0
    try:
        with open(LOG_CSV, "r", encoding="utf-8") as f:
            rdr = csv.reader(f); header = next(rdr, None)
            for row in rdr:
                if not row or len(row) < 6: continue
                timestamp = row[0]; status = row[5]; date_part = (timestamp.split("T")[0]).strip()
                if date_part == today and status in SENT_STATUSES: cnt += 1
    except Exception: pass
    return cnt

def normalize_ws(s: str) -> str: return re.sub(r"\s+", " ", s or "").strip()

def first_text_with_question_mark(text: str) -> str | None:
    if not text: return None
    for line in [l.strip() for l in text.splitlines() if l.strip()]:
        if "?" in line and 5 <= len(line) <= 400: return line
    return None

def get_question_from_form(page) -> str | None:
    try:
        ta = page.locator("form textarea").first
        if ta.count() == 0: ta = page.locator("textarea").first
        if ta.count():
            parent = ta.locator("xpath=ancestor::*[self::form or self::section or self::div][1]")
            box_text = normalize_ws(parent.inner_text()); q = first_text_with_question_mark(box_text)
            if q: return q
    except Exception: pass
    try:
        form = page.locator("form").first
        if form.count(): return first_text_with_question_mark(normalize_ws(form.inner_text()))
    except Exception: pass
    try: return first_text_with_question_mark(normalize_ws(page.locator("body").inner_text()))
    except Exception: return None

FACT_PATTERNS = [r"\bw\s*którym\s+roku\b", r"\bkiedy\b", r"\bdata\b", r"\brok\b", r"\bile\b", r"\biloma\b", r"\bil[eao]\s+odcink", r"\breżyser\b", r"\bkto\b", r"\bktóry\b.*\b(rok|sezon|odcinek)\b"]
CREATIVE_HINTS = [r"\buzasadnij\b", r"\bnapisz\b", r"\bdlaczego\b", r"\btwoim zdaniem\b", r"\bopisz\b"]

def classify_question(q: str) -> str:
    ql = (q or "").lower()
    if any(re.search(p, ql) for p in FACT_PATTERNS): return "fact"
    if any(re.search(p, ql) for p in CREATIVE_HINTS): return "creative"
    if any(w in ql for w in ["najlepszy","ulubiony","poleciłbyś","co sądzisz","uzasadnij"]): return "creative"
    return "creative"

def extract_person_or_title(q: str) -> str:
    m_title = re.search(r'‘([^’]+)’|‚([^‚]+)‚|"([^"]+)"|\*([^\*]+)\*', q)
    if m_title:
        for i in range(1, 5):
            if m_title.group(i): return m_title.group(i)
    m_name = re.search(r"([A-ZŻŹĆĄŚĘŁÓŃ][a-zżźćńółęąś]+(?:\s+[A-ZŻŹĆĄŚĘŁÓŃ][a-zżźćńółęąś]+)+)", q)
    return m_name.group(1) if m_name else ""

def generate_creative_answer(q: str, style: str = "medium") -> str:
    ql = (q or "").lower(); ref = extract_person_or_title(q)
    if "jessic" in ql and "chastain" in ql:
        return ("Za najlepszy uważam *Oczy Tammy Faye*. "
                "Chastain imponuje pełną transformacją, ale ważniejsze, że prowadzi postać z empatią i wyczuciem: "
                "od prywatnych pęknięć po publiczny wizerunek. "
                "To rola z kontrolą tonu, dzięki czemu film trzyma emocjonalny rytm. "
                "Dla mnie to najpełniejszy pokaz jej możliwości, co potwierdza też Oscar.")
    thesis = f"Najmocniej przemawia do mnie ten tytuł, w którym {ref or 'postać'} jest grana bez maniery, a film trzyma emocjonalną spójność."
    arg1 = "Doceniam, gdy aktorstwo nie jest popisem dla kamery, tylko służy historii – subtelne gesty mówią więcej niż dialog."
    arg2 = "Ważna jest konsekwencja reżyserska i montaż, które niosą tempo, zamiast je udawać; wtedy nie czuję fałszu."
    close = "Dlatego właśnie ten wybór wydaje mi się najbardziej uczciwy i po prostu trafia we mnie."
    if style == "short": return f"{thesis} {arg1} {close}"
    elif style == "long":
        extra = ("Muzyka i zdjęcia dopełniają ton – gdy nie zagłuszają emocji, pamiętam film długo po seansie. "
                 "Lubię kino, które ufa widzowi bez podpowiadania na każdym kroku.")
        return f"{thesis} {arg1} {arg2} {extra} {close}"
    else: return f"{thesis} {arg1} {arg2} {close}"

def quick_web_fact(context, query: str, timeout_ms: int = 12000) -> tuple[str, str]:
    page = context.new_page(); src = ""; ans = ""
    try:
        url = f"https://www.bing.com/search?q={quote_plus(query)}"; page.goto(url, timeout=timeout_ms); src = url; time.sleep(0.8)
        try:
            box = page.locator("#b_focus, .b_entityTP, .b_focusTextLarge, .b_vList").first
            if box.count():
                txt = normalize_ws(box.inner_text()); m = re.search(r"\b(1[89]\d{2}|20\d{2}|21\d{2})\b", txt)
                ans = m.group(0) if m else (re.search(r"\b\d{1,4}\b", txt).group(0) if re.search(r"\b\d{1,4}\b", txt) else txt.split("\n")[0][:220])
        except Exception: pass
        if not ans:
            try:
                first = page.locator("li.b_algo").first
                if first.count():
                    txt = normalize_ws(first.inner_text()); m = re.search(r"\b(1[89]\d{2}|20\d{2}|21\d{2})\b", txt)
                    if m:
                        ans = m.group(0); link = first.locator("a").first.get_attribute("href"); src = link or src
                    else:
                        lines = [l for l in txt.split("\n") if len(l.strip()) > 5]
                        if lines:
                            ans = lines[0][:220]; link = first.locator("a").first.get_attribute("href"); src = link or src
            except Exception: pass
        if not ans: ans = "Brak pewnej odpowiedzi — proszę o doprecyzowanie."
        return ans, src
    finally:
        try: page.close()
        except Exception: pass

def has_submission_confirmation(page) -> bool:
    try:
        txt = normalize_ws(page.locator("body").inner_text()); pats = [r"dziękujemy", r"twoje zgłoszenie zostało", r"zgłoszenie przyjęte", r"wysłano zgłoszenie", r"thank you"]
        return any(re.search(p, txt, flags=re.IGNORECASE) for p in pats)
    except Exception: return False

def is_contest_active(page) -> bool:
    try:
        txt = normalize_ws(page.locator("body").inner_text())
        ended_patterns = [r"\bkonkurs\s+zakończony\b", r"\bzakończony\b", r"\bzgłoszenia\s+zakończone\b", r"\bdziękujemy\s+za\s+udział\b", r"\bnie\s+przyjmujemy\s+zgłoszeń\b"]
        if any(re.search(p, txt, flags=re.IGNORECASE) for p in ended_patterns): return False
    except Exception: pass
    try:
        btn = page.locator("button:has-text('Wyślij zgłoszenie'), input[type='submit'], button[type='submit']").first
        if btn.count() == 0: return False
        try:
            if btn.get_attribute("disabled") is not None: return False
        except Exception: pass
    except Exception: return False
    return True

def check_all_required_boxes(page):
    try:
        checks = page.locator("form input[type='checkbox']"); cnt = checks.count()
        for i in range(min(6, cnt)):
            cb = checks.nth(i)
            try:
                if cb.is_visible() and not cb.is_checked(): cb.check()
            except Exception:
                try:
                    lbl = cb.locator("xpath=following-sibling::label[1]");
                    if lbl.count(): lbl.click()
                except Exception: pass
    except Exception: pass

def submit_form(page) -> bool:
    for sel in ["button:has-text('Wyślij zgłoszenie')", "text=Wyślij zgłoszenie", "input[type='submit']", "button[type='submit']"]:
        try:
            btn = page.locator(sel).first
            if btn.count(): btn.click(timeout=3000); return True
        except Exception: pass
    return False

def save_artifacts(page, prefix: str):
    try:
        os.makedirs("artifacts", exist_ok=True)
        png = os.path.join("artifacts", f"{prefix}.png"); html = os.path.join("artifacts", f"{prefix}.html")
        page.screenshot(path=png, full_page=True)
        with open(html, "w", encoding="utf-8") as f: f.write(page.content())
        print(f"[ART] Zapisano {png} i {html}")
    except Exception as e: print(f"[ART] Błąd zapisu artefaktów: {e}")

def login_via_google(context, page, email: str, wait_after_s: float = 2.0):
    triggered = False
    for sel in ["text=Zaloguj", "text=Zaloguj się", "button:has-text('Zaloguj')", "[data-test='login'], [data-testid='login']", "a[href*='login']"]:
        try:
            if page.locator(sel).first.count(): page.locator(sel).first.click(timeout=2000); triggered = True; break
        except Exception: pass
    google_clicked = False; popup = None
    for sel in ["text=Google", "button:has-text('Google')", "a:has-text('Google')", "[data-test*='google'], [data-provider='google']", "[href*='google']"]:
        try:
            if page.locator(sel).first.count():
                try:
                    with context.expect_page(timeout=4000) as newp: page.locator(sel).first.click(timeout=2000)
                    popup = newp.value
                except PWTimeout: popup = page
                google_clicked = True; break
        except Exception: pass
    if not google_clicked: popup = page
    try:
        acc = popup.locator(f"text={email}").first
        if acc.count(): acc.click(timeout=3000)
        else:
            try:
                ebox = popup.locator("input[type='email']").first
                if ebox.count(): ebox.fill(email); popup.keyboard.press("Enter")
            except Exception: pass
    except Exception: pass
    try:
        context.pages[0].wait_for_url(re.compile(r"filmweb\.pl"), timeout=30000)
    except Exception: pass
    time.sleep(wait_after_s)

def collect_contests(context, base_url: str = "https://www.filmweb.pl/") -> list[str]:
    page = context.new_page(); urls = set()
    try:
        hubs = ["https://www.filmweb.pl/contests", "https://www.filmweb.pl/contest", "https://www.filmweb.pl/"]
        for hub in hubs:
            try:
                page.goto(hub, timeout=25000); page.wait_for_load_state("domcontentloaded")
            except Exception: continue
            try:
                hrefs = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.href)")
            except Exception: hrefs = []
            for h in hrefs or []:
                if not h: continue
                full = h
                if full.startswith("/"): full = urljoin(base_url, full)
                if "/contest/" in full and full.startswith("https://www.filmweb.pl/contest/"):
                    urls.add(full.split("?")[0])
    finally:
        try: page.close()
        except Exception: pass
    return sorted(urls)

def process_contest(context, url: str, mode: str, style: str, dry_run: bool, save_art: bool) -> str:
    page = context.new_page(); status = "INIT"; source = ""; used_mode = mode
    try:
        page.goto(url, timeout=30000); page.wait_for_load_state("domcontentloaded")
        if not is_contest_active(page):
            status = "SKIPPED_ENDED"; log_row(url, "", "", mode, status, ""); print(f"[SKIP] Konkurs zakończony: {url}"); return status
        q = normalize_ws(get_question_from_form(page) or ""); q_type = classify_question(q); used_mode = ("auto->" + q_type) if mode == "auto" else mode
        if (mode == "auto" and q_type == "creative") or mode == "creative": a = generate_creative_answer(q, style=style)
        else: a, source = quick_web_fact(context, q)
        try:
            ta = page.locator("form textarea").first
            if ta.count(): ta.fill(a)
            else: page.locator("textarea").first.fill(a)
        except Exception: pass
        check_all_required_boxes(page)
        if save_art: save_artifacts(page, prefix=datetime.now().strftime("%Y%m%d_%H%M%S"))
        if dry_run:
            status = "DRY_FILLED"
        else:
            sent = submit_form(page)
            if sent:
                confirmed = has_submission_confirmation(page)
                page.evaluate("""() => { const div=document.createElement('div'); div.textContent='✅ Zgłoszenie wysłane!'; Object.assign(div.style,{position:'fixed',top:'20px',right:'20px',background:'#16a34a',color:'#fff',padding:'10px 16px',borderRadius:'8px',boxShadow:'0 4px 12px rgba(0,0,0,0.2)',zIndex:'999999',fontFamily:'system-ui',fontSize:'14px'}); document.body.appendChild(div); setTimeout(()=>div.remove(),5000);}""")
                try: print("\a")
                except Exception: pass
                status = "SENT_CONFIRMED" if confirmed else "SENT"
            else: status = "NOT_SENT"
        log_row(url, q, a, used_mode, status, source); print(f"[Q] {q}\n[A] {a}\n[mode] {used_mode}  [status] {status}  [src] {source}"); return status
    except Exception as e:
        status = f"ERROR:{type(e).__name__}:{e}"; log_row(url, "", "", used_mode, status, source); print(status); return status
    finally:
        try: page.close()
        except Exception: pass

def run(url: str | None, headless: bool, mode: str, dry_run: bool, force_login: bool, style: str, save_art: bool, scan: bool, max_contests: int, max_daily: int):
    ensure_log()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch_persistent_context(user_data_dir=USER_DATA_DIR, headless=headless, viewport={"width": 1380, "height": 840}, channel="chrome", args=["--disable-blink-features=AutomationControlled","--no-default-browser-check","--no-first-run"], user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"))
        except Exception:
            browser = p.chromium.launch_persistent_context(user_data_dir=USER_DATA_DIR, headless=headless, viewport={"width": 1380, "height": 840}, user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"))
        page = browser.new_page()
        try:
            already = count_today_sent()
            if already >= max_daily: print(f"[LIMIT] Dzisiejszy limit {max_daily} wysyłek już osiągnięty ({already}). Kończę."); return
            if scan:
                contests = collect_contests(browser)
                if not contests: print("[SCAN] Nie znaleziono konkursów."); return
                print(f"[SCAN] Konkursy znalezione ({len(contests)}):")
                for i, cu in enumerate(contests, 1): print(f"  {i}. {cu}")
                processed_non_ended = 0
                for cu in contests:
                    # Sprawdź limit dzienny (liczy tylko SENT_*), zakończone nie wchodzą do limitu
                    today_sent = count_today_sent()
                    if today_sent >= max_daily: print(f"[LIMIT] Osiągnięto {today_sent}/{max_daily} dziennie. Kończę skan."); break
                    print(f"\n>>> Przetwarzam: {cu}")
                    status = process_contest(browser, cu, mode, style, dry_run, save_art)
                    if status == 'SKIPPED_ENDED':
                        # nie liczymy do max_contests, szukamy dalej
                        continue
                    processed_non_ended += 1
                    if processed_non_ended >= max_contests:
                        print(f"[SCAN] Osiągnięto limit aktywnych konkursów: {max_contests}.")
                        break
                return
            else:
                if not url: print("[ERROR] Brak --url i --scan=false. Podaj URL lub włącz skan."); return
                print(f">>> Przetwarzam: {url}")
                if force_login:
                    page.goto(url, timeout=30000); page.wait_for_load_state("domcontentloaded"); login_via_google(browser, page, EMAIL)
                process_contest(browser, url, mode, style, dry_run, save_art)
        finally:
            try: browser.close()
            except Exception: pass

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Agent konkursów Filmweb (skaner + limit dzienny + CSV + artefakty)")
    ap.add_argument("--scan", type=lambda v: v.lower() in ("true","1","yes"), default=True, help="Skanuj Filmweb i przetwarzaj konkursy")
    ap.add_argument("--max-contests", type=int, default=3, help="Maksymalna liczba aktywnych konkursów do przetworzenia")
    ap.add_argument("--max-daily", type=int, default=3, help="Maksymalna liczba wysyłek dziennie")
    ap.add_argument("--url", type=str, default=None, help="URL pojedynczego konkursu (gdy --scan=false)")
    ap.add_argument("--headless", type=lambda v: v.lower() in ("true","1","yes"), default=False, help="Tryb headless")
    ap.add_argument("--mode", type=str, choices=["auto","creative","fact"], default="auto", help="Strategia odpowiedzi")
    ap.add_argument("--dry-run", type=lambda v: v.lower() in ("true","1","yes"), default=False, help="Bez klikania 'Wyślij zgłoszenie'")
    ap.add_argument("--force-login", type=lambda v: v.lower() in ("true","1","yes"), default=False, help="Wymuś ścieżkę logowania przez Google")
    ap.add_argument("--style", type=str, choices=["short","medium","long"], default="medium", help="Długość odpowiedzi w trybie creative")
    ap.add_argument("--save-artifacts", type=lambda v: v.lower() in ("true","1","yes"), default=True, help="Zapisywać zrzut ekranu i HTML po przetwarzaniu")
    args = ap.parse_args()
    run(args.url, args.headless, args.mode, args.dry_run, args.force_login, args.style, args.save_artifacts, args.scan, args.max_contests, args.max_daily)
