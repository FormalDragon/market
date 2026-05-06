import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="글로벌 시장 대시보드 MVP", layout="wide")
st.title("Streamlit 투자 데이터 분석 MVP")
st.caption("내장 글로벌 자산 + 사용자 업로드 CSV 기반 분석 (API 키 불필요)")

COLUMN_HINTS = {
    "date": ["date", "Date", "날짜", "기준일", "일자", "trading_date", "time"],
    "ticker": ["ticker", "code", "symbol", "종목코드", "지표코드", "ETF코드", "코드", "Code"],
    "indicator_name": ["name", "asset_name", "indicator_name", "지표명", "자산명", "종목명", "이름", "Name"],
    "close": ["close", "Close", "price", "value", "종가", "지수값", "가격", "기준가", "값"],
}

REQUIRED = ["date", "close"]


def auto_map(cols):
    mapped = {}
    for std, hints in COLUMN_HINTS.items():
        mapped[std] = next((c for c in cols if c in hints), None)
        if mapped[std] is None:
            mapped[std] = next((c for c in cols if c.lower() in [h.lower() for h in hints]), None)
    return mapped


def compute_metrics(df):
    df = df.sort_values(["ticker", "date"]).copy()
    g = df.groupby("ticker", group_keys=False)
    df["return_5d"] = g["close"].pct_change(5)
    df["return_20d"] = g["close"].pct_change(20)
    return df


def latest_by_ticker(df):
    return df.sort_values(["ticker", "date"]).groupby("ticker", as_index=False).tail(1)


def classify_state(latest):
    def safe(t, col):
        x = latest.loc[latest["ticker"] == t, col]
        return None if x.empty else x.iloc[0]

    spx20, nq20 = safe("SPX", "return_20d"), safe("NQ", "return_20d")
    vix20, us10y20 = safe("VIX", "return_20d"), safe("US10Y", "return_20d")
    dxy20 = safe("DXY", "return_20d")

    if all(v is not None for v in [spx20, nq20, vix20]) and spx20 > 0 and nq20 > 0 and vix20 < 0:
        return "Risk-on"
    if all(v is not None for v in [spx20, nq20, vix20]) and spx20 < 0 and nq20 < 0 and vix20 > 0:
        return "Risk-off"
    if all(v is not None for v in [us10y20, nq20]) and us10y20 > 0.01 and nq20 < 0:
        return "Rate Pressure"
    if all(v is not None for v in [dxy20, spx20]) and dxy20 > 0 and spx20 < 0:
        return "Dollar Stress"
    if vix20 is not None and vix20 > 0.08:
        return "Volatility Expansion"
    return "Mixed"


def preprocess_uploaded(raw, mapping):
    out = pd.DataFrame()
    out["date_raw"] = raw[mapping["date"]]
    out["close_raw"] = raw[mapping["close"]]
    out["date"] = pd.to_datetime(out["date_raw"], errors="coerce")
    close_series = out["close_raw"].astype(str).str.replace(",", "", regex=False)
    out["close"] = pd.to_numeric(close_series, errors="coerce")

    if mapping.get("ticker"):
        out["ticker"] = raw[mapping["ticker"]].astype(str)
    elif mapping.get("indicator_name"):
        out["ticker"] = raw[mapping["indicator_name"]].astype(str)
    else:
        out["ticker"] = "UNKNOWN"

    if mapping.get("indicator_name"):
        out["indicator_name"] = raw[mapping["indicator_name"]].astype(str)

    out["exclude"] = out[["date", "close", "ticker"]].isna().any(axis=1)
    return out


# 1) 내장 데이터
try:
    global_raw = pd.read_csv("data/global_assets.csv")
    global_raw["date"] = pd.to_datetime(global_raw["date"], errors="coerce")
    global_raw["close"] = pd.to_numeric(global_raw["close"], errors="coerce")
    global_df = compute_metrics(global_raw.dropna(subset=["date", "close", "ticker"]))
    latest_global = latest_by_ticker(global_df)
    market_state = classify_state(latest_global)
    st.success("내장 글로벌 자산 데이터 로드에 성공했습니다.")
except Exception as e:
    st.error(f"내장 데이터 로드 실패: {e}")
    st.stop()

# 2) 탭

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "시장 요약", "글로벌 자산 흐름", "시장 신호", "업로드 데이터 분석", "글로벌-특정 시장 비교", "검증 및 규칙 확인"
])

with tab1:
    c1, c2, c3 = st.columns(3)
    c1.metric("글로벌 시장 상태", market_state)
    c2.metric("자산 수", f"{global_df['ticker'].nunique()}")
    c3.metric("기준일", str(global_df["date"].max().date()))
    st.write("본 대시보드는 투자 추천이 아닌 시장 상태 요약 도구입니다.")

with tab2:
    st.subheader("내장 글로벌 자산 추이")
    pick = st.multiselect("자산 선택", sorted(global_df["ticker"].unique()), default=["SPX", "NQ", "VIX"])
    plot_df = global_df[global_df["ticker"].isin(pick)]
    fig = px.line(plot_df, x="date", y="close", color="ticker", title="가격 추이")
    st.plotly_chart(fig, use_container_width=True)
    bar = px.bar(latest_global, x="ticker", y=["return_5d", "return_20d"], barmode="group", title="최신 5일/20일 수익률")
    st.plotly_chart(bar, use_container_width=True)

with tab3:
    st.subheader("시장 신호")
    st.write(f"현재 분류: **{market_state}**")
    cond = {
        "Risk-on": market_state == "Risk-on",
        "Risk-off": market_state == "Risk-off",
        "Rate Pressure": market_state == "Rate Pressure",
        "Dollar Stress": market_state == "Dollar Stress",
        "Volatility Expansion": market_state == "Volatility Expansion",
        "Mixed": market_state == "Mixed",
    }
    st.dataframe(pd.DataFrame({"signal": list(cond.keys()), "active": list(cond.values())}))

uploaded_result = None
mapping_result = None
validation_rows = []

with tab4:
    st.subheader("사용자 CSV 업로드")
    up = st.file_uploader("CSV 파일 업로드", type=["csv"])
    if up is None:
        st.warning("사용자 업로드 데이터가 없어 특정 시장 분석은 수행하지 않았습니다.")
    else:
        raw = pd.read_csv(up)
        st.write("원본 미리보기")
        st.dataframe(raw.head(10))

        cols = [None] + list(raw.columns)
        auto = auto_map(raw.columns)
        mapping = {}
        st.markdown("#### 컬럼 매핑")
        for k in ["date", "close", "ticker", "indicator_name"]:
            default = auto.get(k)
            idx = cols.index(default) if default in cols else 0
            mapping[k] = st.selectbox(f"{k} 매핑", cols, index=idx, key=f"map_{k}")

        mapping_result = mapping

        has_required = all(mapping.get(k) is not None for k in REQUIRED)
        has_id = (mapping.get("ticker") is not None) or (mapping.get("indicator_name") is not None)
        if has_required and has_id:
            st.success("필수 컬럼 매핑 조건을 충족했습니다.")
        else:
            st.error("필수 매핑 부족: date/close 및 ticker 또는 indicator_name이 필요합니다.")

        if st.button("업로드 데이터 분석 실행", disabled=not (has_required and has_id)):
            prep = preprocess_uploaded(raw, mapping)
            date_fail = prep["date"].isna().mean()
            close_fail = prep["close"].isna().mean()
            dupes = prep.duplicated(subset=["date", "ticker"]).sum()

            if date_fail <= 0.2:
                st.success(f"날짜 변환 통과 (실패율 {date_fail:.1%})")
            else:
                st.error(f"날짜 변환 실패율 초과 ({date_fail:.1%})")
            if close_fail <= 0.2:
                st.success(f"숫자 변환 통과 (실패율 {close_fail:.1%})")
            else:
                st.error(f"숫자 변환 실패율 초과 ({close_fail:.1%})")
            if dupes > 0:
                st.warning(f"중복 데이터 {dupes}건 발견 (마지막 값 유지)")
            else:
                st.success("중복 데이터 없음")

            validation_rows = [
                ["필수 컬럼 매핑", "통과" if has_required else "실패"],
                ["지표 식별자", "통과" if has_id else "실패"],
                ["날짜 변환", "통과" if date_fail <= 0.2 else "실패"],
                ["숫자 변환", "통과" if close_fail <= 0.2 else "실패"],
                ["중복 데이터", "경고" if dupes > 0 else "통과"],
            ]

            clean = prep.dropna(subset=["date", "close", "ticker"]).sort_values(["ticker", "date"])
            clean = clean.drop_duplicates(subset=["date", "ticker"], keep="last")
            uploaded_result = compute_metrics(clean)
            st.dataframe(uploaded_result.head(10))

with tab5:
    st.subheader("글로벌-특정 시장 비교")
    if uploaded_result is None or uploaded_result.empty:
        st.warning("사용자 업로드 데이터가 없어 비교 분석을 수행하지 않았습니다.")
    else:
        last_up = latest_by_ticker(uploaded_result)
        up_5d = last_up["return_5d"].mean()
        up_20d = last_up["return_20d"].mean()
        g_5d = latest_global["return_5d"].mean()
        g_20d = latest_global["return_20d"].mean()
        c1, c2 = st.columns(2)
        c1.metric("글로벌 평균 5D/20D", f"{g_5d:.2%} / {g_20d:.2%}")
        c2.metric("업로드 평균 5D/20D", f"{up_5d:.2%} / {up_20d:.2%}")
        cmp = pd.DataFrame({"group": ["Global", "Uploaded"], "return_5d": [g_5d, up_5d], "return_20d": [g_20d, up_20d]})
        st.plotly_chart(px.bar(cmp, x="group", y=["return_5d", "return_20d"], barmode="group"), use_container_width=True)

with tab6:
    st.subheader("검증 및 규칙 확인")
    if mapping_result:
        st.write("최종 매핑")
        st.dataframe(pd.DataFrame(mapping_result.items(), columns=["표준 컬럼", "매핑 원본 컬럼"]))
    if validation_rows:
        st.write("검증 결과")
        st.dataframe(pd.DataFrame(validation_rows, columns=["검증 항목", "상태"]))
    st.info("본 대시보드는 투자 데이터를 기반으로 시장 상태와 주요 신호를 요약하는 분석 도구입니다. 출력 결과는 투자 추천을 의미하지 않습니다.")
