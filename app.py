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
ANALYSIS_MODES = ["글로벌 시장만 분석", "사용자 데이터 추가 분석"]
TAB_LABELS = ["시장 요약", "글로벌 분석", "업로드 데이터 분석", "비교 분석", "규칙 확인"]
MARKET_STATES = [
    "Risk-on",
    "Risk-off",
    "Rate Pressure",
    "Dollar Stress",
    "Volatility Expansion",
    "Mixed",
]
DATE_FORMAT_CHOICES = ["자동", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%m/%d/%Y", "%d/%m/%Y"]
NUMBER_FORMAT_CHOICES = ["일반 숫자", "퍼센트(%)"]
VALIDATION_FAIL_LIMIT = 0.2


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


def preprocess_uploaded(raw, mapping, date_format_choice="자동", number_format_choice="일반 숫자"):
    out = pd.DataFrame()
    out["date_raw"] = raw[mapping["date"]]
    out["close_raw"] = raw[mapping["close"]]

    if date_format_choice != "자동":
        out["date"] = pd.to_datetime(out["date_raw"], format=date_format_choice, errors="coerce")
        failed = out["date"].isna()
        out.loc[failed, "date"] = pd.to_datetime(out.loc[failed, "date_raw"], errors="coerce")
    else:
        out["date"] = pd.to_datetime(out["date_raw"], errors="coerce")

    close_series = out["close_raw"].astype(str)
    close_series = (
        close_series.str.replace(",", "", regex=False)
        .str.replace("원", "", regex=False)
        .str.replace("$", "", regex=False)
    )
    if number_format_choice == "퍼센트(%)":
        close_series = close_series.str.replace("%", "", regex=False)
        out["close"] = pd.to_numeric(close_series, errors="coerce") / 100
    else:
        out["close"] = pd.to_numeric(close_series.str.replace("%", "", regex=False), errors="coerce")

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


def build_analysis_availability(prep, has_required, has_id):
    valid = prep.dropna(subset=["date", "close", "ticker"])
    max_rows_per_ticker = 0 if valid.empty else valid.groupby("ticker").size().max()
    return {
        "기본 시계열 분석": has_required and has_id and not valid.empty,
        "5일 수익률": max_rows_per_ticker >= 6,
        "20일 수익률": max_rows_per_ticker >= 21,
    }


def render_uploaded_result(result):
    latest_uploaded = latest_by_ticker(result)
    c1, c2, c3 = st.columns(3)
    c1.metric("업로드 자산 수", f"{result['ticker'].nunique()}")
    c2.metric("업로드 기준일", str(result["date"].max().date()))
    c3.metric("평균 20일 수익률", f"{latest_uploaded['return_20d'].mean():.2%}")

    st.dataframe(result.tail(10))
    ufig = px.line(result, x="date", y="close", color="ticker", title="업로드 데이터 가격 추이")
    st.plotly_chart(ufig, use_container_width=True)
    ubar = px.bar(
        latest_uploaded,
        x="ticker",
        y=["return_5d", "return_20d"],
        barmode="group",
        title="업로드 데이터 최신 5일/20일 수익률",
    )
    st.plotly_chart(ubar, use_container_width=True)


if "analysis_mode" not in st.session_state:
    st.session_state.analysis_mode = "글로벌 시장만 분석"
if "uploaded_result" not in st.session_state:
    st.session_state.uploaded_result = None
if "mapping_result" not in st.session_state:
    st.session_state.mapping_result = None
if "validation_rows" not in st.session_state:
    st.session_state.validation_rows = []
if "preprocess_preview" not in st.session_state:
    st.session_state.preprocess_preview = None

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

tab1, tab2, tab3, tab4, tab5 = st.tabs(TAB_LABELS)

with tab1:
    st.subheader("시장 요약")
    st.radio(
        "분석 모드 선택",
        ANALYSIS_MODES,
        horizontal=True,
        key="analysis_mode",
        help="사용자 데이터 추가 분석을 선택해도 업로드는 업로드 데이터 분석 탭에서만 진행합니다.",
    )
    mode = st.session_state.analysis_mode

    c1, c2, c3 = st.columns(3)
    c1.metric("글로벌 시장 상태", market_state)
    c2.metric("자산 수", f"{global_df['ticker'].nunique()}")
    c3.metric("기준일", str(global_df["date"].max().date()))

    if mode == "사용자 데이터 추가 분석":
        st.info("사용자 데이터 추가 분석이 선택되었습니다. CSV 업로드와 컬럼 매핑은 '업로드 데이터 분석' 탭에서 진행하세요.")

with tab2:
    st.subheader("글로벌 분석")
    st.markdown("#### 글로벌 자산 흐름")
    pick = st.multiselect("자산 선택", sorted(global_df["ticker"].unique()), default=["SPX", "NQ", "VIX"])
    plot_df = global_df[global_df["ticker"].isin(pick)]
    if plot_df.empty:
        st.warning("선택된 자산이 없어 차트를 표시할 수 없습니다.")
    else:
        fig = px.line(plot_df, x="date", y="close", color="ticker", title="가격 추이")
        st.plotly_chart(fig, use_container_width=True)
        bar = px.bar(latest_global, x="ticker", y=["return_5d", "return_20d"], barmode="group", title="최신 5일/20일 수익률")
        st.plotly_chart(bar, use_container_width=True)

    st.markdown("#### 시장 신호")
    cond = {state: market_state == state for state in MARKET_STATES}
    st.dataframe(pd.DataFrame({"signal": list(cond.keys()), "active": list(cond.values())}))

with tab3:
    st.subheader("업로드 데이터 분석")
    up = st.file_uploader("CSV 파일 업로드", type=["csv"])
    if up is None:
        st.warning("CSV 파일을 업로드하면 검증·전처리·분석 흐름이 활성화됩니다.")
    else:
        raw = pd.read_csv(up)

        st.markdown("#### 1) 원본 데이터 미리보기")
        st.dataframe(raw.head(10))

        st.markdown("#### 2) 컬럼 매핑 UI")
        cols = [None] + list(raw.columns)
        auto = auto_map(raw.columns)
        mapping = {}
        for k in ["date", "close", "ticker", "indicator_name"]:
            default = auto.get(k)
            idx = cols.index(default) if default in cols else 0
            mapping[k] = st.selectbox(f"{k} 매핑", cols, index=idx, key=f"map_{k}")
        st.session_state.mapping_result = mapping

        st.markdown("#### 3) 날짜·숫자 형식 선택")
        c1, c2 = st.columns(2)
        date_choice = c1.selectbox("날짜 형식", DATE_FORMAT_CHOICES)
        num_choice = c2.selectbox("숫자 형식", NUMBER_FORMAT_CHOICES)

        has_required = all(mapping.get(k) is not None for k in REQUIRED)
        has_id = (mapping.get("ticker") is not None) or (mapping.get("indicator_name") is not None)

        st.markdown("#### 4) 검증 결과")
        if not has_required or not has_id:
            st.error("필수 매핑 부족: date/close 및 ticker 또는 indicator_name이 필요합니다.")
        else:
            prep = preprocess_uploaded(raw, mapping, date_choice, num_choice)
            date_fail = prep["date"].isna().mean()
            close_fail = prep["close"].isna().mean()
            dupes = prep.duplicated(subset=["date", "ticker"]).sum()

            st.success("필수 컬럼 매핑 조건을 충족했습니다.")
            if date_fail <= VALIDATION_FAIL_LIMIT:
                st.success(f"날짜 변환 통과 (실패율 {date_fail:.1%})")
            else:
                st.error(f"날짜 변환 실패율 초과 ({date_fail:.1%})")
            if close_fail <= VALIDATION_FAIL_LIMIT:
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
                ["날짜 변환", "통과" if date_fail <= VALIDATION_FAIL_LIMIT else "실패"],
                ["숫자 변환", "통과" if close_fail <= VALIDATION_FAIL_LIMIT else "실패"],
                ["중복 데이터", "경고" if dupes > 0 else "통과"],
            ]
            st.session_state.validation_rows = validation_rows

            st.markdown("#### 5) 전처리 미리보기")
            preview = prep[["date_raw", "date", "close_raw", "close", "exclude"]].head(10)
            st.session_state.preprocess_preview = preview
            st.dataframe(preview)

            st.markdown("#### 6) 분석 가능 항목")
            analyzable = build_analysis_availability(prep, has_required, has_id)
            st.dataframe(pd.DataFrame({"항목": analyzable.keys(), "가능": analyzable.values()}))
            if not any(analyzable.values()):
                st.warning("현재 매핑과 변환 결과로는 분석 가능한 항목이 없습니다. 매핑 또는 형식 선택을 확인하세요.")

            st.markdown("#### 7) 분석 실행")
            can_run = (
                has_required
                and has_id
                and date_fail <= VALIDATION_FAIL_LIMIT
                and close_fail <= VALIDATION_FAIL_LIMIT
            )
            if st.button("업로드 시장 분석 실행", disabled=not can_run):
                clean = prep.dropna(subset=["date", "close", "ticker"]).sort_values(["ticker", "date"])
                clean = clean.drop_duplicates(subset=["date", "ticker"], keep="last")
                st.session_state.uploaded_result = compute_metrics(clean)

            st.markdown("#### 8) 업로드 시장 분석 결과")
            if st.session_state.uploaded_result is not None and not st.session_state.uploaded_result.empty:
                render_uploaded_result(st.session_state.uploaded_result)
            else:
                st.info("분석 실행 후 업로드 시장 분석 결과가 표시됩니다.")

with tab4:
    st.subheader("비교 분석")
    uploaded_result = st.session_state.uploaded_result
    if uploaded_result is None or uploaded_result.empty:
        st.warning("사용자 업로드 데이터 분석 결과가 없어 비교 분석을 표시하지 않습니다.")
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

with tab5:
    st.subheader("규칙 확인")
    st.info("현재 MVP는 핵심 규칙(필수 컬럼, 변환 실패율, 5D/20D 계산)을 적용합니다. 세부 규칙 문서는 Skills.md를 참고하세요.")
    if st.session_state.mapping_result:
        st.markdown("#### 최종 매핑")
        st.dataframe(pd.DataFrame(st.session_state.mapping_result.items(), columns=["표준 컬럼", "매핑 원본 컬럼"]))
    else:
        st.warning("아직 업로드 매핑 정보가 없습니다.")

    if st.session_state.validation_rows:
        st.markdown("#### 검증 결과")
        st.dataframe(pd.DataFrame(st.session_state.validation_rows, columns=["검증 항목", "상태"]))
    else:
        st.info("업로드 데이터 검증을 실행하면 결과가 표시됩니다.")

    if st.session_state.preprocess_preview is not None:
        st.markdown("#### 전처리 미리보기")
        st.dataframe(st.session_state.preprocess_preview)
    else:
        st.info("전처리 미리보기는 업로드 데이터 검증 후 표시됩니다.")

    st.caption("본 대시보드는 투자 데이터를 기반으로 시장 상태와 주요 신호를 요약하는 분석 도구입니다. 출력 결과는 투자 추천을 의미하지 않습니다.")