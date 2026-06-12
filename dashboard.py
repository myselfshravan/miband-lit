#!/usr/bin/env python3
"""Streamlit dashboard for the Mi Band 5: live heart rate + send notifications.

Run the band service first (it owns the BLE connection), then this dashboard.
This process only reads HR data and writes commands into the shared store.
"""
import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import store

store.init_db()

st.set_page_config(page_title="Mi Band 5", page_icon="❤️", layout="wide")
st.title("⌚︎ Mi Band 5 — Live Heart Rate")

CONNECTION_LABELS = {
    "connected": ("🔵", "Connected (authenticating)"),
    "authenticated": ("🟢", "Live"),
    "scanning": ("🟡", "Scanning for band"),
    "not_found": ("🔴", "Band not found"),
    "auth_failed": ("🔴", "Auth failed"),
    "disconnected": ("⚪", "Disconnected"),
    "error": ("🔴", "Error"),
}

# --- Sidebar: status + controls -------------------------------------------
with st.sidebar:
    st.header("Send to band")

    with st.form("notify_form", clear_on_submit=False):
        text = st.text_input("Message", value="Hello from your Mac")
        category = st.selectbox(
            "Type (changes the icon shown)",
            ["sms", "call", "missed_call", "email", "simple"],
            index=0,
        )
        sent = st.form_submit_button("Send notification", use_container_width=True)
        if sent:
            store.add_command("notify", {"text": text, "category": category})
            st.success("Queued — it'll appear on the band in ~1s.")

    st.divider()
    if st.button("📳 Vibrate band", use_container_width=True):
        store.add_command("vibrate", {"strong": True})
        st.toast("Buzz queued")

    st.divider()
    st.caption("Recent commands")
    for ts, kind, payload, status in store.recent_commands(6):
        when = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        detail = payload.get("text", "") if kind == "notify" else ""
        st.caption(f"{when} · {kind} {detail} · **{status}**")

    st.divider()
    window_min = st.slider("Chart window (minutes)", 1, 30, 5)


# --- Main: live metrics + chart (auto-refreshing fragment) -----------------
@st.fragment(run_every=2)
def live_view():
    conn_state = store.get_status("connection", "disconnected")
    icon, label = CONNECTION_LABELS.get(conn_state, ("⚪", conn_state))

    last = store.latest_reading()
    last_seen = store.get_status("last_seen")
    fresh = last_seen and (time.time() - float(last_seen) < 20)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", f"{icon} {label}")

    readings = store.recent_readings(window_min * 60)
    if readings:
        df = pd.DataFrame(readings, columns=["ts", "bpm"])
        df["time"] = pd.to_datetime(df["ts"], unit="s")
        cur = int(df["bpm"].iloc[-1])
        c2.metric("Current", f"{cur} bpm" if fresh else f"{cur} bpm (stale)")
        c3.metric("Min / Max", f"{int(df['bpm'].min())} / {int(df['bpm'].max())}")
        c4.metric("Average", f"{int(df['bpm'].mean())} bpm")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["bpm"], mode="lines+markers",
            line=dict(color="#e63946", width=2), marker=dict(size=5),
            fill="tozeroy", fillcolor="rgba(230,57,70,0.1)", name="bpm",
        ))
        fig.update_layout(
            height=420, margin=dict(l=10, r=10, t=30, b=10),
            yaxis_title="bpm", xaxis_title=None,
            yaxis=dict(range=[max(0, df["bpm"].min() - 15), df["bpm"].max() + 15]),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        c2.metric("Current", "—")
        st.info("Waiting for the first reading… make sure the band service is running "
                "and the band is on your wrist.")


live_view()
