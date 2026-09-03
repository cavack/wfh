from datetime import UTC, datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.enrich_historical_microstructure import _depth_rows_for_events, _trade_rows_for_events


def _zip_csv(name: str, text: str) -> bytes:
    target = BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        archive.writestr(name, text)
    return target.getvalue()


def test_trade_selection_is_causal_ttl_bounded_and_maps_taker_side():
    event = 1_000_000
    rows = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"]
    rows.append(f"1,10,2,1,1,{event-60_001},true")
    rows.append(f"2,10,3,2,2,{event-60_000},true")
    rows.append(f"3,11,4,3,3,{event},false")
    rows.append(f"4,12,5,4,4,{event+1},true")
    payload = _zip_csv("x.csv", "\n".join(rows))
    selected = _trade_rows_for_events(payload, [event])[event]
    assert [(row["timestamp"], row["side"], row["amount"]) for row in selected] == [
        (event - 60_000, "sell", 3.0),
        (event, "buy", 4.0),
    ]


def test_trade_selection_caps_to_latest_100():
    event = 2_000_000
    rows = ["agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker"]
    for index in range(120):
        rows.append(f"{index},10,1,{index},{index},{event-119+index},true")
    selected = _trade_rows_for_events(_zip_csv("x.csv", "\n".join(rows)), [event])[event]
    assert len(selected) == 100
    assert selected[0]["timestamp"] == event - 99
    assert selected[-1]["timestamp"] == event


def test_depth_selection_never_uses_future_snapshot():
    event_dt = datetime(2026, 8, 1, 0, 0, 5, tzinfo=UTC)
    event = int(event_dt.timestamp() * 1000)
    rows = ["timestamp,percentage,depth,notional"]
    for second, bid, ask in [(4, 100, 200), (6, 999, 999)]:
        stamp = f"2026-08-01 00:00:0{second}"
        rows.extend([f"{stamp},-1.00,1,{bid}", f"{stamp},1.00,1,{ask}"])
    selected = _depth_rows_for_events(_zip_csv("x.csv", "\n".join(rows)), [event])[event]
    assert selected["observed_at_ms"] == event - 1000
    assert selected["bid_depth_1pct_usdt"] == 100.0
    assert selected["ask_depth_1pct_usdt"] == 200.0
