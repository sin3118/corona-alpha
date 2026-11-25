# 매수·매도 도우미 (claude-trading-skills)

`.claude/skills/` 에는 [tradermonty/claude-trading-skills](https://github.com/tradermonty/claude-trading-skills)
(MIT, commit 4080042)의 skill 12개가 들어 있다. 사용자는 한국어로 질문한다. 답변도 한국어로 한다.

## 원칙
- 주문은 절대 넣지 않는다. 결정과 실행은 사용자가 증권사 앱에서 직접 한다.
- 출력은 투자 조언이나 매매 신호가 아니다. 위험 관리와 계획을 돕는 정보다.
- 스크립트 출력에 `$` 가 붙어도 계산은 통화와 무관하다. 원화로 바꿔서 설명한다.
- 결과 파일은 `reports/`, 상태 파일은 `state/` 에 둔다. 둘 다 gitignore 대상이다.

## 매수 전 루틴 (API 키 불필요)
1. 시장 점검: 새로 사도 되는 시장인지 본다.
   ```bash
   python3 .claude/skills/market-breadth-analyzer/scripts/market_breadth_analyzer.py --output-dir reports
   python3 .claude/skills/uptrend-analyzer/scripts/uptrend_analyzer.py --output-dir reports
   python3 .claude/skills/exposure-coach/scripts/calculate_exposure.py \
     --breadth reports/market_breadth_<타임스탬프>.json \
     --uptrend reports/uptrend_analysis_<타임스탬프>.json --output-dir reports
   ```
   - `--breadth` 에는 `market_breadth_history.json` 말고 타임스탬프가 붙은 파일을 넘긴다.
   - 결과가 `CASH_PRIORITY` 나 `REDUCE_ONLY` 이면 신규 매수를 줄이라는 뜻이다. 입력이 두 개뿐이면 신뢰도는 LOW 다.
2. 수량 계산: `position-sizer`
   ```bash
   python3 .claude/skills/position-sizer/scripts/position_sizer.py \
     --account-size 10000000 --entry 70000 --stop 66500 --risk-pct 1
   ```
3. 계획 세우기: 차트 이미지가 있으면 `technical-analyst`, VCP 후보가 있으면 `breakout-trade-planner`.
4. 주문 전 점검: `drawdown-circuit-breaker` 로 오늘 새 위험을 질 수 있는지 확인한다. 그다음 `pre-trade-discipline-gate` 로 계획, 비중, 보복 매매 여부를 점검한다.

## 매도 후 루틴
- `trader-memory-core`: 매수 논리(thesis)를 등록하고, 청산과 손익을 기록한다.
- `signal-postmortem`: 매매가 왜 맞았는지 또는 틀렸는지 복기한다.
- `weekly-performance-digest`: 주간 승률, 기대값, R-multiple.

## 매일 아침 보고 (VOO, QQQ, UNH)
1. `python3 scripts/daily_us_review.py` 를 실행한다 (약 1분). 결과는 `reports/daily/<날짜>/data.md` 에 저장된다.
   - 내용: 시장 지표, 업종 ETF, 시장 점검 판정, 관심 종목 숫자와 신호.
2. WebSearch 로 전날 미국 증시 마감 기사와 VOO, QQQ, UNH 관련 뉴스를 찾는다. 출처 링크를 붙인다.
3. 보고서는 한국어로 쓰고 순서를 지킨다: 한 줄 요약 → 전날 시황 → 시장 점검 판정 → 종목별 검토(상태 OK/WARN/REVIEW, 바뀐 점, 지켜볼 가격) → 오늘 확인할 것.
4. 매수·매도를 지시하지 않는다. 전날과 비교해 판정이나 신호가 바뀐 점을 가장 먼저 쓴다.
5. 관심 종목이나 지지 가격을 바꾸려면 스크립트의 `--watch` 옵션과 `LEVELS` 를 고친다.

## 어디서 시작할지 모를 때
```bash
python3 .claude/skills/trading-skills-navigator/scripts/recommend.py \
  --query "<목표>" --no-api --experience beginner
```

## 네트워크
시장 점검에는 `tradermonty.github.io` 와 `raw.githubusercontent.com`, 시세에는 `query1.finance.yahoo.com` 접근이 필요하다
(클라우드 환경 "corona-alpha" 에서 허용됨). FMP, FINVIZ, Alpaca를 쓰는 skill은 API 키가 필요해서 설치하지 않았다.
