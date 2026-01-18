from __future__ import annotations

import sqlite3
import calendar
from datetime import date, datetime, time, timedelta
from typing import Optional

import streamlit as st
from streamlit_calendar import calendar as st_calendar

import os
st.caption(f"RUNNING FILE: {os.path.abspath(__file__)}")


DB_PATH = "app.db"


# ---------- DB ----------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ev_date TEXT NOT NULL,          -- YYYY-MM-DD
        start_time TEXT,                -- HH:MM (nullable, 終日はNULLでもOK)
        end_time TEXT,                  -- HH:MM
        category TEXT NOT NULL,         -- class / job / private / work / proposal
        title TEXT NOT NULL,
        place TEXT                      -- store名など（任意）
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workplace TEXT NOT NULL,        -- サンマルク / 成城石井
        day_type TEXT NOT NULL,         -- weekday / weekend / dow
        dow INTEGER,                    -- 0=Mon..6=Sun（day_type='dow'の時だけ）
        start_time TEXT NOT NULL,       -- HH:MM
        end_time TEXT NOT NULL          -- HH:MM
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        max_hours_per_day INTEGER,
        max_hours_per_week INTEGER
    );
    """)
    cur.execute("""
    INSERT OR IGNORE INTO settings (id, max_hours_per_day, max_hours_per_week)
    VALUES (1, 6, 20);
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS wages (
        workplace TEXT PRIMARY KEY,
        hourly_wage INTEGER NOT NULL
    );
    """)

    conn.commit()
    conn.close()


def add_event(ev_date: str, start_time: Optional[str], end_time: Optional[str],
             category: str, title: str, place: Optional[str] = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO events (ev_date, start_time, end_time, category, title, place)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ev_date, start_time, end_time, category, title, place),
    )
    conn.commit()
    conn.close()


def delete_event(event_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def fetch_events_in_month(year: int, month: int):
    start = f"{year}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end = f"{year}-{month:02d}-{last_day:02d}"

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ev_date, start_time, end_time, category, title, place
        FROM events
        WHERE ev_date BETWEEN ? AND ?
        ORDER BY ev_date ASC, start_time ASC
        """,
        (start, end),
    )
    rows = cur.fetchall()
    conn.close()

    by_date = {}
    for r in rows:
        ev = {
            "id": r[0],
            "date": r[1],
            "start": r[2],
            "end": r[3],
            "category": r[4],
            "title": r[5],
            "place": r[6],
        }
        by_date.setdefault(ev["date"], []).append(ev)
    return by_date


def fetch_events_between(start_date: str, end_date: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, ev_date, start_time, end_time, category, title, place
        FROM events
        WHERE ev_date BETWEEN ? AND ?
        ORDER BY ev_date ASC, start_time ASC
        """,
        (start_date, end_date),
    )
    rows = cur.fetchall()
    conn.close()

    return [
        {"id": r[0], "date": r[1], "start": r[2], "end": r[3], "category": r[4], "title": r[5], "place": r[6]}
        for r in rows
    ]


# ---------- DB (proposal config) ----------
def upsert_settings(max_day: int, max_week: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE settings SET max_hours_per_day=?, max_hours_per_week=? WHERE id=1",
        (max_day, max_week),
    )
    conn.commit()
    conn.close()


def get_settings() -> tuple[int, int]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT max_hours_per_day, max_hours_per_week FROM settings WHERE id=1")
    row = cur.fetchone()
    conn.close()
    if not row:
        return 6, 20
    return int(row[0] or 6), int(row[1] or 20)


def upsert_wage(workplace: str, hourly_wage: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO wages(workplace, hourly_wage) VALUES(?, ?) "
        "ON CONFLICT(workplace) DO UPDATE SET hourly_wage=excluded.hourly_wage",
        (workplace, hourly_wage),
    )
    conn.commit()
    conn.close()


def get_wages() -> dict[str, int]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT workplace, hourly_wage FROM wages")
    rows = cur.fetchall()
    conn.close()
    return {r[0]: int(r[1]) for r in rows}


def add_availability(workplace: str, day_type: str, dow: Optional[int], start_time: str, end_time: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO availability(workplace, day_type, dow, start_time, end_time)
        VALUES (?, ?, ?, ?, ?)
        """,
        (workplace, day_type, dow, start_time, end_time),
    )
    conn.commit()
    conn.close()


def delete_availability(avail_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM availability WHERE id=?", (avail_id,))
    conn.commit()
    conn.close()


def get_availabilities() -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, workplace, day_type, dow, start_time, end_time
        FROM availability
        ORDER BY workplace, day_type, dow, start_time
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [
        {"id": r[0], "workplace": r[1], "day_type": r[2], "dow": r[3], "start_time": r[4], "end_time": r[5]}
        for r in rows
    ]


def delete_proposals_in_range(start_date: str, end_date: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM events
        WHERE category='proposal' AND ev_date BETWEEN ? AND ?
        """,
        (start_date, end_date),
    )
    conn.commit()
    conn.close()


# ---------- Proposal logic ----------
def _t(s: str) -> time:
    return datetime.strptime(s, "%H:%M").time()


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def propose_week(
    week_start_date: date,
    max_day: int,
    max_week: int,
    wages: dict[str, int],
    avails: list[dict],
    events: list[dict],
    slot_minutes: int = 60,
):
    busy = [e for e in events if e["category"] in ("class", "job", "private", "work")]

    def is_busy(d: date, s: str, e: str) -> bool:
        ss, ee = _t(s), _t(e)
        ds = d.strftime("%Y-%m-%d")
        for b in busy:
            if b["date"] != ds:
                continue
            if b["start"] is None or b["end"] is None:
                return True
            bs, be = _t(b["start"]), _t(b["end"])
            if (ss < be) and (bs < ee):
                return True
        return False

    candidates = []  # (d, start, end, workplace, wage)
    for i in range(7):
        d = week_start_date + timedelta(days=i)
        dow = d.weekday()
        is_weekend = dow >= 5

        for a in avails:
            if a["day_type"] == "weekday" and is_weekend:
                continue
            if a["day_type"] == "weekend" and not is_weekend:
                continue
            if a["day_type"] == "dow" and a["dow"] != dow:
                continue

            cur = datetime.combine(d, _t(a["start_time"]))
            end = datetime.combine(d, _t(a["end_time"]))
            while cur + timedelta(minutes=slot_minutes) <= end:
                s = cur.strftime("%H:%M")
                e = (cur + timedelta(minutes=slot_minutes)).strftime("%H:%M")
                if not is_busy(d, s, e):
                    w = a["workplace"]
                    candidates.append((d, s, e, w, wages.get(w, 0)))
                cur += timedelta(minutes=slot_minutes)

    picked = []
    day_hours: dict[date, int] = {}
    total = 0

    def has_adjacent(d, s, e, w):
        for (d2, s2, e2, w2, _) in picked:
            if d2 == d and w2 == w and (e2 == s or e == s2):
                return True
        return False

    def score(c):
        d, s, e, w, wage = c
        sc = wage
        if has_adjacent(d, s, e, w):
            sc += 200
        sc -= day_hours.get(d, 0) * 20
        return sc

    candidates.sort(key=score, reverse=True)

    for c in candidates:
        d, s, e, w, wage = c
        if total + 1 > max_week:
            continue
        if day_hours.get(d, 0) + 1 > max_day:
            continue

        conflict = any(d2 == d and not (e <= s2 or e2 <= s) for (d2, s2, e2, _, _) in picked)
        if conflict:
            continue

        picked.append(c)
        day_hours[d] = day_hours.get(d, 0) + 1
        total += 1

    picked.sort(key=lambda x: (x[0], x[3], x[1]))
    merged = []
    i = 0
    while i < len(picked):
        d, s, e, w, wage = picked[i]
        j = i + 1
        cur_s, cur_e = s, e
        hours = 1
        while j < len(picked):
            d2, s2, e2, w2, wage2 = picked[j]
            if d2 == d and w2 == w and wage2 == wage and s2 == cur_e:
                cur_e = e2
                hours += 1
                j += 1
            else:
                break
        merged.append({
            "date": d.strftime("%Y-%m-%d"),
            "start": cur_s,
            "end": cur_e,
            "workplace": w,
            "hours": hours,
            "income": hours * wage,
        })
        i = j

    return merged


# ---------- UI helpers ----------
def format_event_label(ev):
    if ev["start"] and ev["end"]:
        return f'{ev["start"]}-{ev["end"]} {ev["title"]}'
    return ev["title"]


@st.dialog("予定を追加")
def show_add_event_dialog(selected_date: str):
    st.write(f"📅 **{selected_date}** の予定を入力してください")
    all_day = st.checkbox("終日", value=False, key="dialog_all_day")

    with st.form("dialog_add", clear_on_submit=True):
        category_ui = st.selectbox(
            "種別",
            ["class（授業）", "job（就活）", "private（遊び）", "work（確定バイト）", "proposal（提案シフト）"],
            key="dialog_cat"
        )
        cat_map = {
            "class（授業）": "class",
            "job（就活）": "job",
            "private（遊び）": "private",
            "work（確定バイト）": "work",
            "proposal（提案シフト）": "proposal",
        }

        start_time = end_time = None
        if not all_day:
            col1, col2 = st.columns(2)
            st_val = col1.time_input("開始", value=_t("10:00"), key="dialog_st")
            et_val = col2.time_input("終了", value=_t("12:00"), key="dialog_et")
            start_time = st_val.strftime("%H:%M")
            end_time = et_val.strftime("%H:%M")

        title = st.text_input("タイトル", placeholder="例：サンマルク", key="dialog_title")
        place = st.text_input("場所・店名", key="dialog_place")

        submitted = st.form_submit_button("保存する", use_container_width=True)
        if submitted:
            if not title.strip():
                st.error("タイトルを入力してください")
                return

            add_event(selected_date, start_time, end_time, cat_map[category_ui], title.strip(), place.strip() or None)

            # カレンダー再生成して「残りクリック」問題も避ける
            st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
            st.session_state["skip_next_dateclick"] = True
            st.rerun()



# ---------- main ----------
st.set_page_config(page_title="バイトシフト作成", layout="wide")

st.markdown("""
    <style>
    .fc-header-toolbar {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

init_db()

st.title("📅 バイトシフト作成アプリ")

# ★ year/month のゴミが残っても影響しないように隔離
st.session_state.pop("year", None)
st.session_state.pop("month", None)


today = date.today()

# アプリ側の年月
st.session_state.setdefault("sel_year", today.year)
st.session_state.setdefault("sel_month", today.month)

# ウィジェット側（year/month を絶対に使わない）
st.session_state.setdefault("ui_year", st.session_state["sel_year"])
st.session_state.setdefault("ui_month", st.session_state["sel_month"])

c1, c2 = st.columns([2, 3])

ui_year = c1.number_input("年", 2020, 2035, key="ui_year")
ui_month = c2.selectbox("月", list(range(1, 13)), key="ui_month")

if ui_year != st.session_state["sel_year"] or ui_month != st.session_state["sel_month"]:
    st.session_state["sel_year"] = int(ui_year)
    st.session_state["sel_month"] = int(ui_month)
    st.session_state["cal_gen"] = st.session_state.get("cal_gen", 0) + 1
    st.session_state["skip_next_dateclick"] = True
    st.rerun()

year = st.session_state["sel_year"]
month = st.session_state["sel_month"]



# ---------- Sidebar: shift proposal ----------
st.sidebar.header("🧠 シフト提案")

# 上限
st.sidebar.subheader("上限設定")
max_day, max_week = get_settings()
new_max_day = st.sidebar.number_input("1日上限（時間）", 0, 24, max_day, 1)
new_max_week = st.sidebar.number_input("週上限（時間）", 0, 80, max_week, 1)
if st.sidebar.button("上限を保存", use_container_width=True):
    upsert_settings(int(new_max_day), int(new_max_week))
    st.sidebar.success("保存しました")

# 時給
st.sidebar.subheader("時給設定")
wages = get_wages()
wp = st.sidebar.selectbox("バイト先", ["サンマルク", "成城石井"])
w0 = wages.get(wp, 1100)
wage_val = st.sidebar.number_input("時給（円）", 0, 10000, int(w0), 10)
if st.sidebar.button("時給を保存", use_container_width=True):
    upsert_wage(wp, int(wage_val))
    st.sidebar.success("保存しました")

# 労働可能時間
st.sidebar.subheader("労働可能時間帯")
day_type_ui = st.sidebar.selectbox("曜日タイプ", ["平日", "土日", "曜日指定"])
day_type = {"平日": "weekday", "土日": "weekend", "曜日指定": "dow"}[day_type_ui]

dow = None
if day_type == "dow":
    dow_ui = st.sidebar.selectbox("曜日", ["月", "火", "水", "木", "金", "土", "日"])
    dow = ["月", "火", "水", "木", "金", "土", "日"].index(dow_ui)

a_start = st.sidebar.time_input("開始", value=_t("18:00")).strftime("%H:%M")
a_end = st.sidebar.time_input("終了", value=_t("22:00")).strftime("%H:%M")

col1, _ = st.sidebar.columns(2)
if col1.button("追加", use_container_width=True):
    if a_start >= a_end:
        st.sidebar.error("開始 < 終了 にしてください")
    else:
        add_availability(wp, day_type, dow, a_start, a_end)
        st.sidebar.success("追加しました")
        st.rerun()

# 一覧＆削除
avails = get_availabilities()
if avails:
    st.sidebar.caption("登録済み")
    for a in avails:
        label = f'{a["workplace"]} | {a["day_type"]}'
        if a["day_type"] == "dow":
            label += f'({a["dow"]})'
        label += f' | {a["start_time"]}-{a["end_time"]}'
        c1, c2 = st.sidebar.columns([4, 1])
        c1.write(label)
        if c2.button("×", key=f"avdel_{a['id']}"):
            delete_availability(a["id"])
            st.rerun()
else:
    st.sidebar.info("まだ登録がありません")

# 提案生成
st.sidebar.subheader("今週の提案")
week_start = monday_of(date.today())
st.sidebar.write(f"対象週：{week_start.strftime('%Y-%m-%d')} 〜")

if st.sidebar.button("今週の提案を作成", use_container_width=True):
    wages = get_wages()
    avails = get_availabilities()
    max_day, max_week = get_settings()

    if not avails:
        st.sidebar.error("労働可能時間帯が未登録です")
    elif not wages:
        st.sidebar.error("時給が未登録です")
    else:
        start_s = week_start.strftime("%Y-%m-%d")
        end_s = (week_start + timedelta(days=6)).strftime("%Y-%m-%d")

        delete_proposals_in_range(start_s, end_s)

        events_week = fetch_events_between(start_s, end_s)
        merged = propose_week(
            week_start_date=week_start,
            max_day=max_day,
            max_week=max_week,
            wages=wages,
            avails=avails,
            events=events_week,
            slot_minutes=60,
        )

        total_h = 0
        total_income = 0
        for m in merged:
            add_event(
                m["date"],
                m["start"],
                m["end"],
                "proposal",
                "提案シフト",
                m["workplace"],
            )
            total_h += m["hours"]
            total_income += m["income"]

        st.sidebar.success(f"作成：{total_h}時間 / {total_income:,}円")

        # 追加したイベントが表示されるよう、カレンダー再生成
        st.session_state["cal_gen"] += 1
        st.session_state["skip_next_dateclick"] = True
        st.rerun()


# ---------- Calendar ----------
events_by_date = fetch_events_in_month(int(year), int(month))

fc_events = []
for day_key, evs in events_by_date.items():
    for ev in evs:
        if ev["start"] and ev["end"]:
            start = f"{day_key}T{ev['start']}:00"
            end = f"{day_key}T{ev['end']}:00"
            all_day_flag = False
        else:
            start = day_key
            end = day_key
            all_day_flag = True

        item = {
            "title": format_event_label(ev),
            "start": start,
            "end": end,
            "allDay": all_day_flag,
        }

        # proposalは店名(place)で色分け（任意）
        if ev["category"] == "proposal":
            if ev["place"] == "サンマルク":
                item["textColor"] = "#E65100"
            elif ev["place"] == "成城石井":
                item["textColor"] = "#0D47A1"

        fc_events.append(item)


calendar_options = {
    "initialView": "dayGridMonth",
    "locale": "ja",
    "height": 650,
    "initialDate": f"{year}-{month:02d}-01",
    "timeZone": "Asia/Tokyo",
    "displayEventTime": False,
    "dayMaxEvents": True,
    "eventDisplay": "block",
    "headerToolbar": False,
}

cal_gen = st.session_state.get("cal_gen", 0)
state = st_calendar(
    events=fc_events,
    options=calendar_options,
    callbacks=["dateClick", "eventClick"],
    key=f"calendar_{year}_{month}_{st.session_state['cal_gen']}",
)



# dateClick の「残り」を1回捨てる
if st.session_state.get("skip_next_dateclick", False):
    st.session_state["skip_next_dateclick"] = False
else:
    if state and state.get("dateClick"):
        dc = state["dateClick"]
        raw = dc.get("dateStr") or dc.get("date") or ""
        clicked_date = raw[:10]
        show_add_event_dialog(clicked_date)


# ---------- List / Delete ----------
st.divider()
st.subheader("🗂 この月の予定一覧（削除）")
flat = [ev for evs in events_by_date.values() for ev in evs]

if not flat:
    st.info("この月の予定はまだありません。予定を追加してね")
else:
    for ev in flat:
        cols = st.columns([5, 1])
        cols[0].write(f"{ev['date']} | {format_event_label(ev)} | [{ev['category']}]")
        if cols[1].button("削除", key=f"del_{ev['id']}"):
            delete_event(ev["id"])
            st.session_state["cal_gen"] += 1
            st.session_state["skip_next_dateclick"] = True
            st.rerun()


