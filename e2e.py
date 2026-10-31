"""MomSakhi PR end-to-end run: Firebase emulator (auth + firestore, the PR's rules),
headless Chromium at 390px. Never touches production (emu=1 on 127.0.0.1)."""
import json, os, sys, time, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

PORT = open("/tmp/msemu/port").read().strip()
BASE = "http://127.0.0.1:%s/?emu=1" % PORT
FS = "http://127.0.0.1:8080/v1/projects/aangan-6a58c/databases/(default)/documents"
SHOTS = "/tmp/msemu/shots"; os.makedirs(SHOTS, exist_ok=True)
results = []

def check(ok, what):
    results.append(("PASS" if ok else "FAIL") + "  " + what); print(results[-1], flush=True)

def rest(path, method="GET", body=None, owner=False):
    req = urllib.request.Request(FS + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers=dict({"Content-Type": "application/json"}, **({"Authorization": "Bearer owner"} if owner else {})))
    try:
        with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:200]

# a real JPEG to attach, made with PIL if present, else by the browser
SEED = {"onboarded": True, "city": "Pune", "profile": {"nickname": "Krishan", "fullName": "", "email": "",
        "stages": ["Toddler"], "langs": ["English"]}}

def signed_in_page(b, uid, name):
    ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="http://127.0.0.1:" + PORT)
    seed = dict(SEED, profile=dict(SEED["profile"], nickname=name))
    ctx.add_init_script("if(!localStorage.getItem('aangan.demo.v1'))localStorage.setItem('aangan.demo.v1',%s)" % json.dumps(json.dumps(seed)))
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(BASE + "#home"); pg.wait_for_function("window.Backend && Backend.isReal && Backend._auth")
    pg.evaluate("""async ([uid, name]) => {
      const m = await import('https://www.gstatic.com/firebasejs/10.4.0/firebase-auth.js');
      const cred = m.GoogleAuthProvider.credential(JSON.stringify({sub: uid, email: uid + '@example.com', name: name, email_verified: true}));
      await m.signInWithCredential(Backend._auth, cred);
    }""", [uid, name])
    pg.wait_for_function("Backend.user && Array.isArray(Backend.posts)", timeout=15000)
    if pg.evaluate("location.hash") != "#home": pg.evaluate("location.hash='#home'")
    pg.wait_for_selector(".circles-row")
    return ctx, pg, errs

def snap(pg, name, sel=None, toast=False):
    pg.evaluate("v => { const t = document.getElementById('toast'); if (t) t.style.visibility = v; }", "visible" if toast else "hidden")
    if sel: pg.evaluate("s => { const e = document.querySelector(s); if (e) e.scrollIntoView({block: 'start'}); }", sel)
    time.sleep(0.3); pg.screenshot(path=SHOTS + "/" + name)
    pg.evaluate("() => { const t = document.getElementById('toast'); if (t) t.style.visibility = 'visible'; }")

def compose(pg, kind, title, body, anon=False, photo=None):
    pg.evaluate("location.hash='#ask'"); pg.wait_for_selector("#ask-title")
    if kind: pg.click('[data-act="ask-intent"][data-val="%s"]' % kind)
    pg.fill("#ask-title", title); pg.fill("#ask-body", body)
    if anon: pg.click('[data-act="ask-anon"]')
    if photo:
        pg.set_input_files("#ask-photo-input", photo); pg.wait_for_selector(".photo-preview img")
    pg.click("#ask-post"); pg.wait_for_function("location.hash.indexOf('#q/') === 0", timeout=15000)
    return pg.evaluate("location.hash.slice(3)")

with sync_playwright() as p:
    b = p.chromium.launch()
    # ---------- signed out: nothing readable, #tips lands on welcome
    for path in ("/posts", "/posts/anything"):
        code, _ = rest(path)
        check(code in (403, 404) and code == 403, "signed-out REST %s denied (%s)" % (path, code))
    code, _ = rest(":runQuery", "POST", {"structuredQuery": {"from": [{"collectionId": "posts"}],
        "where": {"fieldFilter": {"field": {"fieldPath": "intent"}, "op": "EQUAL", "value": {"stringValue": "experience"}}}}})
    check(code == 403, "signed-out query for Experience posts denied (%s)" % code)

    ctx, pg, errs = signed_in_page(b, "krishan1", "Krishan")
    # make a photo in the browser (canvas -> jpeg file)
    jpg = pg.evaluate("""() => { const c = document.createElement('canvas'); c.width = 1600; c.height = 1100;
      const x = c.getContext('2d'); const g = x.createLinearGradient(0,0,1600,1100); g.addColorStop(0,'#f6c9a8'); g.addColorStop(1,'#7fb7a8');
      x.fillStyle = g; x.fillRect(0,0,1600,1100); x.fillStyle = '#fff'; x.font = 'bold 120px sans-serif'; x.fillText('Park day', 480, 600);
      return c.toDataURL('image/jpeg', 0.95).split(',')[1]; }""")
    import base64; open("/tmp/msemu/park.jpg", "wb").write(base64.b64decode(jpg))

    pg.screenshot(path=SHOTS + "/01-home-kid-circles.png")
    row = pg.inner_text(".circles-row")
    check(row.index("Newborn") < row.index("Toddlers") < row.index("Kids' health") < row.index("New to the US"), "kid circles first, Sweta's circles kept after")

    pg.evaluate("location.hash='#ask'"); pg.wait_for_selector("#ask-title")
    check("Posting as Krishan" in pg.inner_text(".anon-preview"), "composer starts NOT anonymous")
    pg.click('[data-act="ask-intent"][data-val="experience"]')
    snap(pg, "02-composer-types-anon-off.png", ".chips")

    q = compose(pg, "advice", "Which stroller worked for you?", "Looking at light ones for travel.", photo="/tmp/msemu/park.jpg")
    pg.wait_for_selector("#post-%s .post-photo" % q)
    v = compose(pg, "vent", "Long night, no sleep again", "Just needed to say it somewhere kind.")
    x = compose(pg, "experience", "What finally fixed our bedtime battles", "A fixed 7:30 routine, bath, two books, lights out. Took a week.")
    xa = compose(pg, "experience", "Getting through the first week of daycare", "Short goodbyes and a photo of us in her bag.", anon=True)
    u = None

    # server copies (owner read bypasses rules) -- the photo bug fix proof
    docs = {d["name"].split("/")[-1]: d["fields"] for d in rest("/posts", owner=True)[1].get("documents", [])}
    check(docs[q]["intent"]["stringValue"] == "advice" and docs[v]["intent"]["stringValue"] == "vent" and docs[x]["intent"]["stringValue"] == "experience", "types saved in Firestore")
    check(docs[q].get("photo", {}).get("stringValue", "").startswith("data:image/jpeg;base64,"), "attached photo saved ON the post (%d chars)" % len(docs[q].get("photo", {}).get("stringValue", "")))
    check(docs[xa]["anon"]["booleanValue"] is True and "uid" not in docs[xa] and docs[x]["anon"]["booleanValue"] is False, "anon only when switched on; anon post carries no uid")

    # an untyped legacy post (written as the user would have before this PR), via the SDK
    u = pg.evaluate("""async () => { const r = await Backend.addPost(Backend.user.uid, 'Krishan', false, 'sleep', 'Older post with no type', 'Written before post types.', 'Mom', 'teal', null); return r.id; }""")

    # feed + filter
    pg.evaluate("location.hash='#home'"); pg.wait_for_selector("#post-%s" % u)
    snap(pg, "03-feed-question-with-photo.png", "#post-%s" % q); snap(pg, "03b-feed-tags.png", "#post-%s" % v)
    feed = pg.inner_html(".feed")
    check(all(("post-" + i) in feed for i in (q, v, x, xa, u)), "Fresh today shows every post, untyped one too")
    pg.click('[data-act="home-type"][data-v="question"]'); f = pg.inner_html(".feed")
    check(("post-" + q) in f and ("post-" + u) in f and ("post-" + v) not in f and ("post-" + x) not in f, "Questions filter = Question + untyped")
    pg.click('[data-act="home-type"][data-v="vent"]'); f = pg.inner_html(".feed")
    check(("post-" + v) in f and ("post-" + q) not in f and ("post-" + x) not in f, "Vents filter = vents only")
    snap(pg, "04-filter-vents.png", "#type-filter")
    pg.click('[data-act="home-type"][data-v="all"]')
    pg.click('[data-act="home-seg"][data-v="tips"]'); f = pg.inner_html(".feed")
    check(("post-" + x) in f and ("post-" + xa) in f and ("post-" + q) not in f and ("post-" + v) not in f and ("post-" + u) not in f, "Moms' tips = Experience posts only")
    check(pg.locator(".feed .share-btn").count() == 2 and pg.locator('[data-act="share-post"]').count() == 2, "share button on each Experience post, nowhere else")
    snap(pg, "05-moms-tips.png", ".seg")
    # share: headless Linux Chromium has no navigator.share -> copies the link
    has_share = pg.evaluate("!!navigator.share")
    pg.click('#post-%s [data-act="share-post"]' % x)
    pg.wait_for_function("document.getElementById('toast') && /Link copied/.test(document.getElementById('toast').textContent)", timeout=5000)
    clip = pg.evaluate("navigator.clipboard.readText()")
    check((not has_share) and clip.endswith("#q/" + x), "share fallback copied %s" % clip)
    snap(pg, "06-share-link-copied.png", "#post-%s" % x, toast=True)
    # Web Share path: stub navigator.share and check what goes out
    pg.evaluate("window.__shared = null; navigator.share = (d) => { window.__shared = d; return Promise.resolve(); }")
    pg.click('#post-%s [data-act="share-post"]' % x); sh = pg.evaluate("window.__shared")
    check(sh and sh["url"].endswith("#q/" + x) and "bedtime" not in json.dumps(sh), "Web Share sends link + generic line only: %s" % json.dumps(sh))
    # replies start named
    pg.evaluate("location.hash='#q/%s'" % x); pg.wait_for_selector("#reply-text")
    check("Reply as Krishan" in pg.inner_text(".reply-anon"), "reply box starts NOT anonymous")
    pg.fill("#reply-text", "This helped us too, thank you!"); pg.click("#reply-send")
    pg.wait_for_function("document.querySelectorAll('.answers .answer').length >= 1", timeout=10000)
    for _ in range(20):
        reps = rest("/posts/%s/replies" % x, owner=True)[1].get("documents", [])
        if reps: break
        time.sleep(0.5)
    check(len(reps) == 1 and reps[0]["fields"]["anon"]["booleanValue"] is False, "reply saved named (anon=false)")
    snap(pg, "07-experience-detail-reply.png", ".answers-head")
    # rules: a non-JPEG photo is refused
    bad = pg.evaluate("""async () => { const f = Backend._fs; try { await f.addDoc(f.collection(Backend._db, 'posts'), {uid: Backend.user.uid, author: 'K', anon: false, title: 'x', body: 'y', meta: 'Mom', hue: 'teal', replyCount: 0, photo: 'javascript:alert(1)', createdAt: f.serverTimestamp()}); return 'allowed'; } catch (e) { return e.code; } }""")
    check(bad == "permission-denied", "rules refuse a non-JPEG photo (%s)" % bad)
    check(not errs, "no page errors (signed-in tab): %s" % errs)

    # second mom, fresh browser: photo comes back from the server, existing anon stays anon
    ctx2, pg2, errs2 = signed_in_page(b, "sweta1", "Sweta")
    pg2.wait_for_selector("#post-%s .post-photo" % q, timeout=15000)
    snap(pg2, "08-photo-from-server-other-mom.png", "#post-%s" % q)
    check("Anonymous mom" in pg2.inner_text("#post-%s" % xa), "another mom sees the anon Experience post as Anonymous mom")
    check(not errs2, "no page errors (second mom): %s" % errs2)

    # signed out in the browser: #tips shows the welcome screen, no posts
    ctx3 = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2); pg3 = ctx3.new_page()
    pg3.goto(BASE + "#tips"); pg3.wait_for_function("window.Backend && Backend.isReal"); time.sleep(1.5)
    check(pg3.locator(".post").count() == 0 and pg3.evaluate("!Backend.user"), "signed-out #tips shows no posts, same as signed-out #home today (hash now %s)" % pg3.evaluate("location.hash"))
    pg3.screenshot(path=SHOTS + "/09-signed-out-tips.png")
    b.close()

sys.exit(1 if any(r.startswith("FAIL") for r in results) else 0)
