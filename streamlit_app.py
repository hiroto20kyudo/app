from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime, time, timedelta
from typing import Optional

import streamlit as st
from streamlit_calendar import calendar as st_calendar

# =========================
# 1. ページ設定 & スタイル
# =========================
st.set_page_config(page_title="バイトシフト作成", layout="wide")

st.markdown("""
    <style>
    /* 警告メッセージと標準ツールバーを非表示 */
    [data-testid="stNotification"], .stAlert, .fc-header-toolbar {
        display: none !important;
    }
    /* 以前のスタイル：ドットを消して太字にする */
    .fc .fc-daygrid-event-dot { display: none !important; }
    .fc .fc-daygrid-dot-event .fc-event-title { margin-left: 0 !important; }
    .fc .fc-daygrid-block-event, .fc .fc-daygrid-dot-event { 
        background: none !important; border: none !important; 
    }
    .fc .fc-event-main { color: #333 !important; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

DB_PATH = "app.db"

# =========================
# 2. DB 操作
# =========================
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ev_date TEXT NOT NULL, start_time TEXT, end_time TEXT, category TEXT NOT NULL, title TEXT NOT NULL, place TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS availability (id INTEGER PRIMARY KEY AUTOINCREMENT, workplace TEXT NOT NULL, day_type TEXT NOT NULL, dow INTEGER, start_time TEXT NOT NULL, end_time TEXT NOT NULL);")
    cur.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), max_hours_per_day INTEGER, max_hours_per_week INTEGER);")
    cur.execute("INSERT OR IGNORE INTO settings (id, max_hours_per_day, max_hours_per_week) VALUES (1, 6, 20);")
    cur.execute("CREATE TABLE IF NOT EXISTS wages (workplace TEXT PRIMARY KEY, hourly_wage INTEGER NOT NULL);")
    conn.commit(); conn.close()

def add_event(ev_date, start, end, cat, title, place=None):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO events (ev_date, start_time, end_time, category, title, place) VALUES (?, ?, ?, ?, ?, ?)", (ev_date, start, end, cat, title, place))
    conn.commit(); conn.close()

def delete_event(ev_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id = ?", (ev_id,))
    conn.commit(); conn.close()

def fetch_events_in_month(y, m):
    start, end = f"{y}-{m:02d}-01", f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, ev_date, start_time, end_time, category, title, place FROM events WHERE ev_date BETWEEN ? AND ? ORDER BY ev_date ASC, start_time ASC", (start, end))
    rows = cur.fetchall(); conn.close()
    by_date = {}
    for r in rows:
        ev = {"id": r[0], "date": r[1], "start": r[2], "end": r[3], "category": r[4], "title": r[5], "place": r[6]}
        by_date.setdefault(ev["date"], []).append(ev)
    return by_date

def get_settings():
    conn = get_conn(); row = conn.cursor().execute("SELECT max_hours_per_day, max_hours_per_week FROM settings WHERE id=1").fetchone(); conn.close()
    return row if row else (6, 20)

def upsert_settings(d, w):
    conn = get_conn(); conn.cursor().execute("UPDATE settings SET max_hours_per_day=?, max_hours_per_week=? WHERE id=1", (d, w)); conn.commit(); conn.close()

def get_wages():
    conn = get_conn(); rows = conn.cursor().execute("SELECT workplace, hourly_wage FROM wages").fetchall(); conn.close()
    return {r[0]: int(r[1]) for r in rows}

def upsert_wage(wp, wage):
    conn = get_conn(); conn.cursor().execute("INSERT INTO wages(workplace, hourly_wage) VALUES (?, ?) ON CONFLICT(workplace) DO UPDATE SET hourly_wage = excluded.hourly_wage", (wp, wage)); conn.commit(); conn.close()

def get_availabilities():
    conn = get_conn(); rows = conn.cursor().execute("SELECT id, workplace, day_type, dow, start_time, end_time FROM availability ORDER BY workplace, day_type, dow, start_time").fetchall(); conn.close()
    return [{"id": r[0], "workplace": r[1], "day_type": r[2], "dow": r[3], "start_time": r[4], "end_time": r[5]} for r in rows]

def add_availability(wp, dt, dow, s, e):
    conn = get_conn(); conn.cursor().execute("INSERT INTO availability(workplace, day_type, dow, start_time, end_time) VALUES (?, ?, ?, ?, ?)", (wp, dt, dow, s, e)); conn.commit(); conn.close()

def delete_availability(aid):
    conn = get_conn(); conn.cursor().execute("DELETE FROM availability WHERE id = ?", (aid,)); conn.commit(); conn.close()

def delete_proposals_in_range(s, e):
    conn = get_conn(); conn.cursor().execute("DELETE FROM events WHERE category = 'proposal' AND ev_date BETWEEN ? AND ?", (s, e)); conn.commit(); conn.close()

def fetch_events_between(s, e):
    conn = get_conn(); rows = conn.cursor().execute("SELECT id, ev_date, start_time, end_time, category, title, place FROM events WHERE ev_date BETWEEN ? AND ? ORDER BY ev_date ASC, start_time ASC", (s, e)).fetchall(); conn.close()
    return [{"id": r[0], "date": r[1], "start": r[2], "end": r[3], "category": r[4], "title": r[5], "place": r[6]} for r in rows]

# =========================
# 3. シフト提案ロジック
# =========================
def _t(s): return datetime.strptime(s, "%H:%M").time()
def monday_of(d): return d - timedelta(days=d.weekday())

def propose_week(wsd, max_d, max_w, wages, avails, events):
    busy = [e for e in events if e["category"] in ("class", "job", "private", "work")]
    def is_busy(d, s, e):
        ss, ee, ds = _t(s), _t(e), d.strftime("%Y-%m-%d")
        for b in busy:
            if b["date"] != ds: continue
            if b["start"] is None or b["end"] is None: return True
            if (_t(b["start"]) < ee) and (ss < _t(b["end"])): return True
        return False
    cands = []
    for i in range(7):
        d = wsd + timedelta(days=i)
        dow, is_we = d.weekday(), d.weekday() >= 5
        for a in avails:
            if (a["day_type"] == "weekday" and is_we) or (a["day_type"] == "weekend" and not is_we) or (a["day_type"] == "dow" and a["dow"] != dow): continue
            cur, end = datetime.combine(d, _t(a["start_time"])), datetime.combine(d, _t(a["end_time"]))
            while cur + timedelta(minutes=60) <= end:
                s, e = cur.strftime("%H:%M"), (cur + timedelta(minutes=60)).strftime("%H:%M")
                if not is_busy(d, s, e): cands.append((d, s, e, a["workplace"], wages.get(a["workplace"], 0)))
                cur += timedelta(minutes=60)
    picked, day_hrs = [], {}
    cands.sort(key=lambda x: x[4], reverse=True)
    for c in cands:
        d, s, e, w, wage = c
        if len(picked) >= max_w or day_hrs.get(d, 0) >= max_d: continue
        if any(d2 == d and not (e <= s2 or e2 <= s) for (d2, s2, e2, _, _) in picked): continue
        picked.append(c); day_hrs[d] = day_hrs.get(d, 0) + 1
    picked.sort(key=lambda x: (x[0], x[3], x[1]))
    merged = []
    i = 0
    while i < len(picked):
        d, s, e, w, wage = picked[i]
        j, cur_e = i + 1, e
        while j < len(picked) and picked[j][0] == d and picked[j][3] == w and picked[j][1] == cur_e:
            cur_e, j = picked[j][2], j + 1
        merged.append({"date": d.strftime("%Y-%m-%d"), "start": s, "end": cur_e, "workplace": w})
        i = j
    return merged

# =========================
# 4. UI ヘルパー & ダイアログ
# =========================
def format_event_label(ev):
    return f'{ev["start"]}-{ev["end"]} {ev["title"]}' if ev["start"] else ev["title"]

@st.dialog("予定を追加")
def show_add_event_dialog():
    selected_date = st.session_state.get("selected_date")
    st.write(f"📅 **{selected_date}** の予定を入力してください")
    all_day = st.checkbox("終日", value=False)
    with st.form("dialog_add", clear_on_submit=True):
        category_ui = st.selectbox("種別", ["class（授業）", "job（就活）", "private（遊び）", "work（確定バイト）", "proposal（提案シフト）"])
        cat_map = {"class（授業）": "class", "job（就活）": "job", "private（遊び）": "private", "work（確定バイト）": "work", "proposal（提案シフト）": "proposal"}
        s_t, e_t = (None, None) if all_day else (st.time_input("開始", value=_t("10:00")).strftime("%H:%M"), st.time_input("終了", value=_t("12:00")).strftime("%H:%M"))
        title = st.text_input("タイトル", placeholder="例：サンマルク")
        place = st.text_input("場所・店名")
        if st.form_submit_button("保存する", use_container_width=True):
            if not title.strip(): st.error("タイトルを入力してください")
            else:
                add_event(selected_date, s_t, e_t, cat_map[category_ui], title.strip(), place.strip() or None)
                st.session_state["cal_gen"] += 1
                st.session_state["skip_next_dateclick"] = True
                st.rerun()

# =========================
# 5. メインアプリ
# =========================
init_db()
st.title("📅 バイトシフト作成アプリ")

# セッション初期化 (KeyError防止)
st.session_state.setdefault("sel_year", date.today().year)
st.session_state.setdefault("sel_month", date.today().month)
st.session_state.setdefault("cal_gen", 0)
st.session_state.setdefault("skip_next_dateclick", False)
st.session_state.setdefault("selected_date", None)
st.session_state.setdefault("open_add_dialog", False)

# 年月選択
c1, c2 = st.columns([2, 3])
ui_year = c1.number_input("年", 2020, 2035, value=st.session_state["sel_year"], key="input_year")
ui_month = c2.selectbox("月", list(range(1, 13)), index=st.session_state["sel_month"]-1, key="input_month")

if ui_year != st.session_state["sel_year"] or ui_month != st.session_state["sel_month"]:
    st.session_state["sel_year"], st.session_state["sel_month"] = int(ui_year), int(ui_month)
    st.session_state["cal_gen"] += 1
    st.rerun()

year, month = st.session_state["sel_year"], st.session_state["sel_month"]
st.markdown(f"<h3 style='text-align: center;'>{year}年{month}月</h3>", unsafe_allow_html=True)

# =========================
# 6. サイドバー
# =========================
st.sidebar.header("🧠 シフト提案")
max_day, max_week = get_settings()
new_max_day = st.sidebar.number_input("1日上限（時間）", 0, 24, max_day, 1)
new_max_week = st.sidebar.number_input("週上限（時間）", 0, 80, max_week, 1)
if st.sidebar.button("上限を保存"):
    upsert_settings(int(new_max_day), int(new_max_week)); st.sidebar.success("保存完了")

wages = get_wages()
wp = st.sidebar.selectbox("バイト先", ["サンマルク", "成城石井"])
wage_val = st.sidebar.number_input("時給（円）", 0, 10000, int(wages.get(wp, 1100)), 10)
if st.sidebar.button("時給を保存"):
    upsert_wage(wp, int(wage_val)); st.sidebar.success("保存完了")

st.sidebar.subheader("労働可能時間帯")
day_type_ui = st.sidebar.selectbox("曜日タイプ", ["平日", "土日", "曜日指定"])
day_type = {"平日": "weekday", "土日": "weekend", "曜日指定": "dow"}[day_type_ui]
dow = ["月", "火", "水", "木", "金", "土", "日"].index(st.sidebar.selectbox("曜日", ["月", "火", "水", "木", "金", "土", "日"])) if day_type == "dow" else None
a_s = st.sidebar.time_input("開始", value=_t("18:00")).strftime("%H:%M")
a_e = st.sidebar.time_input("終了", value=_t("22:00")).strftime("%H:%M")
if st.sidebar.button("時間帯を追加"):
    add_availability(wp, day_type, dow, a_s, a_e); st.rerun()

avs = get_availabilities()
for a in avs:
    col = st.sidebar.columns([4, 1])
    col[0].write(f'{a["workplace"]} | {a["start_time"]}-{a["end_time"]}')
    if col[1].button("×", key=f"av_{a['id']}"): delete_availability(a["id"]); st.rerun()

st.sidebar.subheader("提案生成")
week_start = monday_of(date.today())
if st.sidebar.button("今週の提案を作成"):
    w, a = get_wages(), get_availabilities()
    if not a or not w: st.sidebar.error("設定不足")
    else:
        s_s, e_s = week_start.strftime("%Y-%m-%d"), (week_start + timedelta(days=6)).strftime("%Y-%m-%d")
        delete_proposals_in_range(s_s, e_s)
        res = propose_week(week_start, max_day, max_week, w, a, fetch_events_between(s_s, e_s))
        for m in res: add_event(m["date"], m["start"], m["end"], "proposal", "提案シフト", m["workplace"])
        st.session_state["cal_gen"] += 1; st.rerun()

# =========================
# 7. カレンダー表示
# =========================
events_by_date = fetch_events_in_month(year, month)
fc_events = []
for d_key, evs in events_by_date.items():
    for ev in evs:
        fc_events.append({
            "title": format_event_label(ev),
            "start": f"{d_key}T{ev['start']}:00" if ev["start"] else d_key,
            "end": f"{d_key}T{ev['end']}:00" if ev["end"] else d_key,
            "allDay": not ev["start"],
            "textColor": "#E65100" if ev["category"] == "proposal" else "#333"
        })

opts = {"initialView": "dayGridMonth", "locale": "ja", "height": 650, "initialDate": f"{year}-{month:02d}-01", "headerToolbar": False, "selectable": True}

state = st_calendar(
    events=fc_events, options=opts, callbacks=["dateClick"],
    key=f"calendar_{year}_{month}_{st.session_state['cal_gen']}",
)

# クリックハンドラ
if st.session_state["skip_next_dateclick"]:
    st.session_state["skip_next_dateclick"] = False
elif state and "dateClick" in state:
    click_data = state["dateClick"]
    clicked_raw = click_data.get("dateStr") or click_data.get("date")
    if clicked_raw:
        st.session_state["selected_date"] = clicked_raw.split("T")[0]
        st.session_state["open_add_dialog"] = True
        st.rerun()

if st.session_state.get("open_add_dialog"):
    st.session_state["open_add_dialog"] = False
    show_add_event_dialog()

# =========================
# 8. 予定一覧 / 削除
# =========================
st.divider()
flat = [ev for sub in events_by_date.values() for ev in sub]
for ev in flat:
    cols = st.columns([5, 1])
    cols[0].write(f"{ev['date']} | {format_event_label(ev)}")
    if cols[1].button("削除", key=f"del_{ev['id']}"):
        delete_event(ev["id"]); st.session_state["cal_gen"] += 1; st.rerun()