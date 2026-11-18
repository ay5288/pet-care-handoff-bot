import os, re, math, datetime, urllib.parse, requests
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, FollowEvent, TextMessage, LocationMessage, ImageMessage,
    TextSendMessage, FlexSendMessage, BubbleContainer, CarouselContainer,
    ImageComponent, BoxComponent, TextComponent, ButtonComponent, URIAction, MessageAction
)

app = FastAPI()
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

# ⚠️ 1. 請填入「汪喵寵物照護資料庫」的 Google Apps Script /exec 網址
GOOGLE_SHEET_API = "https://script.google.com/macros/s/AKfycbyXqSsQ5exQq4T-i4t4DzCwMIX15fo_NB3J66Ixodax5ktO0WT7MobhRDKoOwLJN4j8ZQ/exec"
# ⚠️ 2. 請填入寵物機器人的 LINE 官方帳號 ID（包含 @ 符號，例如 @123abcde）
LINE_BOT_BASIC_ID = "@650tsvlz"
# ⚠️ 3. 請確認這個寵物機器人的 Render 公開網址（結尾不要加斜線）
RENDER_BASE_URL = "https://pet-care-handoff-bot.onrender.com"
# ⚠️ 4. 可填入您的 Notion 寵物嚴選好物變現頁面網址（未填時自動隱藏購物按鈕）
NOTION_PET_SHOP_URL = ""

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

PET_MAP_HTML = """<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="referrer" content="no-referrer">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"/>
<title>汪喵居家守護與周邊急診獸醫院地圖</title>
<style>
  body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif; background: #F8F9FA; color: #1A1B1E; }
  .header { background: #1A1B1E; color: #fff; padding: 14px 16px; font-weight: bold; font-size: 15px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }
  .map-viewport { width: 100%; height: 300px; overflow: hidden; position: relative; background: #E9ECEF; border-bottom: 1px solid #DEE2E6; }
  .map-canvas { width: 768px; height: 768px; position: absolute; left: 50%; top: 50%; transform: translate(__OFFSET_X__px, __OFFSET_Y__px); }
  .tile-grid { display: grid; grid-template-columns: repeat(3, 256px); grid-template-rows: repeat(3, 256px); width: 768px; height: 768px; }
  .tile-grid img { width: 256px; height: 256px; display: block; }
  .overlay-svg { position: absolute; top: 0; left: 0; width: 768px; height: 768px; pointer-events: none; }
  .box { padding: 16px; max-width: 600px; margin: 0 auto; }
  .card { background: #fff; border-radius: 20px; padding: 18px; margin-bottom: 14px; box-shadow: 0 8px 24px rgba(0,0,0,0.06); }
  .title { font-weight: 700; font-size: 16px; color: #1A1B1E; margin-bottom: 6px; }
  .meta { font-size: 13px; color: #666; line-height: 1.5; margin-bottom: 14px; }
  .btn { display: block; width: 100%; box-sizing: border-box; text-align: center; text-decoration: none; padding: 14px; border-radius: 14px; font-size: 15px; font-weight: bold; color: #fff; margin-bottom: 10px; }
  .btn-red { background: linear-gradient(135deg, #FF6B6B, #FA5252); }
  .btn-green { background: linear-gradient(135deg, #20C997, #12B886); }
  .btn-blue { background: linear-gradient(135deg, #339AF0, #228BE6); }
</style>
</head><body>
<div class="header"><span>🐾 汪喵守護 · 醫療與協尋地圖</span><span style="font-size:11px;background:#FF6B4A;padding:3px 10px;border-radius:12px;">1km 守護圈</span></div>
<div class="map-viewport"><div class="map-canvas"><div class="tile-grid">__TILES__</div><svg class="overlay-svg" viewBox="0 0 768 768">__SVG_MARKS__</svg></div></div>
<div class="box">
  <div class="card">
    <div class="title">📍 毛孩住家／走失協尋定位</div>
    <div class="meta">__ADDR__<br>座標：__LAT__, __LON__</div>
    <a class="btn btn-blue" href="__NAV_URL__">🧭 開啟導航前往此位置</a>
  </div>
  <div class="card">
    <div class="title">🏥 周邊 24H 急診獸醫院、動保處與寵物店</div>
    <a class="btn btn-red" href="__VET_URL__">🚨 搜尋附近 24小時急診獸醫院</a>
    <a class="btn btn-green" href="__HOTEL_URL__">🏛️ 搜尋附近動保處／動物之家</a>
    <a class="btn btn-blue" href="__SHOP_URL__">🦴 搜尋附近寵物用品／寵物旅館</a>
  </div>
</div>
</body></html>"""
ACTIVE_PET_MAP = {}
PET_LIST_MAP = {}
PENDING_STATE = {}
PET_PHOTO_CACHE = {}
PET_GALLERY_CACHE = {}
PET_AVATAR_MAP = {}
PET_HEALTH_META = {}

def get_pet_scope(uid: str, default_name: str = "毛孩寶貝"):
    pets = PET_LIST_MAP.get(uid, [])
    active = ACTIVE_PET_MAP.get(uid, "")
    if not active:
        active = pets if len(pets) > 0 else default_name
    if active and active not in pets:
        pets.append(active)
        PET_LIST_MAP[uid] = pets
    scope_uid = uid if active == default_name else f"{uid}#{active}"
    return scope_uid, active, pets

def latlon_to_pixel(lat, lon, z=16):
    n = 2.0 ** z
    x = (float(lon) + 180.0) / 360.0 * n * 256.0
    lat_rad = math.radians(float(lat))
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * 256.0
    return x, y

def parse_latlon(loc_str: str):
    try:
        if "(" in loc_str and ")" in loc_str:
            part = next(iter(loc_str.split("(")[-1].split(")")))
            lat_s, lon_s = part.split(",")
            return float(lat_s.strip()), float(lon_s.strip())
    except Exception:
        pass
    return None, None

def call_sheet(payload: dict):
    try:
        r = requests.post(GOOGLE_SHEET_API, json=payload, timeout=12)
        return r.json()
    except Exception:
        return {}

def get_user_name(uid: str):
    base_uid = uid.split("#") if "#" in uid else uid
    try:
        profile = line_bot_api.get_profile(base_uid)
        return profile.display_name
    except Exception:
        return "照護者"

@app.get("/")
def root():
    return {"status": "Online", "service": "Pet Care Handoff Bot 10.0 Pro App"}

@app.get("/pet_photo/{photo_id}")
def serve_pet_photo(photo_id: str):
    img_bytes = PET_PHOTO_CACHE.get(photo_id)
    if not img_bytes:
        raise HTTPException(status_code=404, detail="No photo")
    return Response(content=img_bytes, media_type="image/jpeg")

@app.post("/api/photo_upload")
async def web_photo_upload(scope_key: str = Form(...), pet: str = Form("毛孩寶貝"), replace_id: str = Form(""), files: list[UploadFile] = File(...)):
    now_t = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%m/%d %H:%M")
    gal = PET_GALLERY_CACHE.get(scope_key, [])
    for f in files:
        data = await f.read()
        if not data:
            continue
        if replace_id:
            PET_PHOTO_CACHE[replace_id] = data
            for item in gal:
                if item.get("id") == replace_id:
                    item["time"] = f"{now_t} (已更新)"
            replace_id = ""
        else:
            pid = f"{scope_key}_{int(datetime.datetime.utcnow().timestamp() * 1000)}_{len(gal)}"
            PET_PHOTO_CACHE[pid] = data
            gal.append({"id": pid, "time": now_t, "uploader": "App相簿上傳"})
            if not PET_AVATAR_MAP.get(scope_key):
                PET_AVATAR_MAP[scope_key] = pid
    PET_GALLERY_CACHE[scope_key] = gal
    return RedirectResponse(url=f"/pet_app?scope_key={urllib.parse.quote(scope_key)}&pet={urllib.parse.quote(pet)}", status_code=303)

@app.get("/api/photo_action")
def web_photo_action(act: str, scope_key: str, pid: str, pet: str = "毛孩寶貝"):
    gal = PET_GALLERY_CACHE.get(scope_key, [])
    if act == "avatar" and pid in PET_PHOTO_CACHE:
        PET_AVATAR_MAP[scope_key] = pid
    elif act == "delete":
        gal = [x for x in gal if x.get("id") != pid]
        PET_GALLERY_CACHE[scope_key] = gal
        PET_PHOTO_CACHE.pop(pid, None)
        if PET_AVATAR_MAP.get(scope_key) == pid:
            PET_AVATAR_MAP[scope_key] = gal[-1].get("id", "") if len(gal) > 0 else ""
    return RedirectResponse(url=f"/pet_app?scope_key={urllib.parse.quote(scope_key)}&pet={urllib.parse.quote(pet)}", status_code=303)
@app.get("/pet_app", response_class=HTMLResponse)
def pet_app_studio(scope_key: str, pet: str = "毛孩寶貝"):
    S = chr(47)
    safe_pet = pet.replace("<", "").replace(">", "")
    safe_sk = urllib.parse.quote(scope_key)
    safe_pn = urllib.parse.quote(safe_pet)
    items = PET_GALLERY_CACHE.get(scope_key, [])
    cur_av = PET_AVATAR_MAP.get(scope_key, "")

    cards_html = ""
    for idx, item in enumerate(reversed(items), 1):
        pid = item.get("id", "")
        ts = item.get("time", "")
        is_av = (pid == cur_av)
        av_badge = '<span class="badge-av">👑 封面頭貼</span>' if is_av else ''
        av_btn = f'<span class="btn-done">👑 目前頭貼</span>' if is_av else f'<a class="btn-act btn-gold" href="{S}api{S}photo_action?act=avatar&scope_key={safe_sk}&pid={pid}&pet={safe_pn}">⭐ 設為頭貼</a>'
        cards_html += f'''
        <div class="photo-card">
          <div class="img-wrap" onclick="openLightbox('{S}pet_photo{S}{pid}')"><img src="{S}pet_photo{S}{pid}"/>{av_badge}</div>
          <div class="meta-row"><span>NO.{len(items)-idx+1} · {ts}</span><span style="color:#FF6B4A;">點擊照片可全螢幕放大</span></div>
          <div class="btn-row">
            {av_btn}
            <label class="btn-act btn-blue">🔄 替換<input type="file" accept="image/*" style="display:none;" onchange="replacePhoto('{pid}', this)"/></label>
            <a class="btn-act btn-red" href="{S}api{S}photo_action?act=delete&scope_key={safe_sk}&pid={pid}&pet={safe_pn}" onclick="return confirm('確定刪除這張毛孩照片嗎？')">🗑️ 刪除</a>
          </div>
        </div>'''

    if not cards_html:
        cards_html = '<div class="empty-box"><div style="font-size:40px;margin-bottom:8px;">🐾</div>尚無毛孩照片<br><span style="font-size:13px;color:#868E96;font-weight:normal;">點擊下方「➕ 上傳照片」即可一次多選不限張數</span></div>'

    poster_link = f"{S}lost_poster?scope_key={safe_sk}&pet={safe_pn}"
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
    <title>{safe_pet} · PetCare Pro App</title>
    <style>
      body {{ margin:0; padding:0 0 84px 0; font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display",sans-serif; background:#F4F5F7; color:#1A1B1E; }}
      .topbar {{ background:#1A1B1E; color:#fff; padding:16px 18px; position:sticky; top:0; z-index:90; display:flex; justify-content:space-between; align-items:center; }}
      .topbar h1 {{ margin:0; font-size:17px; letter-spacing:0.5px; }}
      .pill {{ font-size:11px; background:#FF6B4A; color:#fff; padding:4px 10px; border-radius:20px; font-weight:bold; }}
      .wrap {{ max-width:500px; margin:0 auto; padding:14px; }}
      .hero-banner {{ background:linear-gradient(135deg,#FF6B4A,#FF922B); color:#fff; border-radius:22px; padding:18px; margin-bottom:16px; box-shadow:0 10px 24px rgba(255,107,74,0.28); }}
      .photo-card {{ background:#fff; border-radius:22px; padding:12px; margin-bottom:16px; box-shadow:0 6px 20px rgba(0,0,0,0.05); }}
      .img-wrap {{ position:relative; border-radius:16px; overflow:hidden; cursor:zoom-in; }}
      .img-wrap img {{ width:100%; max-height:360px; object-fit:cover; display:block; }}
      .badge-av {{ position:absolute; top:12px; left:12px; background:rgba(26,27,30,0.82); backdrop-filter:blur(6px); color:#FFD43B; font-weight:bold; font-size:12px; padding:6px 12px; border-radius:20px; }}
      .meta-row {{ display:flex; justify-content:space-between; font-size:12px; color:#868E96; margin:10px 6px; font-weight:600; }}
      .btn-row {{ display:flex; gap:8px; }}
      .btn-act, .btn-done {{ flex:1; text-align:center; text-decoration:none; padding:11px 4px; border-radius:12px; font-size:13px; font-weight:700; cursor:pointer; }}
      .btn-done {{ background:#E6FCF5; color:#087F5B; }}
      .btn-gold {{ background:#FFF9DB; color:#E67700; }}
      .btn-blue {{ background:#E7F5FF; color:#1864AB; }}
      .btn-red {{ background:#FFF5F5; color:#C92A2A; }}
      .empty-box {{ background:#fff; border-radius:22px; padding:48px 20px; text-align:center; font-size:17px; font-weight:bold; color:#1A1B1E; }}
      .tabbar {{ position:fixed; bottom:0; left:0; right:0; background:rgba(255,255,255,0.94); backdrop-filter:blur(12px); border-top:1px solid #E9ECEF; display:flex; padding:8px 12px 14px; z-index:95; justify-content:space-around; }}
      .tab-btn {{ flex:1; text-align:center; text-decoration:none; color:#495057; font-size:12px; font-weight:700; cursor:pointer; }}
      .tab-main {{ background:linear-gradient(135deg,#FF6B4A,#FA5252); color:#fff; padding:10px 16px; border-radius:24px; font-size:13px; box-shadow:0 4px 12px rgba(250,82,82,0.3); }}
      #lightbox {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.92); z-index:200; align-items:center; justify-content:center; }}
      #lightbox img {{ max-width:95%; max-height:90%; border-radius:12px; }}
    </style></head><body>
    <div class="topbar"><h1>🐾 {safe_pet} · 雲端相簿 App</h1><span class="pill">{len(items)} 張 · 無上限</span></div>
    <div class="wrap">
      <div class="hero-banner">
        <div style="font-size:15px;font-weight:800;margin-bottom:4px;">✨ 專屬毛孩成長相簿 ＆ 封面管理</div>
        <div style="font-size:12px;opacity:0.92;line-height:1.4;">點下方橘色「➕ 上傳照片」可一次多選。設定「⭐ 設為頭貼」後，回到 LINE 點「今日日報」即刻顯示在卡片最頂端！</div>
      </div>
      {cards_html}
    </div>
    <form id="upForm" action="{S}api{S}photo_upload" method="post" enctype="multipart/form-data" style="display:none;">
      <input type="hidden" name="scope_key" value="{scope_key}"/>
      <input type="hidden" name="pet" value="{safe_pet}"/>
      <input type="hidden" id="repId" name="replace_id" value=""/>
      <input id="fileIn" type="file" name="files" accept="image/*" multiple onchange="document.getElementById('upForm').submit()"/>
    </form>
    <div class="tabbar">
      <a class="tab-btn" href="#top" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">🖼️ 成長相簿</a>
      <label class="tab-btn" for="fileIn"><span class="tab-main">➕ 上傳照片</span></label>
      <a class="tab-btn" href="{poster_link}">🚨 協尋海報</a>
    </div>
    <div id="lightbox" onclick="this.style.display='none'"><img id="lbImg" src=""/></div>
    <script>
      function openLightbox(src) {{ document.getElementById('lbImg').src = src; document.getElementById('lightbox').style.display = 'flex'; }}
      function replacePhoto(pid, inputEl) {{
        if (!inputEl.files || !inputEl.files.length) return;
        document.getElementById('repId').value = pid;
        var dt = new DataTransfer();
        dt.items.add(inputEl.files);
        document.getElementById('fileIn').files = dt.files;
        document.getElementById('upForm').submit();
      }}
    </script></body></html>"""
    return HTMLResponse(content=html)
@app.get("/lost_poster", response_class=HTMLResponse)
def lost_poster_page(scope_key: str, pet: str = "毛孩寶貝", addr: str = "新北市五股區", phone: str = "請私訊聯繫", desc: str = "請大家幫忙留意協尋！"):
    S = chr(47)
    safe_pet = pet.replace("<", "").replace(">", "")
    safe_addr = addr.replace("<", "").replace(">", "")
    safe_phone = re.sub(r"[^0-9+]", "", phone) or phone.replace("<", "").replace(">", "")
    safe_desc = desc.replace("<", "").replace(">", "")
    avatar_pid = PET_AVATAR_MAP.get(scope_key, "")
    has_photo = bool(avatar_pid and avatar_pid in PET_PHOTO_CACHE)
    photo_html = f'<img src="{RENDER_BASE_URL}{S}pet_photo{S}{avatar_pid}" style="width:100%;max-height:320px;object-fit:cover;border-radius:16px;margin:12px 0;border:3px solid #FA5252;"/>' if has_photo else '<div style="background:#FFF5F5;border:2px dashed #FA5252;border-radius:16px;padding:24px;margin:12px 0;color:#C92A2A;font-weight:bold;">🐾 協尋緊急通報（飼主可於相簿 App 上傳毛孩照片自動顯示於此）</div>'
    call_btn = f'<a class="btn" style="background:#12B886;" href="tel:{safe_phone}">📞 發現毛孩！立即撥打 {safe_phone}</a>' if len(safe_phone) >= 8 else ""
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>🚨 緊急協尋走失毛孩：{safe_pet}</title>
    <style>
      body {{ font-family: -apple-system, sans-serif; margin: 0; padding: 16px; background: #FFF5F5; text-align: center; }}
      .poster {{ background: #fff; border: 4px solid #FA5252; border-radius: 22px; padding: 20px; max-width: 460px; margin: 0 auto; box-shadow: 0 8px 24px rgba(250,82,82,0.2); }}
      .badge {{ background: #FA5252; color: #fff; font-size: 20px; font-weight: bold; padding: 10px; border-radius: 12px; letter-spacing: 2px; }}
      .name {{ font-size: 30px; font-weight: bold; color: #1A1B1E; margin: 12px 0 6px; }}
      .info {{ text-align: left; background: #FFF9DB; padding: 14px; border-radius: 14px; font-size: 15px; line-height: 1.6; color: #333; margin: 12px 0; }}
      .btn {{ display: block; color: #fff; text-decoration: none; font-size: 18px; font-weight: bold; padding: 15px; border-radius: 14px; margin-top: 10px; }}
    </style></head><body>
    <div class="poster">
      <div class="badge">🚨 緊急協尋 · 走失毛孩 🚨</div>
      <div class="name">名字：{safe_pet}</div>
      {photo_html}
      <div class="info">
        <b>📍 最後走失地點：</b>{safe_addr}<br>
        <b>📝 特徵與狀況：</b>{safe_desc}<br>
        <b>📞 飼主聯絡電話：</b>{safe_phone}
      </div>
      {call_btn}
      <a class="btn" style="background:#228BE6;" href="https:{S}{S}://google.com{S}?q={urllib.parse.quote(safe_addr)}">🗺️ 開啟走失地點周邊地圖</a>
    </div></body></html>"""
    return HTMLResponse(content=html)

@app.get("/call", response_class=HTMLResponse)
def direct_call_page(num: str, name: str = "飼主緊急電話"):
    clean_num = re.sub(r"[^0-9+]", "", num)
    safe_name = name.replace("<", "").replace(">", "")
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>正在撥打給 {safe_name}</title>
    <style>
      body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 40px 20px; background: #F8F9FA; }}
      .card {{ background: #fff; border-radius: 20px; padding: 30px 20px; max-width: 400px; margin: 0 auto; box-shadow: 0 8px 24px rgba(0,0,0,0.06); }}
      .btn {{ display: block; background: #12B886; color: #fff; text-decoration: none; font-size: 22px; font-weight: bold; padding: 18px; border-radius: 14px; margin-top: 24px; }}
    </style></head><body>
    <div class="card">
      <div style="font-size:18px;color:#555;">準備撥打緊急聯絡電話</div>
      <div style="font-size:28px;font-weight:bold;color:#1A1B1E;margin:10px 0;">{safe_name}</div>
      <div style="font-size:24px;color:#FA5252;font-weight:bold;">{clean_num}</div>
      <a class="btn" href="tel:{clean_num}">📞 立即撥出電話</a>
    </div>
    <script>window.onload = function() {{ window.location.href = "tel:{clean_num}"; }};</script>
    </body></html>"""
    return HTMLResponse(content=html)

@app.get("/video", response_class=HTMLResponse)
def video_call_page(room: str, pet: str = "毛孩寶貝"):
    S = chr(47)
    safe_room = re.sub(r"[^a-zA-Z0-9_-]", "", room) or "PetRoomDefault"
    safe_pet = pet.replace("<", "").replace(">", "")
    jitsi_url = f"https:{S}{S}meet.jit.si{S}TaiwanPet_{safe_room}#config.prejoinPageEnabled=false"
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>{safe_pet} · 專屬視訊看毛孩室</title>
    <style>
      body {{ font-family: -apple-system, sans-serif; text-align: center; padding: 36px 20px; background: #F8F9FA; }}
      .card {{ background: #fff; border-radius: 20px; padding: 28px 20px; max-width: 420px; margin: 0 auto; box-shadow: 0 8px 24px rgba(112,72,232,0.12); }}
      .btn {{ display: block; background: #7048E8; color: #fff; text-decoration: none; font-size: 20px; font-weight: bold; padding: 18px; border-radius: 14px; margin-top: 22px; }}
    </style></head><body>
    <div class="card">
      <div style="font-size:16px;color:#555;">📹 汪喵遠端視訊看毛孩（免下載 App）</div>
      <div style="font-size:26px;font-weight:bold;color:#1A1B1E;margin:12px 0;">{safe_pet} 的專屬視訊室</div>
      <div style="font-size:13px;color:#666;line-height:1.5;">正在為您開啟高清視訊通話，請允許瀏覽器使用「麥克風與相機」權限：</div>
      <a class="btn" href="{jitsi_url}">📹 立即進入視訊通話</a>
    </div>
    <script>setTimeout(function() {{ window.location.href = "{jitsi_url}"; }}, 600);</script>
    </body></html>"""
    return HTMLResponse(content=html)

@app.get("/pet_map", response_class=HTMLResponse)
def pet_map_view(lat: float, lon: float, addr: str = "毛孩住家"):
    S = chr(47)
    z = 16
    ux, uy = latlon_to_pixel(lat, lon, z)
    cx_tile, cy_tile = int(ux // 256), int(uy // 256)
    origin_x, origin_y = (cx_tile - 1) * 256, (cy_tile - 1) * 256

    tiles_html = []
    for dy in [-1, 0, 1]:
        for dx in [-1, 0, 1]:
            tx, ty = cx_tile + dx, cy_tile + dy
            nlsc_url = f"https:{S}{S}wmts.nlsc.gov.tw{S}wmts{S}EMAP{S}default{S}GoogleMapsCompatible{S}{z}{S}{ty}{S}{tx}"
            osm_url = f"https:{S}{S}tile.openstreetmap.org{S}{z}{S}{tx}{S}{ty}.png"
            tiles_html.append(f'<img src="{nlsc_url}" onerror="this.onerror=null;this.src=\'{osm_url}\';"/>')

    user_px, user_py = ux - origin_x, uy - origin_y
    offset_x, offset_y = round(-user_px, 1), round(-user_py, 1)
    meters_per_px = 156543.03392 * math.cos(math.radians(float(lat))) / (2 ** z)
    radius_px = round(1000.0 / meters_per_px, 1)

    svg_marks = [
        f'<circle cx="{user_px}" cy="{user_py}" r="{radius_px}" fill="#FF6B4A" fill-opacity="0.14" stroke="#FF6B4A" stroke-width="2" stroke-dasharray="6,4"/>',
        f'<circle cx="{user_px}" cy="{user_py}" r="10" fill="#FF6B4A" stroke="#fff" stroke-width="3"/>'
    ]
    safe_addr = addr.replace("<", "").replace(">", "")
    host = "maps." + "google.com"
    base = f"https:{S}{S}{host}{S}"
    nav_url = f"{base}?daddr={lat},{lon}&dirflg=w"
    vet_url = f"{base}?q={urllib.parse.quote('24小時急診獸醫院')}&ll={lat},{lon}&z=15"
    hotel_url = f"{base}?q={urllib.parse.quote('動保處 動物之家')}&ll={lat},{lon}&z=15"
    shop_url = f"{base}?q={urllib.parse.quote('寵物用品店 寵物旅館')}&ll={lat},{lon}&z=15"

    html = (PET_MAP_HTML
            .replace("__OFFSET_X__", str(offset_x))
            .replace("__OFFSET_Y__", str(offset_y))
            .replace("__TILES__", "".join(tiles_html))
            .replace("__SVG_MARKS__", "".join(svg_marks))
            .replace("__ADDR__", safe_addr)
            .replace("__LAT__", str(lat))
            .replace("__LON__", str(lon))
            .replace("__NAV_URL__", nav_url)
            .replace("__VET_URL__", vet_url)
            .replace("__HOTEL_URL__", hotel_url)
            .replace("__SHOP_URL__", shop_url))
    return HTMLResponse(content=html)
def make_pet_card(title: str, subtitle: str, status_text: str, uid: str, lat=None, lon=None, addr="尚未設定", owner_phone: str = "尚未設定"):
    S = chr(47)
    base_uid = uid.split("#") if "#" in uid else uid
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", uid)
    pet_only_name = uid.split("#")[-1] if "#" in uid else "毛孩寶貝"
    app_uri = f"{RENDER_BASE_URL}/pet_app?scope_key={safe_key}&pet={urllib.parse.quote(pet_only_name)}&openExternalBrowser=1"

    bind_cmd = urllib.parse.quote(f"綁定人員:{base_uid}")
    share_text = urllib.parse.quote(f"邀請您加入「汪喵平安守護 ＆ 寵物照護日記」守護群（不限人數）！點擊下方連結加入後，每次餵食、鏟屎、散步或異常狀況，您都會即時收到通知：\nhttps:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{bind_cmd}")
    share_uri = f"https:{S}{S}line.me{S}R{S}share?text={share_text}"

    summary_only = next(iter(status_text.split("🏠 位置："))).strip()
    report_share_txt = urllib.parse.quote(f"🐾【{title}】\n{summary_only}\n\n📲 免費使用「汪喵平安守護」一鍵打卡＋視訊看毛孩：\nhttps:{S}{S}line.me{S}R{S}ti{S}p{S}{LINE_BOT_BASIC_ID}")
    report_share_uri = f"https:{S}{S}line.me{S}R{S}share?text={report_share_txt}"

    phone_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('飼主電話:')}"
    add_pet_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('毛孩:')}"
    rename_pet_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('改名:')}"
    weight_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('體重:')}"
    clean_phone = re.sub(r"[^0-9]", "", str(owner_phone or ""))

    meta = PET_HEALTH_META.get(uid, {})
    weight_str = meta.get("weight", "未量測")
    vax_str = meta.get("vax", "未設定")
    photo_cnt = len(PET_GALLERY_CACHE.get(safe_key, []))
    avatar_pid = PET_AVATAR_MAP.get(safe_key, "")
    has_avatar = bool(avatar_pid and avatar_pid in PET_PHOTO_CACHE)

    has_alert = ("🚨" in status_text) or ("異常" in status_text) or ("走失" in status_text)
    feed_cnt = status_text.count("餵食：")
    poop_cnt = status_text.count("排泄：")
    act_cnt = status_text.count("活動：") + status_text.count("保健：")

    total_tasks = feed_cnt + poop_cnt + act_cnt + photo_cnt
    pct = min(100, total_tasks * 25)
    bar_color = "#FA5252" if has_alert else ("#12B886" if pct >= 75 else "#FF922B")
    banner_bg = "#FFF5F5" if has_alert else "#E6FCF5"
    banner_fg = "#C92A2A" if has_alert else "#087F5B"
    banner_msg = "⚠️ 偵測到異常或走失警報，請密切留意周邊！" if has_alert else f"✨ 完成度 {pct}% ｜ ⚖️ {weight_str} ｜ 💉 {vax_str}"

    hero_img = ImageComponent(
        url=f"{RENDER_BASE_URL}/pet_photo/{avatar_pid}",
        size="full",
        aspect_ratio="16:9",
        aspect_mode="cover",
        action=URIAction(label="開啟華麗相簿App", uri=app_uri)
    ) if has_avatar else None

    bubble_1 = BubbleContainer(
        size="mega",
        hero=hero_img,
        header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="16px", contents=[
            TextComponent(text=title, weight="bold", size="md", color="#FFFFFF", wrap=True),
            TextComponent(text=subtitle, size="xs", color="#FFA94D", weight="bold", wrap=True, margin="xs")
        ]),
        body=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
            BoxComponent(layout="vertical", background_color=banner_bg, corner_radius="12px", padding_all="10px", contents=[
                TextComponent(text=banner_msg, size="xxs", color=banner_fg, weight="bold", wrap=True),
                BoxComponent(layout="vertical", background_color="#DEE2E6", height="6px", corner_radius="3px", margin="sm", contents=[
                    BoxComponent(layout="vertical", background_color=bar_color, height="6px", width=f"{max(8, pct)}%", corner_radius="3px", contents=[])
                ])
            ]),
            BoxComponent(layout="horizontal", spacing="xs", contents=[
                BoxComponent(layout="vertical", background_color="#E6FCF5", corner_radius="12px", padding_all="6px", align_items="center", contents=[
                    TextComponent(text="🥣 放飯", size="xxs", color="#0CA678", weight="bold"),
                    TextComponent(text=f"{feed_cnt}", size="md", color="#087F5B", weight="bold")
                ]),
                BoxComponent(layout="vertical", background_color="#E7F5FF", corner_radius="12px", padding_all="6px", align_items="center", contents=[
                    TextComponent(text="💩 鏟屎", size="xxs", color="#1C7ED6", weight="bold"),
                    TextComponent(text=f"{poop_cnt}", size="md", color="#1864AB", weight="bold")
                ]),
                BoxComponent(layout="vertical", background_color="#FFF4E6", corner_radius="12px", padding_all="6px", align_items="center", contents=[
                    TextComponent(text="🐕 散步", size="xxs", color="#F76707", weight="bold"),
                    TextComponent(text=f"{act_cnt}", size="md", color="#D9480F", weight="bold")
                ]),
                BoxComponent(layout="vertical", background_color="#F3F0FF", corner_radius="12px", padding_all="6px", align_items="center", contents=[
                    TextComponent(text="📸 相簿", size="xxs", color="#7048E8", weight="bold"),
                    TextComponent(text=f"{photo_cnt}", size="md", color="#5F3DC4", weight="bold")
                ])
            ]),
            BoxComponent(layout="vertical", background_color="#F8F9FA", corner_radius="14px", padding_all="12px", contents=[
                TextComponent(text=status_text, size="xs", color="#212529", wrap=True)
            ])
        ]),
        footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#12B886", height="sm", action=MessageAction(label="🥣 放飯", text="紀錄:餵食:乾乾／罐罐已吃完，飲水正常")),
                ButtonComponent(style="primary", color="#228BE6", height="sm", action=MessageAction(label="💩 鏟屎", text="紀錄:排泄:已清理貓砂／撿便，大小便正常"))
            ]),
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#FD7E14", height="sm", action=MessageAction(label="🐕 散步", text="紀錄:活動:已完成外出散步與陪玩運動")),
                ButtonComponent(style="primary", color="#7950F2", height="sm", action=MessageAction(label="💊 保健", text="紀錄:保健:已按時餵食驅蟲藥／保健品"))
            ]),
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="secondary", height="sm", action=MessageAction(label="😿 吃少", text="異常:餵食:今天食慾較差吃得很少，請留意")),
                ButtonComponent(style="primary", color="#FA5252", height="sm", action=MessageAction(label="🚨 異常", text="異常:健康:發現軟便或嘔吐狀況，已通知全家"))
            ]),
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="secondary", height="sm", action=MessageAction(label="✍️ 記狀況", text="新增狀況")),
                ButtonComponent(style="secondary", height="sm", action=URIAction(label="📤 轉傳交班", uri=report_share_uri))
            ])
        ])
    )
    tools_footer = [
        BoxComponent(layout="horizontal", spacing="sm", contents=[
            ButtonComponent(style="primary", color="#FF6B4A", height="sm", action=URIAction(label=f"🖼️ 相簿App({photo_cnt})", uri=app_uri)),
            ButtonComponent(style="primary", color="#7048E8", height="sm", action=MessageAction(label="📹 開視訊", text="開啟視訊"))
        ]),
        BoxComponent(layout="horizontal", spacing="sm", contents=[
            ButtonComponent(style="secondary", height="sm", action=URIAction(label="⚖️ 記體重", uri=weight_uri)),
            ButtonComponent(style="secondary", height="sm", action=MessageAction(label="💉 驅蟲疫苗", text="驅蟲疫苗"))
        ]),
        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🩺 生成獸醫看診問診摘要", text="獸醫摘要")),
        BoxComponent(layout="horizontal", spacing="sm", contents=[
            ButtonComponent(style="primary", color="#FF922B", height="sm", action=MessageAction(label="🐾 切換毛孩", text="切換毛孩")),
            ButtonComponent(style="secondary", height="sm", action=URIAction(label="✏️ 改毛孩名", uri=rename_pet_uri))
        ]),
        BoxComponent(layout="horizontal", spacing="sm", contents=[
            ButtonComponent(style="secondary", height="sm", action=URIAction(label="➕ 新增毛孩", uri=add_pet_uri)),
            ButtonComponent(style="secondary", height="sm", action=MessageAction(label="✏️ 改刪狀況", text="修改狀況"))
        ]),
        BoxComponent(layout="horizontal", spacing="sm", contents=[
            ButtonComponent(style="secondary", height="sm", action=URIAction(label="➕ 邀家人", uri=share_uri)),
            ButtonComponent(style="secondary", height="sm", action=MessageAction(label="👥 管人員", text="管理人員"))
        ]),
        BoxComponent(layout="horizontal", spacing="sm", contents=[
            ButtonComponent(style="secondary", height="sm", action=MessageAction(label="⏰ 設鬧鐘", text="餵食時間")),
            ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🏠 設地址", text="管理地址"))
        ])
    ]

    if len(clean_phone) >= 8:
        tools_footer.append(
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#FD7E14", height="sm", action=URIAction(label=f"📞 {clean_phone}", uri=f"{RENDER_BASE_URL}/call?num={clean_phone}&name={urllib.parse.quote('毛孩飼主緊急聯絡人')}&openExternalBrowser=1")),
                ButtonComponent(style="secondary", height="sm", action=MessageAction(label="✏️ 改電話", text="管理飼主電話"))
            ])
        )
    else:
        tools_footer.append(ButtonComponent(style="secondary", height="sm", action=URIAction(label="📞 設定飼主緊急電話", uri=phone_uri)))

    clean_addr_only = next(iter(str(addr).split("("))).strip() if "(" in str(addr) else str(addr).strip()
    if lat is not None and lon is not None:
        enc_addr = urllib.parse.quote(clean_addr_only or "毛孩住家")
        map_uri = f"{RENDER_BASE_URL}/pet_map?lat={lat}&lon={lon}&addr={enc_addr}&openExternalBrowser=1"
        tools_footer.append(
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#FA5252", height="sm", action=URIAction(label="🏥 急診地圖", uri=map_uri)),
                ButtonComponent(style="primary", color="#C92A2A", height="sm", action=MessageAction(label="🚨 毛孩走失", text="毛孩走失"))
            ])
        )
    elif clean_addr_only and clean_addr_only != "尚未設定":
        host = "maps." + "google.com"
        q_uri = f"https:{S}{S}{host}{S}?q={urllib.parse.quote(clean_addr_only + ' 附近24小時急診獸醫院')}"
        tools_footer.append(
            BoxComponent(layout="horizontal", spacing="sm", contents=[
                ButtonComponent(style="primary", color="#FA5252", height="sm", action=URIAction(label="🏥 急診地圖", uri=q_uri)),
                ButtonComponent(style="primary", color="#C92A2A", height="sm", action=MessageAction(label="🚨 毛孩走失", text="毛孩走失"))
            ])
        )
    else:
        tools_footer.append(ButtonComponent(style="primary", color="#C92A2A", height="sm", action=MessageAction(label="🚨 毛孩走失緊急協尋通報", text="毛孩走失")))

    if NOTION_PET_SHOP_URL.startswith("http"):
        tools_footer.append(ButtonComponent(style="secondary", height="sm", action=URIAction(label="🛒 汪喵嚴選好物推薦館", uri=NOTION_PET_SHOP_URL)))

    bubble_2 = BubbleContainer(
        size="mega",
        header=BoxComponent(layout="vertical", background_color="#FF6B4A", padding_all="16px", contents=[
            TextComponent(text=f"⚙️ {pet_only_name} · App 功能中心", weight="bold", size="md", color="#FFFFFF", wrap=True),
            TextComponent(text="相簿頭貼、遠端視訊、健康護照與走失協尋", size="xs", color="#FFF4E6", weight="bold", wrap=True, margin="xs")
        ]),
        body=BoxComponent(layout="vertical", spacing="xs", background_color="#FFFFFF", contents=[
            TextComponent(text="👈 向左滑動返回「今日照護儀表板」打卡", size="xxs", color="#868E96", weight="bold")
        ]),
        footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=tools_footer)
    )

    return CarouselContainer(contents=[bubble_1, bubble_2])
@app.post("/callback")
async def callback(request: Request):
    sig = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), sig)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(FollowEvent)
def on_follow(event):
    uid = event.source.user_id
    uname = get_user_name(uid)
    scope_uid, active_pet, _ = get_pet_scope(uid)
    st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
    o_phone = st.get("owner_phone", "尚未設定")
    loc_str = st.get("last_location", "尚未設定")
    lat, lon = parse_latlon(loc_str)
    card = make_pet_card(
        f"🐾 {active_pet} · 汪喵平安守護 10.0 Pro",
        f"嗨 {uname}！左右滑動雙卡切換「日常打卡」與「App 功能中心」：",
        "向右滑動第 2 張卡片點擊「🖼️ 相簿App」，可直接多選上傳毛孩照片並設為卡片最上方大頭貼！",
        scope_uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
    )
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="汪喵平安守護 Pro 已啟動", contents=card))

@handler.add(MessageEvent, message=LocationMessage)
def on_location(event):
    uid = event.source.user_id
    uname = get_user_name(uid)
    scope_uid, active_pet, _ = get_pet_scope(uid)
    addr = event.message.address or "已定位座標"
    lat, lon = event.message.latitude, event.message.longitude
    call_sheet({"action": "location", "user_id": scope_uid, "user_name": uname, "address": addr, "lat": lat, "lon": lon})
    st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
    o_phone = st.get("owner_phone", "尚未設定")
    card = make_pet_card(
        f"📍 {active_pet} · 住家與協尋定位已開通",
        "已將此位置設為毛孩的照護與協尋座標：",
        f"🏠 登記位置：{addr}\n🏥 向右滑動第 2 張卡片可開啟急診地圖或毛孩走失協尋！",
        scope_uid, lat=lat, lon=lon, addr=addr, owner_phone=o_phone
    )
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="毛孩定位更新成功", contents=card))

@handler.add(MessageEvent, message=ImageMessage)
def on_image(event):
    uid = event.source.user_id
    uname = get_user_name(uid)
    scope_uid, active_pet, pet_list = get_pet_scope(uid)
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", scope_uid)
    now_t = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).strftime("%m/%d %H:%M")

    try:
        msg_content = line_bot_api.get_message_content(event.message.id)
        img_data = b"".join(chunk for chunk in msg_content.iter_content())
        gal = PET_GALLERY_CACHE.get(safe_key, [])
        photo_id = f"{safe_key}_{int(datetime.datetime.utcnow().timestamp() * 1000)}"
        PET_PHOTO_CACHE[photo_id] = img_data
        gal.append({"id": photo_id, "time": now_t, "uploader": uname})
        PET_GALLERY_CACHE[safe_key] = gal
        if not PET_AVATAR_MAP.get(safe_key):
            PET_AVATAR_MAP[safe_key] = photo_id
        action_msg = f"📸 已新增毛孩照片（相簿目前共 {len(gal)} 張，不限張數）！"
    except Exception:
        action_msg = "📸 已收到毛孩照片！"

    call_sheet({"action": "log_care", "user_id": scope_uid, "user_name": uname, "category": "特別狀況", "detail": action_msg, "is_abnormal": False})
    st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
    o_phone = st.get("owner_phone", "尚未設定")
    loc_str = st.get("last_location", "尚未設定")
    logs = st.get("today_logs", [])
    logs_txt = "\n".join(logs) if len(logs) > 0 else action_msg
    lat, lon = parse_latlon(loc_str)
    card = make_pet_card(
        f"📸 {active_pet} · 相簿與大頭貼已更新",
        f"共 {len(pet_list)} 隻毛孩 ｜ 滑動第 2 張卡片可開啟相簿 App",
        f"{logs_txt}\n\n🏠 位置：{loc_str}",
        scope_uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
    )
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="毛孩照片已更新", contents=card))
@handler.add(MessageEvent, message=TextMessage)
def on_text(event):
    uid = event.source.user_id
    uname = get_user_name(uid)
    txt = event.message.text.strip()
    scope_uid, active_pet, pet_list = get_pet_scope(uid)
    safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", scope_uid)

    try:
        # 0. 一鍵開啟專屬視訊看毛孩並同步通知所有人員
        if txt in ["開啟視訊", "視訊", "視訊看毛孩", "打視訊"]:
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            p_name = active_pet
            f_ids = st.get("family_ids", [])
            room_code = uid[-12:] if len(uid) >= 12 else uid
            video_uri = f"{RENDER_BASE_URL}/video?room={room_code}&pet={urllib.parse.quote(p_name)}&openExternalBrowser=1"

            if len(f_ids) > 0:
                invite_bubble = BubbleContainer(
                    size="mega",
                    header=BoxComponent(layout="vertical", background_color="#7048E8", padding_all="14px", contents=[
                        TextComponent(text=f"📹 {p_name} · 遠端視訊看毛孩邀請", weight="bold", size="md", color="#FFFFFF", wrap=True)
                    ]),
                    body=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFDF9", contents=[
                        TextComponent(text=f"照護者「{uname}」已開啟專屬視訊室，快進來看看「{p_name}」現在可愛的模樣吧！", size="sm", weight="bold", color="#3D2C2E", wrap=True),
                        TextComponent(text="點擊下方紫色按鈕即可透過瀏覽器直接加入視訊（免下載任何 App）：", size="xs", color="#666666", wrap=True)
                    ]),
                    footer=BoxComponent(layout="vertical", background_color="#FFFDF9", contents=[
                        ButtonComponent(style="primary", color="#7048E8", height="sm", action=URIAction(label="📹 立即加入視訊看毛孩", uri=video_uri))
                    ])
                )
                for fid in f_ids:
                    try:
                        line_bot_api.push_message(fid, FlexSendMessage(alt_text=f"📹 {p_name} 視訊看毛孩邀請", contents=invite_bubble))
                    except Exception:
                        pass

            self_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#7048E8", padding_all="14px", contents=[
                    TextComponent(text=f"📹 {p_name} · 專屬視訊看毛孩室已建立", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFDF9", contents=[
                    TextComponent(text=f"已同步發送視訊邀請給 {len(f_ids)} 位家人／飼主！" if len(f_ids) > 0 else "視訊室已準備就緒（尚未綁定家人時也可直接開啟）！", size="sm", weight="bold", color="#3D2C2E", wrap=True),
                    TextComponent(text="點擊下方紫色按鈕即可開啟手機鏡頭，與家人一起看看毛孩狀況：", size="xs", color="#666666", wrap=True)
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFDF9", contents=[
                    ButtonComponent(style="primary", color="#7048E8", height="sm", action=URIAction(label="📹 立即開啟視訊鏡頭", uri=video_uri)),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日寵物照護日報", text="今日日報"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="專屬視訊室已建立", contents=self_card))
            return

        # 0-1. 開啟原生 App 級華麗相簿工作台
        if txt in ["管理相簿", "相簿", "設頭貼", "毛孩相簿", "相簿App"]:
            gal = PET_GALLERY_CACHE.get(safe_key, [])
            app_uri = f"{RENDER_BASE_URL}/pet_app?scope_key={safe_key}&pet={urllib.parse.quote(active_pet)}&openExternalBrowser=1"
            app_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text=f"🖼️ {active_pet} · 雲端相簿 Pro App", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    TextComponent(text=f"目前相簿已收錄：{len(gal)} 張照片（不限張數上限）", size="sm", weight="bold", color="#1A1B1E", wrap=True),
                    TextComponent(text="點擊下方按鈕開啟專屬相簿 App 工作台，可一次多選上傳手機照片、一鍵設為卡片最上方大頭貼、替換舊照或刪除照片！", size="xs", color="#666666", wrap=True)
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    ButtonComponent(style="primary", color="#FF6B4A", height="sm", action=URIAction(label="🚀 立即開啟雲端相簿 App", uri=app_uri)),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 刷新日報顯示最新大頭貼", text="今日日報"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="開啟雲端相簿App", contents=app_card))
            return

        # 1. 日常打卡與異常健康狀況
        if txt.startswith("紀錄:"):
            PENDING_STATE.pop(uid, None)
            parts = txt.split(":", 2)
            _ = parts.pop(0)
            cat = parts.pop(0) if parts else "照護紀錄"
            detail = parts.pop(0) if parts else txt
            res = call_sheet({"action": "log_care", "user_id": scope_uid, "user_name": uname, "category": cat, "detail": detail, "is_abnormal": False})
            t_str = res.get("time", "剛剛")
            f_cnt = res.get("family_count", 0)
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            o_phone = st.get("owner_phone", "尚未設定")
            loc_str = st.get("last_location", "尚未設定")
            logs = st.get("today_logs", [])
            logs_txt = "\n".join(logs) if len(logs) > 0 else f"[{t_str}] {cat}：{detail}"
            lat, lon = parse_latlon(loc_str)
            notify_note = f"✅ 已同步通知 {f_cnt} 位家人／飼主！" if f_cnt > 0 else "💡 尚未綁定家人／保母"
            card = make_pet_card(
                f"✅ {active_pet} · {cat}已紀錄",
                f"時間：{t_str}　｜　{notify_note}",
                f"{logs_txt}\n\n🏠 位置：{loc_str}",
                scope_uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"{active_pet} {cat}紀錄完成", contents=card))
            return

        if txt.startswith("異常:"):
            PENDING_STATE.pop(uid, None)
            parts = txt.split(":", 2)
            _ = parts.pop(0)
            cat = parts.pop(0) if parts else "健康異常"
            detail = parts.pop(0) if parts else txt
            res = call_sheet({"action": "log_care", "user_id": scope_uid, "user_name": uname, "category": cat, "detail": detail, "is_abnormal": True})
            t_str = res.get("time", "剛剛")
            f_cnt = res.get("family_count", 0)
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            o_phone = st.get("owner_phone", "尚未設定")
            loc_str = st.get("last_location", "尚未設定")
            logs = st.get("today_logs", [])
            logs_txt = "\n".join(logs) if len(logs) > 0 else f"[{t_str}] 🚨 {cat}：{detail}"
            lat, lon = parse_latlon(loc_str)
            card = make_pet_card(
                f"🚨 {active_pet} · 異常狀況通報",
                f"時間：{t_str}　｜　已警報通知 {f_cnt} 位守護成員",
                f"{logs_txt}\n\n🏠 位置：{loc_str}",
                scope_uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"{active_pet} 異常狀況通報", contents=card))
            return
        # 1-2. 新增特別狀況
        if txt in ["新增狀況", "新增特別狀況", "記狀況"]:
            PENDING_STATE[uid] = "WAITING_NOTE"
            S = chr(47)
            note_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('狀況:')}"
            guide_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text=f"✍️ 記錄「{active_pet}」特別狀況", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    TextComponent(text="✅ 請直接在對話框打字輸入狀況內容（不需加任何前綴，直接傳送即可）！", size="xs", color="#1A1B1E", wrap=True),
                    TextComponent(text="💡 範例：今天在陽台曬太陽睡著了，精神很好", size="xxs", color="#868E96", wrap=True)
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    ButtonComponent(style="primary", color="#FF6B4A", height="sm", action=URIAction(label="✍️ 帶入「狀況:」快速輸入", uri=note_uri)),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="❌ 取消並返回日報", text="取消輸入"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="記錄毛孩特別狀況", contents=guide_card))
            return

        if txt == "取消輸入":
            PENDING_STATE.pop(uid, None)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="👌 已取消輸入！輸入「今日日報」可返回主畫面。"))
            return

        is_prefixed_note = txt.startswith("狀況:") or txt.startswith("狀況：") or txt.startswith("備忘:") or txt.startswith("備忘：")
        known_cmds = [
            "今日日報", "修改狀況", "刪除狀況", "修改紀錄", "編輯狀況",
            "餵食時間", "放飯時間", "鬧鐘設定", "管理飼主電話", "修改飼主電話", "飼主電話",
            "刪除飼主電話", "清除飼主電話", "管理地址", "住家地址", "修改地址", "地址",
            "刪除地址", "清除地址", "管理人員", "人員名單", "修改人員", "刪除人員",
            "清空人員", "全部移除人員", "切換毛孩", "多隻毛孩", "毛孩名單", "管理毛孩",
            "毛孩走失", "走失協尋", "走失", "解除走失", "驅蟲疫苗", "獸醫摘要",
            "管理相簿", "相簿", "設頭貼", "毛孩相簿", "相簿App"
        ]
        is_pending_note = (PENDING_STATE.get(uid) == "WAITING_NOTE") and (txt not in known_cmds) and (":" not in txt[:4])

        if is_prefixed_note or is_pending_note:
            PENDING_STATE.pop(uid, None)
            note_content = txt[3:].strip() if is_prefixed_note else txt
            if not note_content:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✍️ 請輸入毛孩的特別狀況內容喔！"))
                return
            res = call_sheet({"action": "log_care", "user_id": scope_uid, "user_name": uname, "category": "特別狀況", "detail": note_content, "is_abnormal": False})
            t_str = res.get("time", "剛剛")
            f_cnt = res.get("family_count", 0)
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            o_phone = st.get("owner_phone", "尚未設定")
            loc_str = st.get("last_location", "尚未設定")
            logs = st.get("today_logs", [])
            logs_txt = "\n".join(logs) if len(logs) > 0 else f"[{t_str}] 特別狀況：{note_content}"
            lat, lon = parse_latlon(loc_str)
            notify_note = f"✅ 已同步通知 {f_cnt} 位家人／飼主！" if f_cnt > 0 else "💡 尚未綁定家人／保母"
            card = make_pet_card(
                f"✍️ {active_pet} · 特別狀況已更新",
                f"時間：{t_str}　｜　{notify_note}",
                f"{logs_txt}\n\n🏠 位置：{loc_str}",
                scope_uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="特別狀況已更新", contents=card))
            return

        # 1-3. 雲端健康護照：記體重、驅蟲疫苗、獸醫看診問診摘要
        if txt.startswith("體重:") or txt.startswith("體重："):
            w_raw = re.sub(r"[^0-9.]", "", txt[3:].strip())
            if not w_raw:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚖️ 請在「體重:」後面輸入公斤數字喔！例如：體重:4.8"))
                return
            new_w = float(w_raw)
            meta = PET_HEALTH_META.get(scope_uid, {})
            old_w = meta.get("last_w_num")
            diff_str = ""
            if old_w is not None:
                diff = round(new_w - old_w, 2)
                diff_str = f" (↗ +{diff}kg)" if diff > 0 else (f" (↘ {diff}kg)" if diff < 0 else " (持平)")
            disp_w = f"{new_w}kg{diff_str}"
            meta["weight"] = disp_w
            meta["last_w_num"] = new_w
            PET_HEALTH_META[scope_uid] = meta
            call_sheet({"action": "log_care", "user_id": scope_uid, "user_name": uname, "category": "保健", "detail": f"⚖️ 量測體重：{disp_w}", "is_abnormal": False})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚖️ 已記錄「{active_pet}」最新體重為【{disp_w}】！輸入「今日日報」可查看儀表板更新。"))
            return

        if txt == "驅蟲疫苗":
            S = chr(47)
            vax_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('疫苗:')}"
            meta = PET_HEALTH_META.get(scope_uid, {})
            cur_vax = meta.get("vax", "尚未設定")
            vax_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text=f"💉 {active_pet} · 驅蟲與疫苗提醒", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="md", background_color="#FFFFFF", contents=[
                    TextComponent(text=f"目前登記下次日期：{cur_vax}", size="sm", weight="bold", color="#1A1B1E", wrap=True),
                    BoxComponent(layout="horizontal", spacing="sm", contents=[
                        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🗓️ 30天後每月驅蟲", text="疫苗:30天後")),
                        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🗓️ 半年後補打疫苗", text="疫苗:180天後"))
                    ])
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    ButtonComponent(style="primary", color="#228BE6", height="sm", action=URIAction(label="✏️ 自訂日期（如 2026-12-25）", uri=vax_uri)),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日日報", text="今日日報"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="驅蟲與疫苗提醒設定", contents=vax_card))
            return

        if txt.startswith("疫苗:") or txt.startswith("疫苗："):
            v_raw = txt[3:].strip()
            now_tw = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
            target_d = (now_tw + datetime.timedelta(days=30)).strftime("%Y-%m-%d") if v_raw == "30天後" else ((now_tw + datetime.timedelta(days=180)).strftime("%Y-%m-%d") if v_raw == "180天後" else v_raw)
            meta = PET_HEALTH_META.get(scope_uid, {})
            meta["vax"] = target_d
            PET_HEALTH_META[scope_uid] = meta
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"💉 已將「{active_pet}」的下次驅蟲／疫苗日期設定為【{target_d}】！輸入「今日日報」可查看最新畫面。"))
            return

        if txt == "獸醫摘要":
            S = chr(47)
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            logs = st.get("today_logs", [])
            meta = PET_HEALTH_META.get(scope_uid, {})
            w_str = meta.get("weight", "未量測")
            v_str = meta.get("vax", "未設定")
            logs_summary = "\n".join(logs) if len(logs) > 0 else "今日尚無飲食與排泄紀錄"
            vet_text = f"🩺【{active_pet} · 獸醫看診健康問診摘要】\n• 最新體重：{w_str}\n• 驅蟲疫苗：{v_str}\n• 今日飲食排泄與異常時間軸：\n{logs_summary}"
            share_vet_uri = f"https:{S}{S}line.me{S}R{S}share?text={urllib.parse.quote(vet_text)}"
            vet_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#228BE6", padding_all="14px", contents=[
                    TextComponent(text=f"🩺 {active_pet} · 獸醫看診問診摘要", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    TextComponent(text=f"⚖️ 最新體重：{w_str}　｜　💉 驅蟲疫苗：{v_str}", size="xs", weight="bold", color="#1864AB", wrap=True),
                    BoxComponent(layout="vertical", background_color="#E7F5FF", corner_radius="10px", padding_all="10px", contents=[
                        TextComponent(text=logs_summary, size="xs", color="#1A1B1E", wrap=True)
                    ])
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    ButtonComponent(style="primary", color="#228BE6", height="sm", action=URIAction(label="📤 一鍵轉傳看診摘要", uri=share_vet_uri)),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日日報", text="今日日報"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="獸醫看診問診摘要", contents=vet_card))
            return
        # 2. 修改／刪除今日已記錄的照護狀況
        if txt in ["修改狀況", "刪除狀況", "修改紀錄", "編輯狀況"]:
            res = call_sheet({"action": "get_today_items", "user_id": scope_uid})
            items = res.get("items", [])
            body_items = [
                TextComponent(text=f"目前管理對象：【{active_pet}】", size="sm", weight="bold", color="#FF6B4A", wrap=True),
                TextComponent(text="• 點「✏️ 改」：可直接輸入新文字覆蓋該筆狀況內容\n• 點「❌ 刪」：立即刪除該筆錯誤紀錄", size="xxs", color="#888888", wrap=True)
            ]
            footer_items = []
            if len(items) == 0:
                body_items.append(TextComponent(text="（今天目前還沒有任何狀況紀錄喔！）", size="xs", color="#888888", margin="md"))
            else:
                S = chr(47)
                for it in items[-5:]:
                    r_num = it.get("row_num")
                    short_detail = str(it.get("detail", ""))[:10]
                    edit_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote(f'改狀況:{r_num}:')}"
                    footer_items.append(ButtonComponent(style="secondary", height="sm", action=URIAction(label=f"✏️ 改 [{it.get('time')}] {short_detail}"[:38], uri=edit_uri)))
                    footer_items.append(ButtonComponent(style="secondary", height="sm", action=MessageAction(label=f"❌ 刪 [{it.get('time')}] {short_detail}"[:38], text=f"刪狀況:{r_num}")))
            footer_items.append(ButtonComponent(style="primary", color="#FF6B4A", height="sm", action=MessageAction(label="📊 返回今日日報", text="今日日報")))
            edit_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text=f"✏️ 修改／刪除「{active_pet}」今日狀況", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="md", background_color="#FFFFFF", contents=body_items),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=footer_items)
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="修改／刪除今日照護狀況", contents=edit_card))
            return

        if txt.startswith("改狀況:"):
            parts = txt.split(":", 2)
            _ = parts.pop(0)
            row_num = parts.pop(0).strip() if parts else ""
            new_text = parts.pop(0).strip() if parts else ""
            if row_num and new_text:
                call_sheet({"action": "edit_log", "user_id": scope_uid, "row_num": row_num, "detail": new_text})
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已成功修改「{active_pet}」的該筆狀況為：「{new_text}」！\n輸入「今日日報」可查看最新完整紀錄。"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請在冒號後面輸入修改後的狀況文字喔！"))
            return

        if txt.startswith("刪狀況:"):
            row_num = txt[4:].strip()
            call_sheet({"action": "delete_log", "user_id": scope_uid, "row_num": row_num})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已成功刪除「{active_pet}」的該筆錯誤狀況紀錄！\n請點擊主畫面上的按鈕重新記錄正確狀態。"))
            return

        # 3. 定時放飯鬧鐘設定
        if txt in ["餵食時間", "放飯時間", "鬧鐘設定"]:
            S = chr(47)
            custom_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('放飯:')}"
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            cur_t = st.get("care_times", "尚未設定")
            rem_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text=f"⏰ {active_pet} · 定時放飯／保健鬧鐘", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="md", background_color="#FFFFFF", contents=[
                    TextComponent(text=f"目前設定時段：{cur_t}", size="sm", weight="bold", color="#1A1B1E", wrap=True),
                    BoxComponent(layout="horizontal", spacing="sm", contents=[
                        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="早晚8點", text="放飯:08:00, 20:00")),
                        ButtonComponent(style="secondary", height="sm", action=MessageAction(label="早中晚三餐", text="放飯:08:00, 13:00, 19:00"))
                    ])
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    ButtonComponent(style="primary", color="#228BE6", height="sm", action=URIAction(label="✏️ 自訂多時段（如 08:30, 21:00）", uri=custom_uri)),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🔕 關閉放飯提醒", text="放飯:關閉"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="汪喵定時放飯鬧鐘", contents=rem_card))
            return

        if txt.startswith("放飯:") or txt.startswith("放飯："):
            t_val = txt[3:].strip().replace("，", ", ").replace("：", ":")
            call_sheet({"action": "set_care_times", "user_id": scope_uid, "user_name": uname, "care_times": t_val})
            msg = f"🔕 已關閉「{active_pet}」的每日定時放飯提醒。" if t_val == "關閉" else f"🥣 設定成功！系統將於每天【{t_val}】準時推播「{active_pet}」的放飯換水提醒卡片！"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            return
        # 4. 飼主緊急電話與住家地址管理
        if txt in ["管理飼主電話", "修改飼主電話", "飼主電話"]:
            S = chr(47)
            edit_phone_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('飼主電話:')}"
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            cur_phone = st.get("owner_phone", "尚未設定")
            phone_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text="📞 飼主緊急電話管理", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="md", background_color="#FFFFFF", contents=[
                    TextComponent(text=f"目前登記號碼：{cur_phone}", size="sm", weight="bold", color="#1A1B1E", wrap=True)
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    ButtonComponent(style="primary", color="#228BE6", height="sm", action=URIAction(label="✏️ 輸入／修改新號碼", uri=edit_phone_uri)),
                    ButtonComponent(style="primary", color="#FA5252", height="sm", action=MessageAction(label="🗑️ 刪除目前飼主電話", text="刪除飼主電話")),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日日報", text="今日日報"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="飼主緊急電話管理", contents=phone_card))
            return

        if txt in ["刪除飼主電話", "清除飼主電話"]:
            call_sheet({"action": "set_owner_phone", "user_id": scope_uid, "user_name": uname, "phone": "尚未設定"})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🗑️ 已刪除原本登記的飼主緊急電話！輸入「今日日報」可返回主畫面。"))
            return

        if txt.startswith("飼主電話:") or txt.startswith("飼主電話："):
            p_val = txt[5:].strip()
            call_sheet({"action": "set_owner_phone", "user_id": scope_uid, "user_name": uname, "phone": p_val})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"📞 已設定飼主緊急直撥電話為【{p_val}】！輸入「今日日報」可立即一鍵撥號。"))
            return

        if txt in ["管理地址", "住家地址", "修改地址", "地址"]:
            S = chr(47)
            edit_addr_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('地址:')}"
            loc_uri = f"https:{S}{S}line.me{S}R{S}nv{S}location{S}"
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            cur_loc = st.get("last_location", "尚未設定")
            addr_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text="🏠 毛孩住家／寄宿地址管理", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="md", background_color="#FFFFFF", contents=[
                    TextComponent(text=f"目前登記位置：{cur_loc}", size="sm", weight="bold", color="#1A1B1E", wrap=True)
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=[
                    ButtonComponent(style="primary", color="#228BE6", height="sm", action=URIAction(label="✏️ 直接輸入／修改文字地址", uri=edit_addr_uri)),
                    ButtonComponent(style="secondary", height="sm", action=URIAction(label="📍 傳送 GPS 定位座標", uri=loc_uri)),
                    ButtonComponent(style="primary", color="#FA5252", height="sm", action=MessageAction(label="🗑️ 刪除目前登記地址", text="刪除地址")),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日日報", text="今日日報"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="毛孩住家地址管理", contents=addr_card))
            return

        if txt.startswith("地址:") or txt.startswith("地址："):
            addr_val = txt[3:].strip()
            call_sheet({"action": "set_address", "user_id": scope_uid, "user_name": uname, "address": addr_val})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🏠 已更新毛孩住家／協尋位置為【{addr_val}】！輸入「今日日報」可查看最新地圖按鈕。"))
            return

        if txt in ["刪除地址", "清除地址"]:
            call_sheet({"action": "set_address", "user_id": scope_uid, "user_name": uname, "address": "尚未設定"})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🗑️ 已刪除原本登記的住家地址！輸入「今日日報」可返回主畫面。"))
            return
        # 5. 守護群人員管理 ＋ 更改毛孩名字
        if txt in ["管理人員", "人員名單", "修改人員", "刪除人員"]:
            S = chr(47)
            bind_cmd = urllib.parse.quote(f"綁定人員:{uid}")
            share_text = urllib.parse.quote(f"邀請您加入「汪喵平安守護 ＆ 寵物照護日記」守護群（不限人數）！點擊下方連結加入後，每次餵食、鏟屎、散步或異常狀況，您都會即時收到通知：\nhttps:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{bind_cmd}")
            share_uri = f"https:{S}{S}line.me{S}R{S}share?text={share_text}"
            st = call_sheet({"action": "today_report", "user_id": uid, "user_name": uname})
            f_ids = st.get("family_ids", [])
            body_contents = [
                TextComponent(text=f"目前已綁定守護人員：{len(f_ids)} 位（不限人數上限）", size="sm", weight="bold", color="#1A1B1E"),
                TextComponent(text="照護打卡與走失警報會同步發送給以下所有成員。如需移除特定家人／保母，請直接點擊下方移除按鈕：", size="xs", color="#666666", wrap=True)
            ]
            footer_btns = []
            if len(f_ids) == 0:
                body_contents.append(TextComponent(text="（目前尚未綁定任何家人或保母人員）", size="xs", color="#888888", margin="md"))
            else:
                for idx, fid in enumerate(f_ids[-10:], 1):
                    f_name = get_user_name(fid)
                    disp_f = f_name if f_name != "照護者" else f"人員 #{idx} ({fid[:6]}...)"
                    footer_btns.append(ButtonComponent(style="secondary", height="sm", action=MessageAction(label=f"❌ 移除：{disp_f}"[:20], text=f"移除人員:{fid}")))
                footer_btns.append(ButtonComponent(style="primary", color="#FA5252", height="sm", action=MessageAction(label="🗑️ 一鍵清空全部人員名單", text="清空人員")))
            footer_btns.append(ButtonComponent(style="primary", color="#228BE6", height="sm", action=URIAction(label="➕ 新增家人／保母（不限人數）", uri=share_uri)))
            footer_btns.append(ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日日報", text="今日日報")))
            fam_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text="👥 家人／保母人員管理（新增與移除）", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="md", background_color="#FFFFFF", contents=body_contents),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=footer_btns)
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="家人／保母人員管理", contents=fam_card))
            return

        if txt.startswith("移除人員:"):
            target_fid = txt[5:].strip()
            res = call_sheet({"action": "remove_family", "user_id": uid, "family_id": target_fid})
            rem_cnt = res.get("count", 0)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已成功移除該位人員！目前剩餘 {rem_cnt} 位毛孩守護成員。"))
            return

        if txt in ["清空人員", "全部移除人員"]:
            call_sheet({"action": "clear_family", "user_id": uid})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🗑️ 已為您清空所有家人／保母人員名單！隨時可透過邀請連結重新加入。"))
            return

        if txt.startswith("改名:") or txt.startswith("改名："):
            new_name = txt[3:].strip()
            if not new_name:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請在「改名:」後面輸入新的毛孩名字喔！例如：改名:橘子"))
                return
            old_name = active_pet
            if old_name in pet_list:
                pet_list[pet_list.index(old_name)] = new_name
            else:
                pet_list.append(new_name)
            PET_LIST_MAP[uid] = pet_list
            ACTIVE_PET_MAP[uid] = new_name
            call_sheet({"action": "set_pet", "user_id": scope_uid, "user_name": uname, "pet_name": new_name})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✏️ 已成功將「{old_name}」更名為「{new_name}」（原本的紀錄與照片已完整保留）！輸入「今日日報」可查看最新畫面。"))
            return

        # 6. 毛孩走失緊急協尋系統
        if txt in ["毛孩走失", "走失協尋", "走失"]:
            S = chr(47)
            st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
            o_phone = st.get("owner_phone", "尚未設定")
            loc_str = st.get("last_location", "尚未設定")
            clean_addr = next(iter(str(loc_str).split("("))).strip() if "(" in str(loc_str) else str(loc_str).strip()
            if not clean_addr or clean_addr == "尚未設定":
                clean_addr = "新北市五股區周邊（請飼主更新定位）"

            call_sheet({"action": "log_care", "user_id": scope_uid, "user_name": uname, "category": "健康異常", "detail": f"🚨【緊急走失協尋】「{active_pet}」於 {clean_addr} 走失，請全體成員協助留意！", "is_abnormal": True})

            poster_uri = f"{RENDER_BASE_URL}/lost_poster?scope_key={safe_key}&pet={urllib.parse.quote(active_pet)}&addr={urllib.parse.quote(clean_addr)}&phone={urllib.parse.quote(o_phone)}&openExternalBrowser=1"
            share_lost_txt = urllib.parse.quote(f"🚨【緊急協尋走失毛孩：{active_pet}】🚨\n📍 走失地點：{clean_addr}\n📞 飼主聯絡電話：{o_phone}\n\n請大家幫忙留意轉發！查看毛孩照片與即時協尋海報：\n{poster_uri}")
            share_lost_uri = f"https:{S}{S}line.me{S}R{S}share?text={share_lost_txt}"

            lost_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#C92A2A", padding_all="14px", contents=[
                    TextComponent(text=f"🚨 緊急協尋走失毛孩：{active_pet}", weight="bold", size="md", color="#FFFFFF", wrap=True),
                    TextComponent(text="已同步通報全體守護群成員", size="xs", color="#FFE3E3", weight="bold", wrap=True, margin="xs")
                ]),
                body=BoxComponent(layout="vertical", spacing="sm", background_color="#FFF5F5", contents=[
                    TextComponent(text=f"📍 最後走失地點：{clean_addr}", size="xs", color="#111111", weight="bold", wrap=True),
                    TextComponent(text=f"📞 飼主緊急電話：{o_phone}", size="xs", color="#111111", weight="bold", wrap=True),
                    TextComponent(text="💡 提示：協尋海報已自動放上相簿 App 設定的大頭貼封面照片！", size="xxs", color="#C92A2A", wrap=True, margin="sm")
                ]),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFF5F5", contents=[
                    ButtonComponent(style="primary", color="#C92A2A", height="sm", action=URIAction(label="🖼️ 開啟專屬尋寵協尋海報網頁", uri=poster_uri)),
                    ButtonComponent(style="primary", color="#FD7E14", height="sm", action=URIAction(label="📤 一鍵轉傳尋寵警報到群組", uri=share_lost_uri)),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="🎉 已尋獲平安回家（解除警報）", text="解除走失")),
                    ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日日報", text="今日日報"))
                ])
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"🚨 緊急協尋走失毛孩：{active_pet}", contents=lost_card))
            return

        if txt == "解除走失":
            call_sheet({"action": "log_care", "user_id": scope_uid, "user_name": uname, "category": "特別狀況", "detail": f"🎉 好消息！「{active_pet}」已平安尋獲回家，解除走失協尋警報！", "is_abnormal": False})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🎉 太棒了！已為「{active_pet}」記錄平安尋獲並解除警報！輸入「今日日報」可返回主畫面。"))
            return
        # 7. 多隻毛孩獨立檔案管理：切換毛孩、新增毛孩、刪除毛孩與綁定人員
        if txt in ["切換毛孩", "多隻毛孩", "毛孩名單", "管理毛孩"]:
            S = chr(47)
            add_pet_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('毛孩:')}"
            rename_pet_uri = f"https:{S}{S}line.me{S}R{S}oaMessage{S}{LINE_BOT_BASIC_ID}{S}?{urllib.parse.quote('改名:')}"
            body_items = [
                TextComponent(text=f"目前正在管理：【{active_pet}】", size="sm", weight="bold", color="#FF6B4A", wrap=True),
                TextComponent(text="每隻毛孩皆擁有獨立的照護統計、相簿 App 大頭貼與走失檔案，互不干擾：", size="xs", color="#666666", wrap=True)
            ]
            footer_btns = []
            for p_item in pet_list:
                is_cur = (p_item == active_pet)
                if is_cur:
                    footer_btns.append(ButtonComponent(style="primary", color="#12B886", height="sm", action=MessageAction(label=f"✅ 目前：{p_item}"[:20], text=f"切換至:{p_item}")))
                else:
                    footer_btns.append(ButtonComponent(style="secondary", height="sm", action=MessageAction(label=f"🐾 切換：{p_item}"[:20], text=f"切換至:{p_item}")))
                    if len(pet_list) > 1:
                        footer_btns.append(ButtonComponent(style="secondary", height="sm", action=MessageAction(label=f"🗑️ 刪除：{p_item}"[:20], text=f"刪毛孩:{p_item}")))

            footer_btns.append(ButtonComponent(style="secondary", height="sm", action=URIAction(label=f"✏️ 更改「{active_pet}」名字"[:20], uri=rename_pet_uri)))
            footer_btns.append(ButtonComponent(style="primary", color="#228BE6", height="sm", action=URIAction(label="➕ 新增另一隻毛孩檔案", uri=add_pet_uri)))
            footer_btns.append(ButtonComponent(style="secondary", height="sm", action=MessageAction(label="📊 返回今日日報", text="今日日報")))

            switch_card = BubbleContainer(
                size="mega",
                header=BoxComponent(layout="vertical", background_color="#1A1B1E", padding_all="14px", contents=[
                    TextComponent(text=f"🐾 多隻毛孩檔案管理（共 {len(pet_list)} 隻）", weight="bold", size="md", color="#FFFFFF", wrap=True)
                ]),
                body=BoxComponent(layout="vertical", spacing="md", background_color="#FFFFFF", contents=body_items),
                footer=BoxComponent(layout="vertical", spacing="sm", background_color="#FFFFFF", contents=footer_btns)
            )
            line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="多隻毛孩檔案管理", contents=switch_card))
            return

        if txt.startswith("切換至:"):
            target_p = txt[4:].strip()
            if target_p:
                if target_p not in pet_list:
                    pet_list.append(target_p)
                    PET_LIST_MAP[uid] = pet_list
                ACTIVE_PET_MAP[uid] = target_p
                scope_uid, active_pet, pet_list = get_pet_scope(uid)
                st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
                o_phone = st.get("owner_phone", "尚未設定")
                c_times = st.get("care_times", "尚未設定")
                loc_str = st.get("last_location", "尚未設定")
                logs = st.get("today_logs", [])
                logs_txt = "\n".join(logs) if len(logs) > 0 else "（今日尚無紀錄，點擊下方馬卡龍按鈕即可為這隻毛孩打卡）"
                lat, lon = parse_latlon(loc_str)
                card = make_pet_card(
                    f"🐾 {active_pet} · 今日照護交班日報",
                    f"共 {len(pet_list)} 隻毛孩 ｜ 鬧鐘：{c_times}",
                    f"{logs_txt}\n\n🏠 位置：{loc_str}",
                    scope_uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
                )
                line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"已切換至 {active_pet}", contents=card))
            return

        if txt.startswith("刪毛孩:"):
            del_p = txt[4:].strip()
            if del_p in pet_list and len(pet_list) > 1:
                pet_list.remove(del_p)
                PET_LIST_MAP[uid] = pet_list
                if ACTIVE_PET_MAP.get(uid) == del_p:
                    ACTIVE_PET_MAP[uid] = pet_list
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🗑️ 已移除毛孩「{del_p}」的切換標籤！目前切換回「{ACTIVE_PET_MAP[uid]}」。"))
            return

        if txt.startswith("毛孩:") or txt.startswith("毛孩：") or txt.startswith("寵物:") or txt.startswith("寵物："):
            p_val = txt[3:].strip()
            if p_val:
                if p_val not in pet_list:
                    pet_list.append(p_val)
                    PET_LIST_MAP[uid] = pet_list
                ACTIVE_PET_MAP[uid] = p_val
                scope_uid, active_pet, pet_list = get_pet_scope(uid)
                call_sheet({"action": "set_pet", "user_id": scope_uid, "user_name": uname, "pet_name": p_val})
                st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
                o_phone = st.get("owner_phone", "尚未設定")
                c_times = st.get("care_times", "尚未設定")
                loc_str = st.get("last_location", "尚未設定")
                lat, lon = parse_latlon(loc_str)
                card = make_pet_card(
                    f"🐾 {p_val} · 專屬毛孩檔案已建立",
                    f"目前共有 {len(pet_list)} 隻毛孩 ｜ 鬧鐘：{c_times}",
                    f"已為「{p_val}」開啟獨立照護儀表板！所有放飯、鏟屎、散步統計與雲端相簿 App 都會獨立計算。\n\n🏠 位置：{loc_str}",
                    scope_uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
                )
                line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text=f"已新增毛孩 {p_val}", contents=card))
            return

        if txt.startswith("綁定人員:"):
            caregiver_uid = txt[5:].strip()
            if caregiver_uid == uid:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 不能綁定自己喔！請把邀請卡片轉傳給其他家人或寵物保母點擊。"))
                return
            res = call_sheet({"action": "bind_family", "user_id": caregiver_uid, "family_id": uid})
            p_name = res.get("pet_name", "毛孩寶貝")
            cnt = res.get("count", 1)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🤝 加入成功！您已成為「{p_name}」的第 {cnt} 位守護成員（不限人數上限）。\n只要照護者點擊放飯、鏟屎、散步、特別狀況或開啟視訊，您都會即時收到通知，每天 18:00 也會收到今日寵物照護日報！"))
            return

        # 8. 查看今日寵物照護日報（旗艦 10.0 商業精品級 App 模式雙卡輪播版）
        st = call_sheet({"action": "today_report", "user_id": scope_uid, "user_name": uname})
        f_cnt = st.get("family_count", 0)
        o_phone = st.get("owner_phone", "尚未設定")
        c_times = st.get("care_times", "尚未設定")
        loc_str = st.get("last_location", "尚未設定")
        logs = st.get("today_logs", [])
        logs_txt = "\n".join(logs) if len(logs) > 0 else "（今日尚無紀錄，點擊下方馬卡龍按鈕即可快樂交班）"

        lat, lon = parse_latlon(loc_str)
        card = make_pet_card(
            f"🐾 {active_pet} · 今日照護交班日報",
            f"共 {len(pet_list)} 隻毛孩 ｜ 守護群：{f_cnt} 位 ｜ 鬧鐘：{c_times}",
            f"{logs_txt}\n\n🏠 位置：{loc_str}",
            scope_uid, lat=lat, lon=lon, addr=loc_str, owner_phone=o_phone
        )
        line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="今日寵物照護日報", contents=card))
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🐾 系統小提示：{str(e)[:60]}（請輸入「今日日報」刷新畫面）"))
